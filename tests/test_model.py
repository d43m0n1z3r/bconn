"""Tests for the pure presentation helpers used by the scan window."""

import unittest
from types import SimpleNamespace

from bconn.ui import model


def device(kind: str, name: str = "Device", address: str = "AA:BB:CC:DD:EE:FF"):
    return SimpleNamespace(
        kind=kind,
        display_name=name,
        name=name,
        alias="",
        address=address,
    )


class FilterTests(unittest.TestCase):
    def test_other_filter_is_available(self):
        self.assertIn("other", model.FILTERS)
        self.assertEqual(model.FILTER_LABELS["other"], "Other")

    def test_computer_maps_to_other(self):
        computer = device("computer")
        self.assertEqual(model.device_filter(computer), "other")
        self.assertTrue(model.matches_filter(computer, "other"))
        self.assertFalse(model.matches_filter(computer, "audio"))

    def test_phone_and_input_have_their_own_tabs(self):
        phone = device("phone")
        keyboard = device("input")
        self.assertEqual(model.device_filter(phone), "phone")
        self.assertEqual(model.device_filter(keyboard), "input")

    def test_all_matches_everything(self):
        self.assertTrue(model.matches_filter(device("other"), "all"))

    def test_search_matches_name_and_address(self):
        buds = device("audio", name="Buds", address="41:42:03:AC:1D:1B")
        self.assertTrue(model.matches_search(buds, "bud"))
        self.assertTrue(model.matches_search(buds, "1d:1b"))
        self.assertFalse(model.matches_search(buds, "keyboard"))

    def test_subtype_icons(self):
        cases = {
            "laptop": "computer",
            "desktop": "computer",
            "tablet": "computer",
            "watch": "preferences-system-time",
            "printer": "printer",
            "scanner": "scanner",
            "camera": "camera-photo",
            "display": "video-display",
            "smartphone": "phone",
        }
        for subtype, expected in cases.items():
            with self.subTest(subtype=subtype):
                item = SimpleNamespace(
                    subtype=subtype,
                    kind="computer",
                    icon="",
                )
                self.assertEqual(model.device_icon(item), expected)

    def test_drawing_tablet_uses_input_icon(self):
        item = SimpleNamespace(subtype="tablet", kind="input", icon="")
        self.assertEqual(model.device_icon(item), "input-tablet")


if __name__ == "__main__":
    unittest.main()
