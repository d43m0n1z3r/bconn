"""Thin, typed BlueZ client over the system D-Bus (Gio/GDBus)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .errors import (  # noqa: E402
    AmbiguousDevice,
    BconnError,
    BluezError,
    DeviceNotFound,
    SystemNotReady,
    translate_glib,
)

BLUEZ = "org.bluez"
OM_PATH = "/"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
BATTERY_IFACE = "org.bluez.Battery1"
AGENT_MANAGER_PATH = "/org/bluez"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"

MANAGED_OBJECTS_TYPE = GLib.VariantType.new("(a{oa{sa{sv}}})")

_AUDIO_ICONS = ("audio-card", "audio-headphones", "audio-headset", "audio-speakers")
_INPUT_ICONS = ("input-keyboard", "input-mouse", "input-gaming", "input-tablet")
_AUDIO_UUIDS = ("110A", "110B", "1108", "110E", "111E", "111F", "112D", "112E")
_INPUT_UUIDS = ("1124", "1812")


@dataclass
class Adapter:
    path: str
    address: str
    name: str = ""
    alias: str = ""
    powered: bool = False
    discovering: bool = False
    pairable: bool = False
    discoverable: bool = False
    uuids: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return self.alias or self.name or self.address


@dataclass
class Device:
    path: str
    address: str
    adapter_path: str = ""
    address_type: str = "public"
    name: str = ""
    alias: str = ""
    icon: str = ""
    paired: bool = False
    bonded: bool = False
    trusted: bool = False
    blocked: bool = False
    connected: bool = False
    services_resolved: bool = False
    rssi: int | None = None
    uuids: tuple[str, ...] = ()
    battery: int | None = None

    @property
    def display_name(self) -> str:
        return self.alias or self.name or self.address

    @property
    def is_audio(self) -> bool:
        icon = (self.icon or "").lower()
        if icon.startswith(_AUDIO_ICONS):
            return True
        prefixes = tuple(f"0000{uuid.lower()}" for uuid in _AUDIO_UUIDS)
        return any(u.lower().startswith(prefixes) for u in self.uuids)

    @property
    def is_input(self) -> bool:
        icon = (self.icon or "").lower()
        if icon.startswith(_INPUT_ICONS):
            return True
        prefixes = tuple(f"0000{uuid.lower()}" for uuid in _INPUT_UUIDS)
        return any(u.lower().startswith(prefixes) for u in self.uuids)

    @property
    def kind(self) -> str:
        if self.is_audio:
            return "audio"
        if self.is_input:
            return "input"
        icon = (self.icon or "").lower()
        if icon.startswith("phone"):
            return "phone"
        if icon.startswith(("computer", "laptop")):
            return "computer"
        return "other"

    @property
    def state(self) -> str:
        if self.blocked:
            return "blocked"
        if self.connected:
            return "connected"
        if self.paired:
            return "paired"
        return "known"


def connect_system_bus() -> Gio.DBusConnection:
    try:
        return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error as error:
        raise translate_glib(error, "connect to system bus") from None


def _call(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    method: str,
    params: GLib.Variant | None = None,
    reply_type: GLib.VariantType | None = None,
    timeout_ms: int = 10_000,
) -> GLib.Variant | None:
    try:
        return conn.call_sync(
            BLUEZ,
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
        raise translate_glib(error, f"{interface}.{method}") from None


def call_method(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    method: str,
    params: GLib.Variant | None = None,
    timeout_ms: int = 10_000,
) -> None:
    _call(conn, path, interface, method, params, None, timeout_ms)


def call_method_async(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    method: str,
    params: GLib.Variant | None = None,
    timeout_ms: int = 30_000,
) -> None:
    """Call a method and pump a private main loop until it finishes.

    This keeps pairing-agent callbacks dispatchable while a method such as
    Pair() or Connect() is pending. It is intended for the CLI; the future GUI
    will use Gio's normal async API on its existing main loop.
    """
    loop = GLib.MainLoop()
    result: dict[str, Any] = {}

    def done(source: Gio.DBusConnection, res: Gio.AsyncResult) -> None:
        try:
            result["value"] = source.call_finish(res)
        except GLib.Error as error:
            result["error"] = error
        loop.quit()

    try:
        conn.call(
            BLUEZ,
            path,
            interface,
            method,
            params,
            None,
            Gio.DBusCallFlags.NONE,
            timeout_ms,
            None,
            done,
        )
    except GLib.Error as error:
        raise translate_glib(error, f"{interface}.{method}") from None

    loop.run()
    if "error" in result:
        raise translate_glib(result["error"], f"{interface}.{method}") from None


def get_managed_objects(conn: Gio.DBusConnection) -> dict[str, Any]:
    reply = _call(
        conn,
        OM_PATH,
        OM_IFACE,
        "GetManagedObjects",
        None,
        MANAGED_OBJECTS_TYPE,
        10_000,
    )
    assert reply is not None
    return reply.unpack()[0]


def parse_objects(objects: dict[str, Any]) -> tuple[list[Adapter], list[Device]]:
    adapters: list[Adapter] = []
    devices: list[Device] = []

    for path, interfaces in objects.items():
        if ADAPTER_IFACE in interfaces:
            props = interfaces[ADAPTER_IFACE]
            adapters.append(
                Adapter(
                    path=path,
                    address=str(props.get("Address", "")),
                    name=str(props.get("Name", "") or ""),
                    alias=str(props.get("Alias", "") or ""),
                    powered=bool(props.get("Powered", False)),
                    discovering=bool(props.get("Discovering", False)),
                    pairable=bool(props.get("Pairable", False)),
                    discoverable=bool(props.get("Discoverable", False)),
                    uuids=tuple(props.get("UUIDs", ()) or ()),
                )
            )

        if DEVICE_IFACE in interfaces:
            props = interfaces[DEVICE_IFACE]
            battery_props = interfaces.get(BATTERY_IFACE, {})
            battery = battery_props.get("Percentage") if battery_props else None
            devices.append(
                Device(
                    path=path,
                    address=str(props.get("Address", "")),
                    adapter_path=str(props.get("Adapter", "") or ""),
                    address_type=str(props.get("AddressType", "public") or "public"),
                    name=str(props.get("Name", "") or ""),
                    alias=str(props.get("Alias", "") or ""),
                    icon=str(props.get("Icon", "") or ""),
                    paired=bool(props.get("Paired", False)),
                    bonded=bool(props.get("Bonded", False)),
                    trusted=bool(props.get("Trusted", False)),
                    blocked=bool(props.get("Blocked", False)),
                    connected=bool(props.get("Connected", False)),
                    services_resolved=bool(props.get("ServicesResolved", False)),
                    rssi=props.get("RSSI"),
                    uuids=tuple(props.get("UUIDs", ()) or ()),
                    battery=int(battery) if isinstance(battery, int) else None,
                )
            )

    return adapters, devices


def get_objects(conn: Gio.DBusConnection) -> tuple[list[Adapter], list[Device]]:
    return parse_objects(get_managed_objects(conn))


def get_all_properties(
    conn: Gio.DBusConnection, path: str, interface: str
) -> dict[str, Any]:
    reply = _call(
        conn,
        path,
        PROPS_IFACE,
        "GetAll",
        GLib.Variant("(s)", (interface,)),
        GLib.VariantType.new("(a{sv})"),
        10_000,
    )
    assert reply is not None
    return reply.unpack()[0]


def get_property(
    conn: Gio.DBusConnection, path: str, interface: str, name: str
) -> Any:
    reply = _call(
        conn,
        path,
        PROPS_IFACE,
        "Get",
        GLib.Variant("(ss)", (interface, name)),
        GLib.VariantType.new("(v)"),
        10_000,
    )
    assert reply is not None
    return reply.unpack()[0]


def set_property(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    name: str,
    value: GLib.Variant,
    timeout_ms: int = 10_000,
) -> None:
    call_method(
        conn,
        path,
        PROPS_IFACE,
        "Set",
        GLib.Variant("(ssv)", (interface, name, value)),
        timeout_ms,
    )


def wait_property(
    conn: Gio.DBusConnection,
    path: str,
    interface: str,
    name: str,
    expected: Any,
    timeout: float,
    interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if get_property(conn, path, interface, name) == expected:
                return True
        except SystemNotReady:
            raise
        except BconnError:
            return False
        time.sleep(interval)
    return False


def select_adapter(
    adapters: Iterable[Adapter], preferred: str | None = None
) -> Adapter:
    adapter_list = list(adapters)
    if not adapter_list:
        raise SystemNotReady(
            "No Bluetooth adapter was found.",
            "If this is a virtual machine, pass a USB Bluetooth adapter through "
            "to the guest. Otherwise check 'dmesg | grep -i blue'.",
        )

    if preferred:
        wanted = preferred.strip().lower()
        for adapter in adapter_list:
            if wanted in {
                adapter.path.lower(),
                adapter.address.lower(),
                adapter.display_name.lower(),
            }:
                return adapter

    for adapter in adapter_list:
        if adapter.powered:
            return adapter
    return adapter_list[0]


def start_discovery(conn: Gio.DBusConnection, adapter: Adapter) -> None:
    try:
        call_method(
            conn,
            adapter.path,
            ADAPTER_IFACE,
            "SetDiscoveryFilter",
            GLib.Variant(
                "(a{sv})",
                (
                    {
                        "Transport": GLib.Variant("s", "auto"),
                        "DuplicateData": GLib.Variant("b", False),
                    },
                ),
            ),
        )
    except BluezError as error:
        # Older kernels/BlueZ versions may not accept every filter option.
        if error.name != "org.bluez.Error.InvalidArguments":
            raise

    try:
        call_method(conn, adapter.path, ADAPTER_IFACE, "StartDiscovery")
    except BluezError as error:
        if error.name != "org.bluez.Error.InProgress":
            raise


def stop_discovery(conn: Gio.DBusConnection, adapter: Adapter) -> None:
    try:
        call_method(conn, adapter.path, ADAPTER_IFACE, "StopDiscovery", timeout_ms=5_000)
    except (BluezError, SystemNotReady):
        pass


def scan_devices(
    conn: Gio.DBusConnection,
    adapter: Adapter,
    timeout: float,
    on_update: Callable[[list[Device]], None] | None = None,
    poll_interval: float = 0.5,
) -> list[Device]:
    start_discovery(conn, adapter)
    deadline = time.monotonic() + timeout
    latest: list[Device] = []
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _, devices = get_objects(conn)
            latest = [d for d in devices if d.adapter_path == adapter.path]
            if on_update is not None:
                on_update(latest)
            time.sleep(min(poll_interval, remaining))
    finally:
        stop_discovery(conn, adapter)
    return latest


def set_adapter_powered(
    conn: Gio.DBusConnection, adapter: Adapter, powered: bool
) -> None:
    if not powered:
        stop_discovery(conn, adapter)
    set_property(conn, adapter.path, ADAPTER_IFACE, "Powered", GLib.Variant("b", powered))


def looks_like_mac(value: str) -> bool:
    value = value.strip()
    return bool(
        re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", value)
        or re.fullmatch(r"[0-9A-Fa-f]{12}", value)
    )


def _mac_key(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", value.lower())


def find_device(devices: Iterable[Device], query: str) -> Device:
    query = query.strip()
    if not query:
        raise DeviceNotFound(query)

    device_list = list(devices)

    if looks_like_mac(query):
        key = _mac_key(query)
        for device in device_list:
            if _mac_key(device.address) == key:
                return device

    needle = query.lower()
    matches = [
        device
        for device in device_list
        if needle in device.display_name.lower()
        or needle in device.name.lower()
        or needle in device.address.lower()
    ]

    if not matches:
        raise DeviceNotFound(query)
    if len(matches) > 1:
        # Prefer a unique exact name/alias match over many substring matches.
        exact = [
            device
            for device in matches
            if needle in {device.name.lower(), device.alias.lower()}
        ]
        if len(exact) == 1:
            return exact[0]
        raise AmbiguousDevice(query, matches)
    return matches[0]
