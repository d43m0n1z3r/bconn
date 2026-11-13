import unittest

from bconn.bluez import Device, parse_objects


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


class ClassOfDeviceTests(unittest.TestCase):
    def device(self, **kwargs) -> Device:
        return Device(path="/org/bluez/hci0/dev_AA", address="AA:BB:CC:DD:EE:FF", **kwargs)

    def test_parses_class_property(self):
        objects = managed_objects()
        objects["/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"]["org.bluez.Device1"][
            "Class"
        ] = 0x00010C
        _, devices = parse_objects(objects)
        mystery = next(d for d in devices if d.address == "AA:BB:CC:DD:EE:02")
        self.assertEqual(mystery.device_class, 0x00010C)
        self.assertEqual(mystery.major_class, 0x01)

    def test_phone_from_class(self):
        phone = self.device(device_class=0x7A020C)
        self.assertEqual(phone.kind, "phone")
        self.assertTrue(phone.supports_file_transfer)

    def test_phone_wins_over_audio_profiles(self):
        # Real phones advertise A2DP/HFP plus PBAP/MAP; audio must not win.
        phone = self.device(
            icon="phone",
            device_class=0x005A020C,
            uuids=(
                "00001105-0000-1000-8000-00805f9b34fb",  # OBEX Object Push
                "0000110a-0000-1000-8000-00805f9b34fb",  # Audio Source
                "0000110e-0000-1000-8000-00805f9b34fb",  # A/V Remote Control
                "0000111f-0000-1000-8000-00805f9b34fb",  # Handsfree AG
                "0000112f-0000-1000-8000-00805f9b34fb",  # PBAP Server
            ),
        )
        self.assertTrue(phone.is_phone)
        self.assertFalse(phone.is_audio)
        self.assertEqual(phone.kind, "phone")
        self.assertTrue(phone.supports_file_transfer)

    def test_phone_uuid_without_icon_or_class(self):
        phone = self.device(
            uuids=(
                "0000110a-0000-1000-8000-00805f9b34fb",  # Audio Source
                "0000112f-0000-1000-8000-00805f9b34fb",  # PBAP Server
            )
        )
        self.assertEqual(phone.kind, "phone")

    def test_headset_with_audio_profiles_stays_audio(self):
        headset = self.device(
            icon="audio-headset",
            uuids=(
                "00001108-0000-1000-8000-00805f9b34fb",  # Headset
                "0000110b-0000-1000-8000-00805f9b34fb",  # Audio Sink
                "0000111e-0000-1000-8000-00805f9b34fb",  # Handsfree
            ),
        )
        self.assertFalse(headset.is_phone)
        self.assertTrue(headset.is_audio)
        self.assertEqual(headset.kind, "audio")

    def test_computer_from_class(self):
        computer = self.device(device_class=0x00010C)
        self.assertEqual(computer.kind, "computer")

    def test_peripheral_is_input(self):
        keyboard = self.device(device_class=0x000540)
        self.assertTrue(keyboard.is_input)
        self.assertEqual(keyboard.kind, "input")
        self.assertFalse(keyboard.supports_file_transfer)

    def test_imaging_and_wearable(self):
        self.assertEqual(self.device(device_class=0x000680).kind, "imaging")
        self.assertEqual(self.device(device_class=0x000704).kind, "wearable")

    def test_computer_subtypes(self):
        self.assertEqual(self.device(device_class=0x000104).subtype, "desktop")
        self.assertEqual(self.device(device_class=0x00010C).subtype, "laptop")
        self.assertEqual(self.device(device_class=0x00011C).subtype, "tablet")

    def test_peripheral_subtypes(self):
        self.assertEqual(self.device(device_class=0x000540).subtype, "keyboard")
        self.assertEqual(self.device(device_class=0x000580).subtype, "mouse")
        self.assertEqual(self.device(device_class=0x000508).subtype, "gamepad")

    def test_imaging_subtypes(self):
        self.assertEqual(self.device(device_class=0x000610).subtype, "display")
        self.assertEqual(self.device(device_class=0x000620).subtype, "camera")
        self.assertEqual(self.device(device_class=0x000640).subtype, "scanner")
        self.assertEqual(self.device(device_class=0x000680).subtype, "printer")

    def test_wearable_and_phone_subtypes(self):
        self.assertEqual(self.device(device_class=0x000704).subtype, "watch")
        self.assertEqual(self.device(device_class=0x005A020C).subtype, "smartphone")
        self.assertEqual(self.device(device_class=0x00240404).subtype, "headset")

    def test_obex_uuid_marks_file_transfer(self):
        device = self.device(
            uuids=("00001105-0000-1000-8000-00805f9b34fb",)
        )
        self.assertTrue(device.supports_file_transfer)

    def test_unknown_unpaired_device_has_no_transfer_action(self):
        self.assertFalse(self.device().supports_file_transfer)

    def test_paired_unknown_device_can_receive_a_file(self):
        self.assertTrue(self.device(paired=True).supports_file_transfer)

    def test_audio_does_not_offer_file_transfer(self):
        device = self.device(
            icon="audio-headphones",
            uuids=("0000110b-0000-1000-8000-00805f9b34fb",),
        )
        self.assertEqual(device.kind, "audio")
        self.assertFalse(device.supports_file_transfer)


if __name__ == "__main__":
    unittest.main()
