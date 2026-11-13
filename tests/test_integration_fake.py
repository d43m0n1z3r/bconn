"""End-to-end CLI tests against a fake BlueZ on a private D-Bus daemon.

No hardware and no root are required. dbus-daemon is part of the base system.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests" / "fake_bluez.py"
CLI = ROOT / "bin" / "bconn"
DAEMON = ROOT / "bin" / "bconn-daemon"


class FakeStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("dbus-daemon"):
            raise unittest.SkipTest("dbus-daemon is not installed")
        output = subprocess.check_output(
            [
                "dbus-daemon",
                "--session",
                "--fork",
                "--print-address=1",
                "--print-pid=1",
            ],
            text=True,
        ).splitlines()
        cls.bus_address = output[0].strip()
        cls.bus_pid = int(output[1].strip())

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "bus_pid", None):
            try:
                os.kill(cls.bus_pid, 15)
            except ProcessLookupError:
                pass

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.stderr_path = self.temp_path / "fake.err"
        env = os.environ.copy()
        env["DBUS_SYSTEM_BUS_ADDRESS"] = self.bus_address
        self.stderr_handle = open(self.stderr_path, "w")
        self.fake = subprocess.Popen(
            [sys.executable, str(FAKE)],
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_handle,
            env=env,
            cwd=ROOT,
        )
        self._wait_for_fake()

    def tearDown(self):
        if self.fake.poll() is None:
            self.fake.terminate()
            try:
                self.fake.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.fake.kill()
                self.fake.wait(timeout=5)
        self.stderr_handle.close()
        self.temp.cleanup()

    def _wait_for_fake(self):
        # CI runners can be slow to start the private bus and fake service.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.stderr_path.exists() and "ready" in self.stderr_path.read_text():
                return
            if self.fake.poll() is not None:
                raise AssertionError(
                    "fake BlueZ exited early:\n"
                    + self.stderr_path.read_text()
                )
            time.sleep(0.05)
        raise AssertionError(
            "fake BlueZ did not become ready:\n" + self.stderr_path.read_text()
        )

    def bconn(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["DBUS_SYSTEM_BUS_ADDRESS"] = self.bus_address
        env["XDG_CONFIG_HOME"] = str(self.temp_path / "config")
        env["XDG_STATE_HOME"] = str(self.temp_path / "state")
        env["NO_COLOR"] = "1"
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=ROOT,
        )

    def daemon(self, *args: str, timeout: float = 40) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["DBUS_SYSTEM_BUS_ADDRESS"] = self.bus_address
        env["XDG_CONFIG_HOME"] = str(self.temp_path / "config")
        env["XDG_STATE_HOME"] = str(self.temp_path / "state")
        return subprocess.run(
            [sys.executable, str(DAEMON), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=ROOT,
        )

    def write_config(self, *, auto_connect: bool = True, paused: bool = False) -> None:
        config_dir = self.temp_path / "config" / "bconn"
        config_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "auto_connect": True,
            "notifications": False,
            "devices": {
                "AA:BB:CC:DD:EE:FF": {
                    "alias": None,
                    "auto_connect": auto_connect,
                    "prefer_audio": True,
                    "paused": paused,
                    "forget_on_disconnect": False,
                }
            },
        }
        (config_dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    def assert_ok(self, result: subprocess.CompletedProcess):
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    # ------------------------------------------------------------------ tests

    def test_list(self):
        result = self.assert_ok(self.bconn("list"))
        self.assertIn("ADAPTER  hci0", result.stdout)
        self.assertIn("Buds", result.stdout)
        self.assertIn("AA:BB:CC:DD:EE:FF", result.stdout)
        self.assertIn("audio", result.stdout)

    def test_scan(self):
        result = self.assert_ok(self.bconn("scan", "--timeout", "2"))
        self.assertIn("found Buds", result.stdout)
        self.assertIn("-52 dBm", result.stdout)

    def test_pair_and_connect(self):
        pair = self.assert_ok(self.bconn("pair", "Buds", "--yes"))
        self.assertIn("Paired", pair.stdout)
        self.assertIn("Trusted", pair.stdout)

        connect = self.assert_ok(self.bconn("connect", "Buds", "--no-audio"))
        self.assertIn("Connected", connect.stdout)

        listing = self.assert_ok(self.bconn("list"))
        self.assertIn("connected", listing.stdout)

    def test_connect_pairs_automatically(self):
        result = self.assert_ok(self.bconn("connect", "Buds", "--yes", "--no-audio"))
        self.assertIn("Paired", result.stdout)
        self.assertIn("Connected", result.stdout)

    def test_connect_by_mac(self):
        result = self.assert_ok(
            self.bconn("connect", "aa:bb:cc:dd:ee:ff", "--yes", "--no-audio")
        )
        self.assertIn("Connected", result.stdout)

    def test_disconnect(self):
        self.assert_ok(self.bconn("connect", "Buds", "--yes", "--no-audio"))
        result = self.assert_ok(self.bconn("disconnect", "Buds"))
        self.assertIn("Disconnected", result.stdout)
        self.assertIn("paused", result.stdout)

    def test_power_toggle(self):
        off = self.assert_ok(self.bconn("power", "off"))
        self.assertIn("off", off.stdout)
        on = self.assert_ok(self.bconn("power", "on"))
        self.assertIn("on", on.stdout)

    def test_auto_opt_in(self):
        self.assert_ok(self.bconn("connect", "Buds", "--yes", "--no-audio"))
        enabled = self.assert_ok(self.bconn("auto", "Buds", "on"))
        self.assertIn("enabled", enabled.stdout)
        listing = self.assert_ok(self.bconn("auto"))
        self.assertIn("on", listing.stdout)
        disabled = self.assert_ok(self.bconn("auto", "Buds", "off"))
        self.assertIn("disabled", disabled.stdout)

    def test_forget(self):
        self.assert_ok(self.bconn("connect", "Buds", "--yes", "--no-audio"))
        result = self.assert_ok(self.bconn("forget", "Buds", "--yes"))
        self.assertIn("Forgot", result.stdout)
        listing = self.assert_ok(self.bconn("list"))
        self.assertNotIn("Buds", listing.stdout)

    def test_info(self):
        self.assert_ok(self.bconn("connect", "Buds", "--yes", "--no-audio"))
        result = self.assert_ok(self.bconn("info", "Buds"))
        self.assertIn("WH-1000XM4", result.stdout)
        self.assertIn("Connected          yes", result.stdout)

    def test_missing_device_errors_without_scan(self):
        result = self.bconn("connect", "Nope", "--no-scan")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No device matches", result.stderr)

    def test_unknown_device_scans_then_errors(self):
        result = self.bconn("connect", "Ghost", "--no-audio", "--timeout", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scanning", result.stderr)
        self.assertIn("No device matches", result.stderr)

    # ------------------------------------------------------------ daemon tests

    def test_daemon_skips_unpaired_device(self):
        self.write_config(auto_connect=True)
        result = self.daemon("--once", "--no-audio", "--no-notify", "--scan", "2")
        self.assert_ok(result)
        self.assertIn("unpaired: Buds", result.stdout)

    def test_daemon_once_connects_opted_in_device(self):
        self.assert_ok(self.bconn("pair", "Buds", "--yes"))
        self.write_config(auto_connect=True)
        result = self.daemon("--once", "--no-audio", "--no-notify", "--scan", "2")
        self.assert_ok(result)
        self.assertIn("connected: Buds", result.stdout)

        listing = self.assert_ok(self.bconn("list"))
        self.assertIn("connected", listing.stdout)

    def test_daemon_respects_paused_device(self):
        self.assert_ok(self.bconn("pair", "Buds", "--yes"))
        self.write_config(auto_connect=True, paused=True)
        result = self.daemon("--once", "--no-audio", "--no-notify", "--scan", "2")
        self.assert_ok(result)
        self.assertIn("nothing to do", result.stdout)

    def test_daemon_skips_auto_connect_disabled_device(self):
        self.assert_ok(self.bconn("pair", "Buds", "--yes"))
        self.write_config(auto_connect=False)
        result = self.daemon("--once", "--no-audio", "--no-notify", "--scan", "2")
        self.assert_ok(result)
        self.assertIn("nothing to do", result.stdout)


if __name__ == "__main__":
    unittest.main()
