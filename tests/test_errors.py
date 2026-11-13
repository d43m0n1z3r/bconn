import unittest

from bconn.errors import (
    BluezError,
    ObexError,
    SystemNotReady,
    extract_remote_error,
    translate_glib,
    translate_obex_glib,
)


class FakeGlibError:
    def __init__(self, message: str):
        self.message = message

    def __str__(self):
        return self.message


class ErrorTests(unittest.TestCase):
    def test_extract_remote_error(self):
        message = (
            "GDBus.Error:org.bluez.Error.AuthenticationFailed: "
            "Authentication failed"
        )
        self.assertEqual(
            extract_remote_error(message),
            "org.bluez.Error.AuthenticationFailed",
        )

    def test_extract_remote_error_missing(self):
        self.assertEqual(extract_remote_error("something broke"), "")

    def test_friendly_authentication_error(self):
        error = BluezError.from_glib(
            FakeGlibError(
                "GDBus.Error:org.bluez.Error.AuthenticationFailed: nope"
            )
        )
        self.assertIn("rejected authentication", error.title)
        self.assertIn("phone", error.hint or "")

    def test_service_missing_becomes_system_not_ready(self):
        error = translate_glib(
            FakeGlibError(
                "GDBus.Error:org.freedesktop.systemd1.NoSuchUnit: "
                "Unit dbus-org.bluez.service not found."
            )
        )
        self.assertIsInstance(error, SystemNotReady)
        self.assertEqual(error.exit_code, 3)
        self.assertIn("systemctl enable", error.hint or "")

    def test_unknown_error_keeps_name(self):
        error = translate_glib(
            FakeGlibError("GDBus.Error:org.example.Error.Weird: nope")
        )
        self.assertIsInstance(error, BluezError)
        self.assertEqual(error.name, "org.example.Error.Weird")

    def test_obex_missing_becomes_system_not_ready(self):
        error = translate_obex_glib(
            FakeGlibError(
                "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: "
                "The name org.bluez.obex was not provided by any .service files"
            )
        )
        self.assertIsInstance(error, SystemNotReady)
        self.assertIn("obex", error.title.lower())
        self.assertIn("systemctl --user start obex.service", error.hint or "")

    def test_obex_friendly_error(self):
        error = translate_obex_glib(
            FakeGlibError(
                "GDBus.Error:org.bluez.obex.Error.NotSupported: nope"
            )
        )
        self.assertIsInstance(error, ObexError)
        self.assertIn("does not support", error.title)

    def test_obex_unknown_error_falls_back(self):
        error = translate_obex_glib(
            FakeGlibError("GDBus.Error:org.example.Error.Weird: nope")
        )
        self.assertIsInstance(error, ObexError)
        self.assertEqual(error.name, "org.example.Error.Weird")


if __name__ == "__main__":
    unittest.main()
