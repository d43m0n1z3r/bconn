import unittest

from bconn.bluez import parse_objects


def managed_objects():
    return {
        "/org/bluez/hci0": {
            "org.bluez.Adapter1": {
                "Address": "AA:BB:CC:11:22:33",
                "Name": "Kali laptop",
                "Alias": "Kali",
                "Powered": True,
                "Discovering": False,
                "UUIDs": ["0000110b-0000-1000-8000-00805f9b34fb"],
            }
        },
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF": {
            "org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:FF",
                "Adapter": "/org/bluez/hci0",
                "Alias": "Buds",
                "Name": "WH-1000XM4",
                "Icon": "audio-headphones",
                "Paired": True,
                "Trusted": True,
                "Connected": True,
                "ServicesResolved": True,
                "RSSI": -52,
                "UUIDs": ["0000110b-0000-1000-8000-00805f9b34fb"],
            },
            "org.bluez.Battery1": {"Percentage": 82},
        },
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01": {
            "org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:01",
                "Adapter": "/org/bluez/hci0",
                "Name": "MX Keys",
                "Icon": "input-keyboard",
                "Paired": True,
            }
        },
        "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02": {
            "org.bluez.Device1": {
                "Address": "AA:BB:CC:DD:EE:02",
                "Adapter": "/org/bluez/hci0",
                "Name": "Mystery",
            }
        },
    }


class ParseObjectsTests(unittest.TestCase):
    def setUp(self):
        self.adapters, self.devices = parse_objects(managed_objects())
        self.by_address = {device.address: device for device in self.devices}

    def test_adapter(self):
        self.assertEqual(len(self.adapters), 1)
        adapter = self.adapters[0]
        self.assertEqual(adapter.address, "AA:BB:CC:11:22:33")
        self.assertEqual(adapter.alias, "Kali")
        self.assertTrue(adapter.powered)

    def test_devices(self):
        self.assertEqual(len(self.devices), 3)
        buds = self.by_address["AA:BB:CC:DD:EE:FF"]
        self.assertEqual(buds.display_name, "Buds")
        self.assertEqual(buds.name, "WH-1000XM4")
        self.assertEqual(buds.battery, 82)
        self.assertEqual(buds.rssi, -52)
        self.assertTrue(buds.connected)
        self.assertTrue(buds.is_audio)
        self.assertEqual(buds.kind, "audio")

    def test_input_device(self):
        keyboard = self.by_address["AA:BB:CC:DD:EE:01"]
        self.assertTrue(keyboard.is_input)
        self.assertEqual(keyboard.kind, "input")
        self.assertIsNone(keyboard.battery)

    def test_other_device(self):
        mystery = self.by_address["AA:BB:CC:DD:EE:02"]
        self.assertEqual(mystery.kind, "other")
        self.assertEqual(mystery.state, "known")

    def test_unknown_interfaces_are_ignored(self):
        objects = managed_objects()
        objects["/org/bluez/hci0"]["org.example.Foo"] = {"Bar": 1}
        adapters, devices = parse_objects(objects)
        self.assertEqual(len(adapters), 1)
        self.assertEqual(len(devices), 3)


if __name__ == "__main__":
    unittest.main()
