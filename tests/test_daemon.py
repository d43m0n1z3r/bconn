"""Tests for the auto-reconnect daemon and its systemd unit."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bconn import daemon


class BackoffTests(unittest.TestCase):
    def test_no_failures(self):
        self.assertEqual(daemon.backoff_delay(0), 0.0)

    def test_exponential_growth(self):
        self.assertEqual(daemon.backoff_delay(1), 15.0)
        self.assertEqual(daemon.backoff_delay(2), 30.0)
        self.assertEqual(daemon.backoff_delay(3), 60.0)
        self.assertEqual(daemon.backoff_delay(4), 120.0)
        self.assertEqual(daemon.backoff_delay(5), 240.0)

    def test_cap(self):
        self.assertEqual(daemon.backoff_delay(6), 300.0)
        self.assertEqual(daemon.backoff_delay(50), 300.0)


class UnitFileTests(unittest.TestCase):
    def test_render_unit_points_at_launcher(self):
        text = daemon.render_unit(poll_seconds=45)
        self.assertIn("[Service]", text)
        self.assertIn("[Install]", text)
        self.assertIn("ExecStart=", text)
        self.assertIn("bin/bconn-daemon", text)
        self.assertIn("Environment=BCONN_POLL_SECONDS=45", text)
        self.assertIn("WantedBy=default.target", text)
        self.assertIn("Restart=on-failure", text)

    def test_unit_path_honours_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": temp}, clear=False
            ):
                self.assertEqual(
                    daemon.unit_path(),
                    Path(temp) / "systemd" / "user" / "bconn-daemon.service",
                )


class DaemonSelectionTests(unittest.TestCase):
    def test_no_notifications_when_disabled(self):
        calls = []
        d = daemon.AutoConnectDaemon(
            notifications=False,
            notifier=lambda *args: calls.append(args),
        )
        d.notify("hello")
        self.assertEqual(calls, [])

    def test_notifier_used_when_enabled(self):
        calls = []
        d = daemon.AutoConnectDaemon(
            notifications=True,
            notifier=lambda *args: calls.append(args),
        )
        d.notify("hello", "body", "low")
        self.assertEqual(calls, [("hello", "body", "low")])


if __name__ == "__main__":
    unittest.main()
