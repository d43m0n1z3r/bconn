"""OBEX Object Push client over the session D-Bus (org.bluez.obex).

``obexd`` runs per user on the *session* bus and exposes Object Push, File
Transfer and phonebook profiles. BConn uses it to send files to phones and
other devices that accept OBEX pushes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .errors import (  # noqa: E402
    BconnError,
    ObexError,
    SystemNotReady,
    translate_obex_glib,
)

OBEX = "org.bluez.obex"
OBEX_PATH = "/org/bluez/obex"
CLIENT_IFACE = "org.bluez.obex.Client1"
OPP_IFACE = "org.bluez.obex.ObjectPush1"
TRANSFER_IFACE = "org.bluez.obex.Transfer1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

TARGET_OPP = "opp"
TARGET_FTP = "ftp"

# Transfer1.Status values.
STATUS_QUEUED = "queued"
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"

ProgressCallback = Callable[[Path, int, int], None]


@dataclass
class Transfer:
    path: str
    filename: Path
    remote_name: str
    transferred: int = 0
    size: int = 0
    status: str = STATUS_QUEUED


def connect_session_bus() -> Gio.DBusConnection:
    """Return the user's session bus, where obexd lives."""
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        raise translate_obex_glib(error, "connect to session bus") from None


def _call(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    method: str,
    params: GLib.Variant | None = None,
    reply_type: GLib.VariantType | None = None,
    timeout_ms: int = 30_000,
) -> GLib.Variant | None:
    try:
        return conn.call_sync(
            OBEX,
            path,
            interface,
            method,
            params,
            reply_type,
            Gio.DBusCallFlags.NONE,
            timeout_ms,
            None,
        )
    except GLib.Error as error:
        raise translate_obex_glib(error, f"{interface}.{method}") from None


def create_session(
    conn: Gio.DBusConnection,
    address: str,
    target: str = TARGET_OPP,
    timeout_ms: int = 60_000,
) -> str:
    """Create an OBEX session and return its object path."""
    reply = _call(
        conn,
        OBEX_PATH,
        CLIENT_IFACE,
        "CreateSession",
        GLib.Variant("(sa{sv})", (address, {"Target": GLib.Variant("s", target)})),
        GLib.VariantType.new("(o)"),
        timeout_ms,
    )
    if reply is None:
        raise ObexError(
            "org.bluez.obex.Error.Failed",
            "CreateSession returned no session path.",
            "CreateSession",
        )
    return str(reply.unpack()[0])


def remove_session(conn: Gio.DBusConnection, session_path: str) -> None:
    try:
        _call(
            conn,
            OBEX_PATH,
            CLIENT_IFACE,
            "RemoveSession",
            GLib.Variant("(o)", (session_path,)),
        )
    except BconnError:
        # The session may already be gone; that is not worth surfacing.
        pass


def _get_transfer_properties(conn: Gio.DBusConnection, transfer_path: str) -> dict:
    reply = _call(
        conn,
        transfer_path,
        PROPS_IFACE,
        "GetAll",
        GLib.Variant("(s)", (TRANSFER_IFACE,)),
        GLib.VariantType.new("(a{sv})"),
    )
    if reply is None:
        return {}
    return dict(reply.unpack()[0])


def send_file(
    conn: Gio.DBusConnection,
    session_path: str,
    source: Path,
    remote_name: str | None = None,
) -> str:
    """Queue one file for transfer and return the Transfer1 object path."""
    source = Path(source).expanduser()
    if not source.is_file():
        raise BconnError(f"Not a file: {source}", "Choose an existing file to send.")
    name = remote_name or source.name
    reply = _call(
        conn,
        session_path,
        OPP_IFACE,
        "SendFile",
        GLib.Variant("(ss)", (str(source.resolve()), name)),
        GLib.VariantType.new("(oa{sv})"),
    )
    if reply is None:
        raise ObexError(
            "org.bluez.obex.Error.Failed",
            "SendFile returned no transfer object.",
            "SendFile",
        )
    return str(reply.unpack()[0])


def wait_transfer(
    conn: Gio.DBusConnection,
    transfer_path: str,
    timeout: float = 120.0,
    progress: ProgressCallback | None = None,
    source: Path | None = None,
    poll_interval: float = 0.2,
) -> dict:
    """Poll a Transfer1 object until it completes, fails, or times out."""
    deadline = time.monotonic() + timeout
    last_reported = -1
    while True:
        props = _get_transfer_properties(conn, transfer_path)
        status = str(props.get("Status", STATUS_QUEUED))
        transferred = int(props.get("Transferred", 0) or 0)
        size = int(props.get("Size", 0) or 0)

        if progress is not None and source is not None and transferred != last_reported:
            progress(source, transferred, size)
            last_reported = transferred

        if status == STATUS_COMPLETE:
            return props
        if status == STATUS_ERROR:
            raise ObexError(
                "org.bluez.obex.Error.Failed",
                f"The device reported a transfer error for {source or 'the file'}.",
                "Transfer1",
            )
        if time.monotonic() >= deadline:
            raise ObexError(
                "org.bluez.obex.Error.Failed",
                f"The transfer did not finish within {timeout:g}s.",
                "Transfer1",
            )
        time.sleep(poll_interval)


def send_files(
    address: str,
    paths: Iterable[str | Path],
    *,
    timeout: float = 120.0,
    progress: ProgressCallback | None = None,
    conn: Gio.DBusConnection | None = None,
) -> list[Transfer]:
    """Send files to ``address`` over OBEX Object Push.

    A session is created once and reused for every file, then removed.
    """
    files = [Path(path).expanduser() for path in paths]
    if not files:
        raise BconnError("No files to send.", "Pass at least one file path.")

    missing = [path for path in files if not path.is_file()]
    if missing:
        listed = ", ".join(str(path) for path in missing)
        raise BconnError(
            f"File not found: {listed}",
            "Check the path and try again.",
        )

    session_conn = conn or connect_session_bus()
    session_path = create_session(session_conn, address, TARGET_OPP)
    results: list[Transfer] = []
    try:
        for source in files:
            transfer_path = send_file(session_conn, session_path, source)
            transfer = Transfer(
                path=transfer_path,
                filename=source,
                remote_name=source.name,
                size=source.stat().st_size,
            )
            props = wait_transfer(
                session_conn,
                transfer_path,
                timeout=timeout,
                progress=progress,
                source=source,
            )
            transfer.transferred = int(props.get("Transferred", transfer.size) or 0)
            transfer.size = int(props.get("Size", transfer.size) or transfer.size)
            transfer.status = str(props.get("Status", STATUS_COMPLETE))
            results.append(transfer)
    finally:
        remove_session(session_conn, session_path)
    return results


def obexd_available(conn: Gio.DBusConnection | None = None) -> bool:
    """Best-effort check that org.bluez.obex is on the session bus."""
    try:
        bus = conn or connect_session_bus()
        return bool(
            bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "NameHasOwner",
                GLib.Variant("(s)", (OBEX,)),
                GLib.VariantType.new("(b)"),
                Gio.DBusCallFlags.NONE,
                3_000,
                None,
            ).unpack()[0]
        )
    except (GLib.Error, SystemNotReady):
        return False
