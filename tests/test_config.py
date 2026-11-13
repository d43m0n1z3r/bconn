import json
import tempfile
import unittest
from pathlib import Path

from bconn.config import Config, State


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.json"
        self.config = Config(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_are_opt_in(self):
        self.assertTrue(self.config.data["auto_connect"])
        self.assertEqual(self.config.data["devices"], {})
        entry = self.config.device("AA:BB:CC:DD:EE:FF")
        self.assertFalse(entry["auto_connect"])
        self.assertFalse(entry["paused"])

    def test_auto_connect_is_per_device(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.config.set_auto_connect(address, True)
        self.assertTrue(self.config.auto_connect_enabled(address))
        self.assertEqual(self.config.opted_in_devices(), [address])
        self.config.set_paused(address, True)
        self.assertFalse(self.config.auto_connect_enabled(address))
        self.assertEqual(self.config.opted_in_devices(), [])

    def test_master_switch_disables_all(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.config.set_auto_connect(address, True)
        self.config.data["auto_connect"] = False
        self.assertFalse(self.config.auto_connect_enabled(address))
        self.assertEqual(self.config.opted_in_devices(), [])

    def test_forget_removes_entry(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.config.set_auto_connect(address, True)
        self.config.forget(address)
        self.assertNotIn(address, self.config.data["devices"])

    def test_round_trip(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.config.set_auto_connect(address, True)
        reloaded = Config(self.path)
        self.assertTrue(reloaded.auto_connect_enabled(address))

    def test_corrupt_config_is_backed_up(self):
        self.path.write_text("{not json", encoding="utf-8")
        config = Config(self.path)
        self.assertTrue(config.warnings)
        self.assertEqual(config.data["devices"], {})
        backups = list(self.path.parent.glob("config.json.corrupt-*"))
        self.assertEqual(len(backups), 1)

    def test_device_entry_defaults_are_filled(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.config.data["devices"][address] = {"auto_connect": True}
        self.config.save()
        reloaded = Config(self.path)
        entry = reloaded.device(address)
        self.assertIn("paused", entry)
        self.assertIn("prefer_audio", entry)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        self.state = State(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_connected(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.state.record_connected(address)
        self.assertEqual(self.state.data["last_device"], address)
        self.assertIn("last_connected", self.state.data["devices"][address])

    def test_forget(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.state.record_connected(address)
        self.state.forget(address)
        self.assertNotIn(address, self.state.data["devices"])
        self.assertIsNone(self.state.data["last_device"])

    def test_round_trip(self):
        address = "AA:BB:CC:DD:EE:FF"
        self.state.record_battery(address, 82)
        reloaded = State(self.path)
        self.assertEqual(reloaded.data["devices"][address]["last_battery"], 82)


if __name__ == "__main__":
    unittest.main()
