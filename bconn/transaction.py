"""Pair → trust → connect transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import bluez  # noqa: E402
from .agent import PairingAgent, Prompter  # noqa: E402
from .errors import BconnError, BluezError, BluezTimeout  # noqa: E402


@dataclass
class ConnectResult:
    device: bluez.Device
    paired_now: bool = False
    trusted_now: bool = False
    services_resolved: bool = True
    warnings: list[str] = field(default_factory=list)


def refresh_device(conn: Gio.DBusConnection, path: str) -> bluez.Device | None:
    _, devices = bluez.get_objects(conn)
    return next((device for device in devices if device.path == path), None)


def _name_lookup_for(device: bluez.Device) -> Callable[[str], str | None]:
    return lambda path: device.display_name if path == device.path else None


def ensure_trusted(conn: Gio.DBusConnection, device: bluez.Device) -> bool:
    if device.trusted:
        return False
    bluez.set_property(
        conn, device.path, bluez.DEVICE_IFACE, "Trusted", GLib.Variant("b", True)
    )
    device.trusted = True
    return True


def _pair_with_agent(
    conn: Gio.DBusConnection, device: bluez.Device
) -> None:
    """Run Pair() and verify the Paired property. An agent must be active."""
    try:
        bluez.call_method_async(
            conn,
            device.path,
            bluez.DEVICE_IFACE,
            "Pair",
            None,
            35_000,
        )
    except BluezError as error:
        if error.name != "org.bluez.Error.AlreadyExists":
            raise

    if not bluez.wait_property(
        conn, device.path, bluez.DEVICE_IFACE, "Paired", True, timeout=10
    ):
        raise BluezError(
            "org.bluez.Error.Failed",
            "Pairing returned without the device becoming paired.",
            "Pair",
        )
    device.paired = True


def pair_device(
    conn: Gio.DBusConnection,
    adapter: bluez.Adapter,
    device: bluez.Device,
    prompter: Prompter | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> tuple[bool, list[str]]:
    """Pair and trust a device. Returns (paired_now, warnings)."""
    warnings: list[str] = []

    if device.paired:
        ensure_trusted(conn, device)
        return False, warnings

    bluez.stop_discovery(conn, adapter)

    with PairingAgent(conn, prompter, _name_lookup_for(device)) as agent:
        _pair_with_agent(conn, device)
        ensure_trusted(conn, device)
        warnings = list(agent.warnings)

    if on_warning:
        for warning in warnings:
            on_warning(warning)

    return True, warnings


def connect_device(
    conn: Gio.DBusConnection,
    adapter: bluez.Adapter,
    device: bluez.Device,
    prompter: Prompter | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> ConnectResult:
    """Pair if needed, trust, connect, and wait for services to resolve."""
    warnings: list[str] = []
    paired_now = False

    bluez.stop_discovery(conn, adapter)

    if device.connected:
        resolved = bluez.get_property(
            conn, device.path, bluez.DEVICE_IFACE, "ServicesResolved"
        )
        if not resolved:
            resolved = bluez.wait_property(
                conn,
                device.path,
                bluez.DEVICE_IFACE,
                "ServicesResolved",
                True,
                timeout=8,
            )
        if not resolved:
            warnings.append(
                "The device is connected, but its services did not finish "
                "resolving. Audio may not be routed yet."
            )
        refreshed = refresh_device(conn, device.path) or device
        return ConnectResult(
            device=refreshed,
            paired_now=False,
            trusted_now=False,
            services_resolved=bool(resolved),
            warnings=warnings,
        )

    with PairingAgent(conn, prompter, _name_lookup_for(device)) as agent:
        if not device.paired:
            _pair_with_agent(conn, device)
            paired_now = True

        trusted_now = ensure_trusted(conn, device)

        try:
            bluez.call_method_async(
                conn,
                device.path,
                bluez.DEVICE_IFACE,
                "Connect",
                None,
                35_000,
            )
        except BluezError as error:
            if error.name != "org.bluez.Error.AlreadyConnected":
                raise

        if not bluez.wait_property(
            conn, device.path, bluez.DEVICE_IFACE, "Connected", True, timeout=12
        ):
            raise BluezTimeout("Connection", 12)

        services_resolved = bluez.wait_property(
            conn,
            device.path,
            bluez.DEVICE_IFACE,
            "ServicesResolved",
            True,
            timeout=12,
        )
        if not services_resolved:
            warnings.append(
                "The device connected, but its services did not finish "
                "resolving. Audio may not be routed yet."
            )

        if paired_now:
            warnings.extend(agent.warnings)

    for warning in warnings:
        if on_warning:
            on_warning(warning)

    refreshed = refresh_device(conn, device.path) or device
    refreshed.connected = True
    refreshed.paired = True
    refreshed.trusted = True
    refreshed.services_resolved = services_resolved

    return ConnectResult(
        device=refreshed,
        paired_now=paired_now,
        trusted_now=trusted_now,
        services_resolved=services_resolved,
        warnings=warnings,
    )


def disconnect_device(conn: Gio.DBusConnection, device: bluez.Device) -> None:
    if not device.connected:
        return
    try:
        bluez.call_method_async(
            conn,
            device.path,
            bluez.DEVICE_IFACE,
            "Disconnect",
            None,
            15_000,
        )
    except BluezError as error:
        if error.name != "org.bluez.Error.NotConnected":
            raise
        return

    bluez.wait_property(
        conn, device.path, bluez.DEVICE_IFACE, "Connected", False, timeout=8
    )


def forget_device(
    conn: Gio.DBusConnection, adapter: bluez.Adapter, device: bluez.Device
) -> None:
    try:
        bluez.call_method(
            conn,
            adapter.path,
            bluez.ADAPTER_IFACE,
            "RemoveDevice",
            GLib.Variant("(o)", (device.path,)),
            10_000,
        )
    except BluezError as error:
        if error.name not in {
            "org.bluez.Error.DoesNotExist",
            "org.bluez.Error.NotExists",
        }:
            raise


def ensure_adapter_powered(
    conn: Gio.DBusConnection, adapter: bluez.Adapter
) -> None:
    if adapter.powered:
        return
    bluez.set_adapter_powered(conn, adapter, True)
    if not bluez.wait_property(
        conn, adapter.path, bluez.ADAPTER_IFACE, "Powered", True, timeout=8
    ):
        raise BconnError(
            "The Bluetooth adapter did not power on.",
            "Check 'rfkill list bluetooth' and 'bconn doctor'.",
        )
    adapter.powered = True
