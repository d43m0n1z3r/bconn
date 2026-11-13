import unittest

from bconn.audio import (
    AudioRoutingError,
    find_sink_for_address,
    parse_snapshot,
    select_sink,
)


def snapshot():
    return [
        {
            "id": 41,
            "type": "PipeWire:Interface:Metadata",
            "props": {"metadata.name": "default"},
            "metadata": [
                {
                    "key": "default.audio.sink",
                    "value": {"name": "bluez_output.AA_BB_CC_DD_EE_FF.1"},
                }
            ],
        },
        {
            "id": 57,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "node.name": "alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink",
                    "node.description": "Laptop speakers",
                }
            },
        },
        {
            "id": 61,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Sink",
                    "node.name": "bluez_output.AA_BB_CC_DD_EE_FF.1",
                    "node.description": "WH-1000XM4",
                    "api.bluez5.address": "AA:BB:CC:DD:EE:FF",
                }
            },
        },
        {
            "id": 62,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "node.name": "bluez_input.AA_BB_CC_DD_EE_FF.0",
                }
            },
        },
    ]


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.sinks = parse_snapshot(snapshot())
        self.by_id = {sink.id: sink for sink in self.sinks}

    def test_only_sinks_are_parsed(self):
        self.assertEqual(sorted(self.by_id), [57, 61])

    def test_default_from_metadata(self):
        self.assertTrue(self.by_id[61].is_default)
        self.assertFalse(self.by_id[57].is_default)

    def test_bluetooth_address(self):
        self.assertEqual(self.by_id[61].address, "AA:BB:CC:DD:EE:FF")
        self.assertTrue(self.by_id[61].is_bluetooth)
        self.assertFalse(self.by_id[57].is_bluetooth)

    def test_address_fallback_from_node_name(self):
        data = snapshot()
        del data[2]["info"]["props"]["api.bluez5.address"]
        sinks = parse_snapshot(data)
        buds = next(sink for sink in sinks if sink.id == 61)
        self.assertEqual(buds.address, "AA:BB:CC:DD:EE:FF")

    def test_find_by_address(self):
        self.assertEqual(
            find_sink_for_address(self.sinks, "aa:bb:cc:dd:ee:ff").id, 61
        )
        self.assertEqual(
            find_sink_for_address(self.sinks, "AABBCCDDEEFF").id, 61
        )

    def test_select_by_id(self):
        self.assertEqual(select_sink(self.sinks, "57").id, 57)

    def test_select_by_name(self):
        self.assertEqual(select_sink(self.sinks, "speakers").id, 57)

    def test_select_by_mac(self):
        self.assertEqual(select_sink(self.sinks, "AA:BB:CC:DD:EE:FF").id, 61)
        self.assertEqual(select_sink(self.sinks, "AABBCCDDEEFF").id, 61)

    def test_select_missing(self):
        with self.assertRaises(AudioRoutingError):
            select_sink(self.sinks, "nope")

    def test_ambiguous(self):
        data = snapshot()
        data.append(
            {
                "id": 63,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Sink",
                        "node.name": "bluez_output.AA_BB_CC_DD_EE_FF.2",
                        "node.description": "WH-1000XM4",
                        "api.bluez5.address": "AA:BB:CC:DD:EE:FF",
                    }
                },
            }
        )
        sinks = parse_snapshot(data)
        with self.assertRaises(AudioRoutingError):
            select_sink(sinks, "WH-1000XM4")


if __name__ == "__main__":
    unittest.main()
