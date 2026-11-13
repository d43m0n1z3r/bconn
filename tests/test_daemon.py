"""Tests for the auto-reconnect daemon and its systemd unit."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bconn import bluez, daemon


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


class DaemonExecutableTests(unittest.TestCase):
    def test_prefers_installed_console_script(self):
        with mock.patch.object(
            daemon.shutil, "which", return_value="/home/me/.local/bin/bconn-daemon"
        ):
            self.assertEqual(
                daemon.daemon_executable(), "/home/me/.local/bin/bconn-daemon"
            )

    def test_falls_back_to_checkout_launcher(self):
        with mock.patch.object(daemon.shutil, "which", return_value=None):
            expected = str(daemon.project_root() / "bin" / "bconn-daemon")
            self.assertEqual(daemon.daemon_executable(), expected)


class UnitFileTests(unittest.TestCase):
    def test_render_unit_points_at_launcher(self):
        text = daemon.render_unit(poll_seconds=45)
        self.assertIn("[Service]", text)
        self.assertIn("[Install]", text)
        self.assertIn("ExecStart=", text)
        self.assertIn("bconn-daemon", text)
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


class DiscoveryGuardTests(unittest.TestCase):
    def make_daemon(self, discovering: bool):
        d = daemon.AutoConnectDaemon(notifications=False)
        d.config = mock.Mock()
        d.config.data = {"auto_connect": True}
        d.config.opted_in_devices.return_value = ["AA:BB:CC:DD:EE:FF"]
        d._reload_config = lambda: None
        d._maybe_connect = lambda *args: None
        adapter = bluez.Adapter(
            path="/org/bluez/hci0",
            address="AA:BB:CC:11:22:33",
            powered=True,
            discovering=discovering,
        )
        return d, adapter

    def run_cycle(self, d, adapter, scan):
        with mock.patch.object(
            daemon.bluez, "connect_system_bus", return_value=object()
        ), mock.patch.object(
            daemon.bluez, "get_objects", return_value=([adapter], [])
        ), mock.patch.object(
            daemon.bluez, "select_adapter", return_value=adapter
        ), mock.patch.object(
            daemon.bluez, "scan_devices", scan
        ):
            d._cycle()

    def test_skips_scan_when_another_client_is_discovering(self):
        d, adapter = self.make_daemon(discovering=True)
        scan = mock.Mock()
        self.run_cycle(d, adapter, scan)
        scan.assert_not_called()

    def test_scans_when_no_one_else_is_discovering(self):
        d, adapter = self.make_daemon(discovering=False)
        scan = mock.Mock(return_value=[])
        self.run_cycle(d, adapter, scan)
        scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
