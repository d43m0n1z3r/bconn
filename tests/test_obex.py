"""Tests for the OBEX Object Push client (mocked D-Bus, no real device)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import gi

gi.require_version("Gio", "2.0")
from gi.repository import GLib  # noqa: E402

from bconn import obex
from bconn.errors import BconnError, ObexError


class FakeConn:
    def __init__(self, reply: GLib.Variant | None = None):
        self.reply = reply
        self.calls: list[tuple] = []

    def call_sync(self, *args):
        self.calls.append(args)
        return self.reply


class ClientCallTests(unittest.TestCase):
    def test_create_session_uses_opp_target(self):
        conn = FakeConn(GLib.Variant("(o)", ("/org/bluez/obex/session0",)))
        path = obex.create_session(conn, "41:42:03:AC:1D:1B")
        self.assertEqual(path, "/org/bluez/obex/session0")
        bus, obj, iface, method, params, *_ = conn.calls[0]
        self.assertEqual(bus, obex.OBEX)
        self.assertEqual(obj, obex.OBEX_PATH)
        self.assertEqual(iface, obex.CLIENT_IFACE)
        self.assertEqual(method, "CreateSession")
        self.assertEqual(
            params.unpack(),
            ("41:42:03:AC:1D:1B", {"Target": "opp"}),
        )

    def test_send_file_uses_resolved_path_and_name(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "photo.jpg"
            source.write_bytes(b"hello")
            conn = FakeConn(GLib.Variant("(oa{sv})", ("/transfer0", {})))
            path = obex.send_file(conn, "/session0", source)
        self.assertEqual(path, "/transfer0")
        _, obj, iface, method, params, *_ = conn.calls[0]
        self.assertEqual(obj, "/session0")
        self.assertEqual(iface, obex.OPP_IFACE)
        self.assertEqual(method, "SendFile")
        self.assertEqual(params.unpack(), (str(source.resolve()), "photo.jpg"))

    def test_send_file_rejects_missing_file(self):
        with self.assertRaises(BconnError):
            obex.send_file(FakeConn(), "/session0", Path("/nope/missing.bin"))


class WaitTransferTests(unittest.TestCase):
    def test_reports_progress_and_completes(self):
        seen: list[tuple[int, int]] = []

        def progress(source, transferred, size):
            seen.append((transferred, size))

        properties = [
            {"Status": "queued", "Transferred": 0, "Size": 4},
            {"Status": "active", "Transferred": 2, "Size": 4},
            {"Status": "complete", "Transferred": 4, "Size": 4},
        ]
        with mock.patch.object(
            obex, "_get_transfer_properties", side_effect=properties
        ), mock.patch.object(obex.time, "sleep"):
            result = obex.wait_transfer(
                FakeConn(),
                "/transfer0",
                progress=progress,
                source=Path("photo.jpg"),
            )
        self.assertEqual(result["Status"], "complete")
        self.assertEqual(seen, [(0, 4), (2, 4), (4, 4)])

    def test_error_status_raises(self):
        with mock.patch.object(
            obex,
            "_get_transfer_properties",
            return_value={"Status": "error"},
        ):
            with self.assertRaises(ObexError):
                obex.wait_transfer(FakeConn(), "/transfer0", timeout=5)

    def test_timeout_raises(self):
        with mock.patch.object(
            obex,
            "_get_transfer_properties",
            return_value={"Status": "active", "Transferred": 1, "Size": 10},
        ), mock.patch.object(obex.time, "sleep"):
            with self.assertRaises(ObexError):
                obex.wait_transfer(FakeConn(), "/transfer0", timeout=0)


class SendFilesTests(unittest.TestCase):
    def test_reuses_one_session_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "a.txt"
            second = Path(temp) / "b.txt"
            first.write_text("a")
            second.write_text("bb")
            with mock.patch.object(
                obex, "connect_session_bus", return_value=FakeConn()
            ), mock.patch.object(
                obex, "create_session", return_value="/session0"
            ) as create, mock.patch.object(
                obex,
                "send_file",
                side_effect=["/transfer0", "/transfer1"],
            ) as send, mock.patch.object(
                obex,
                "wait_transfer",
                return_value={
                    "Status": "complete",
                    "Transferred": 1,
                    "Size": 1,
                },
            ) as wait, mock.patch.object(
                obex, "remove_session"
            ) as remove:
                results = obex.send_files("41:42:03:AC:1D:1B", [first, second])

        create.assert_called_once()
        self.assertEqual(send.call_count, 2)
        self.assertEqual(wait.call_count, 2)
        remove.assert_called_once_with(mock.ANY, "/session0")
        self.assertEqual([result.filename.name for result in results], ["a.txt", "b.txt"])

    def test_missing_file_fails_before_opening_a_session(self):
        with mock.patch.object(obex, "connect_session_bus") as connect:
            with self.assertRaises(BconnError):
                obex.send_files("41:42:03:AC:1D:1B", ["/nope/missing.bin"])
        connect.assert_not_called()

    def test_empty_file_list_is_rejected(self):
        with self.assertRaises(BconnError):
            obex.send_files("41:42:03:AC:1D:1B", [])


class ObexdAvailableTests(unittest.TestCase):
    def test_detects_owner(self):
        conn = FakeConn(GLib.Variant("(b)", (True,)))
        self.assertTrue(obex.obexd_available(conn))

    def test_returns_false_without_owner(self):
        conn = FakeConn(GLib.Variant("(b)", (False,)))
        self.assertFalse(obex.obexd_available(conn))


if __name__ == "__main__":
    unittest.main()
