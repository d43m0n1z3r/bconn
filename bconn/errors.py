"""Error types and BlueZ/D-Bus error translation for BConn."""

from __future__ import annotations

import re
from typing import Iterable

_REMOTE_ERROR_RE = re.compile(r"(org\.[A-Za-z0-9_.]*\.Error\.[A-Za-z0-9_]+)")


class BconnError(Exception):
    """Base class for user-facing errors."""

    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self._hint = hint

    @property
    def title(self) -> str:
        return self.message

    @property
    def hint(self) -> str | None:
        return self._hint


class SystemNotReady(BconnError):
    """The Bluetooth stack cannot be used at all."""

    exit_code = 3

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(
            message,
            hint or "Run 'bconn doctor' to diagnose the Bluetooth stack.",
        )


class DeviceNotFound(BconnError):
    def __init__(self, query: str):
        super().__init__(
            f"No device matches '{query}'.",
            "Run 'bconn scan' first, or pass the device MAC address.",
        )


class AmbiguousDevice(BconnError):
    def __init__(self, query: str, matches: Iterable[object]):
        self.matches = list(matches)
        names = ", ".join(
            f"{getattr(d, 'display_name', d)} ({getattr(d, 'address', '?')})"
            for d in self.matches
        )
        super().__init__(
            f"'{query}' matches more than one device: {names}.",
            "Use a longer name or the MAC address.",
        )


class BluezTimeout(BconnError):
    def __init__(self, operation: str, seconds: float):
        super().__init__(
            f"{operation} did not finish within {seconds:g}s.",
            "The device may be out of range or asleep. Retry when it is awake.",
        )


def extract_remote_error(message: str) -> str:
    """Pull a D-Bus error name such as org.bluez.Error.Failed out of a message."""
    match = _REMOTE_ERROR_RE.search(message or "")
    return match.group(1) if match else ""


def _is_service_missing(name: str, message: str) -> bool:
    lowered = (message or "").lower()
    return (
        name
        in {
            "org.freedesktop.DBus.Error.ServiceUnknown",
            "org.freedesktop.DBus.Error.NameHasNoOwner",
            "org.freedesktop.DBus.Error.NoReply",
            "org.freedesktop.DBus.Error.Spawn.ExecFailed",
            "org.freedesktop.DBus.Error.Spawn.Failed",
            "org.freedesktop.systemd1.NoSuchUnit",
        }
        or "dbus-org.bluez.service" in lowered
        or (
            "org.bluez" in lowered
            and (
                "startservicebyname" in lowered
                or "spawn" in lowered
                or "no such file" in lowered
                or "not provided by any .service files" in lowered
            )
        )
    )


_FRIENDLY: dict[str, tuple[str, str | None]] = {
    "org.bluez.Error.NotReady": (
        "The Bluetooth adapter is not ready.",
        "Power it on with 'bconn power on'.",
    ),
    "org.bluez.Error.NotAvailable": (
        "The device is not available.",
        "It may be out of range or asleep. Bring it closer and retry.",
    ),
    "org.bluez.Error.NotConnected": (
        "The device is not connected.",
        None,
    ),
    "org.bluez.Error.NotPaired": (
        "The device is not paired.",
        "Run 'bconn pair <device>' first.",
    ),
    "org.bluez.Error.AlreadyConnected": (
        "The device is already connected.",
        None,
    ),
    "org.bluez.Error.AlreadyExists": (
        "The device is already paired.",
        None,
    ),
    "org.bluez.Error.InProgress": (
        "Another Bluetooth operation is already in progress.",
        "Wait a moment and retry.",
    ),
    "org.bluez.Error.AuthenticationFailed": (
        "The device rejected authentication.",
        "It may still be paired with a phone or another computer. Remove the "
        "pairing there, then run 'bconn pair <device>' again.",
    ),
    "org.bluez.Error.AuthenticationRejected": (
        "The device rejected the pairing request.",
        "Put the device in pairing mode and retry.",
    ),
    "org.bluez.Error.AuthenticationCanceled": (
        "Pairing was cancelled.",
        "Retry and confirm the code on the device.",
    ),
    "org.bluez.Error.AuthenticationTimeout": (
        "Pairing timed out.",
        "Put the device in pairing mode, keep it close, and retry.",
    ),
    "org.bluez.Error.Blocked": (
        "The device is blocked.",
        "Unblock it in the Bluetooth settings or with bluetoothctl.",
    ),
    "org.bluez.Error.Failed": (
        "The Bluetooth operation failed.",
        "Run 'bconn doctor' and check 'bconn info <device>' for details.",
    ),
    "org.freedesktop.DBus.Error.AccessDenied": (
        "Permission denied by D-Bus/polkit.",
        "Make sure your user is in the 'bluetooth' group and log back in.",
    ),
}


class BluezError(BconnError):
    """A failure reported by BlueZ over D-Bus."""

    def __init__(self, name: str, detail: str = "", operation: str | None = None):
        self.name = name
        self.detail = detail
        self.operation = operation
        super().__init__(detail or name or "Bluetooth operation failed.")

    @classmethod
    def from_glib(cls, error: object, operation: str | None = None) -> "BluezError":
        message = getattr(error, "message", str(error))
        return cls(extract_remote_error(message), message, operation)

    @property
    def title(self) -> str:
        friendly = _FRIENDLY.get(self.name)
        if friendly:
            return friendly[0]
        if self.name:
            return f"Bluetooth operation failed ({self.name})."
        return "Bluetooth operation failed."

    @property
    def hint(self) -> str | None:
        friendly = _FRIENDLY.get(self.name)
        if friendly:
            return friendly[1]
        return "Run 'bconn doctor' for a system check."


def translate_glib(error: object, operation: str | None = None) -> BconnError:
    """Convert a GLib.Error into the right Bconn error class."""
    parsed = BluezError.from_glib(error, operation)
    if _is_service_missing(parsed.name, parsed.detail):
        return SystemNotReady(
            "The Bluetooth service (bluetoothd) is not running.",
            "Start it once with: sudo systemctl enable --now bluetooth",
        )
    return parsed
