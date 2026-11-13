import unittest

from bconn.bluez import Device, find_device, looks_like_mac
from bconn.errors import AmbiguousDevice, DeviceNotFound


def make_device(
    address: str, name: str = "", alias: str = "", **kwargs
) -> Device:
    return Device(path=f"/org/bluez/hci0/dev_{address.replace(':', '_')}",
                  address=address, name=name, alias=alias, **kwargs)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.buds = make_device(
            "AA:BB:CC:DD:EE:01",
            name="WH-1000XM4",
            alias="Buds",
            icon="audio-headphones",
        )
        self.speaker = make_device(
            "AA:BB:CC:DD:EE:02",
            name="SoundCore Mini",
            alias="",
            icon="audio-speakers",
        )
        self.keyboard = make_device(
            "AA:BB:CC:DD:EE:03",
            name="MX Keys",
            alias="",
            icon="input-keyboard",
        )
        self.devices = [self.buds, self.speaker, self.keyboard]

    def test_exact_colon_mac(self):
        self.assertIs(
            find_device(self.devices, "aa:bb:cc:dd:ee:01"), self.buds
        )

    def test_exact_bare_mac(self):
        self.assertIs(
            find_device(self.devices, "AABBCCDDEE03"), self.keyboard
        )

    def test_alias_substring(self):
        self.assertIs(find_device(self.devices, "bud"), self.buds)

    def test_name_substring(self):
        self.assertIs(find_device(self.devices, "soundcore"), self.speaker)

    def test_exact_name_beats_substring(self):
        other = make_device("AA:BB:CC:DD:EE:04", name="Buds Pro")
        self.assertIs(find_device(self.devices + [other], "buds"), self.buds)

    def test_ambiguous(self):
        other = make_device("AA:BB:CC:DD:EE:04", name="WH-1000XM4")
        with self.assertRaises(AmbiguousDevice):
            find_device(self.devices + [other], "wh-1000")

    def test_not_found(self):
        with self.assertRaises(DeviceNotFound):
            find_device(self.devices, "nope")

    def test_looks_like_mac(self):
        self.assertTrue(looks_like_mac("AA:BB:CC:DD:EE:FF"))
        self.assertTrue(looks_like_mac("aabbccddeeff"))
        self.assertTrue(looks_like_mac("AA-BB-CC-DD-EE-FF"))
        self.assertFalse(looks_like_mac("buds"))

    def test_device_kind_and_state(self):
        self.assertTrue(self.buds.is_audio)
        self.assertEqual(self.buds.kind, "audio")
        self.assertEqual(self.buds.state, "known")
        self.buds.connected = True
        self.assertEqual(self.buds.state, "connected")
        self.buds.blocked = True
        self.assertEqual(self.buds.state, "blocked")


if __name__ == "__main__":
    unittest.main()
