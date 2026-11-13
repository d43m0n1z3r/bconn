#!/usr/bin/env python3
"""A tiny fake BlueZ service for testing BConn without hardware or root.

Run it on a private D-Bus daemon and point DBUS_SYSTEM_BUS_ADDRESS at that
daemon. It implements just enough of org.bluez for list/scan/pair/connect.
"""

from __future__ import annotations

import signal
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

ADAPTER_PATH = "/org/bluez/hci0"
DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
DEVICE_ADDRESS = "AA:BB:CC:DD:EE:FF"
AGENT_MANAGER_PATH = "/org/bluez"

OM_XML = """
<node>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects">
      <arg type="a{oa{sa{sv}}}" direction="out"/>
    </method>
  </interface>
</node>
"""

ADAPTER_XML = """
<node>
  <interface name="org.bluez.Adapter1">
    <method name="StartDiscovery"/>
    <method name="StopDiscovery"/>
    <method name="SetDiscoveryFilter">
      <arg type="a{sv}" direction="in"/>
    </method>
    <method name="RemoveDevice">
      <arg type="o" direction="in"/>
    </method>
    <property name="Address" type="s" access="read"/>
    <property name="Name" type="s" access="read"/>
    <property name="Alias" type="s" access="readwrite"/>
    <property name="Powered" type="b" access="readwrite"/>
    <property name="Discovering" type="b" access="read"/>
    <property name="Pairable" type="b" access="readwrite"/>
    <property name="Discoverable" type="b" access="readwrite"/>
    <property name="UUIDs" type="as" access="read"/>
  </interface>
</node>
"""

DEVICE_XML = """
<node>
  <interface name="org.bluez.Device1">
    <method name="Pair"/>
    <method name="CancelPairing"/>
    <method name="Connect"/>
    <method name="Disconnect"/>
    <property name="Address" type="s" access="read"/>
    <property name="AddressType" type="s" access="read"/>
    <property name="Name" type="s" access="read"/>
    <property name="Alias" type="s" access="readwrite"/>
    <property name="Icon" type="s" access="read"/>
    <property name="Adapter" type="o" access="read"/>
    <property name="Paired" type="b" access="read"/>
    <property name="Bonded" type="b" access="read"/>
    <property name="Trusted" type="b" access="readwrite"/>
    <property name="Blocked" type="b" access="readwrite"/>
    <property name="Connected" type="b" access="read"/>
    <property name="ServicesResolved" type="b" access="read"/>
    <property name="RSSI" type="n" access="read"/>
    <property name="UUIDs" type="as" access="read"/>
  </interface>
</node>
"""

AGENT_MANAGER_XML = """
<node>
  <interface name="org.bluez.AgentManager1">
    <method name="RegisterAgent">
      <arg type="o" direction="in"/>
      <arg type="s" direction="in"/>
    </method>
    <method name="UnregisterAgent">
      <arg type="o" direction="in"/>
    </method>
    <method name="RequestDefaultAgent">
      <arg type="o" direction="in"/>
    </method>
  </interface>
</node>
"""


def v(value):
    """Wrap a Python value in a GLib.Variant for the a{sv} maps."""
    if isinstance(value, bool):
        return GLib.Variant("b", value)
    if isinstance(value, int):
        return GLib.Variant("i", value)
    if isinstance(value, (list, tuple)):
        return GLib.Variant("as", list(value))
    return GLib.Variant("s", str(value))


class FakeBluez:
    def __init__(self, connection: Gio.DBusConnection):
        self.conn = connection
        self.agent_owner: str | None = None
        self.agent_path: str | None = None
        self.discovering = False
        self.gone = False

        self.props: dict[str, dict[str, dict[str, GLib.Variant]]] = {
            ADAPTER_PATH: {
                "org.bluez.Adapter1": {
                    "Address": v("AA:BB:CC:11:22:33"),
                    "Name": v("Kali laptop"),
                    "Alias": v("Kali"),
                    "Powered": v(True),
                    "Discovering": v(False),
                    "Pairable": v(False),
                    "Discoverable": v(False),
                    "UUIDs": v(["0000110b-0000-1000-8000-00805f9b34fb"]),
                }
            },
            DEVICE_PATH: {
                "org.bluez.Device1": {
                    "Address": v(DEVICE_ADDRESS),
                    "AddressType": v("public"),
                    "Name": v("WH-1000XM4"),
                    "Alias": v("Buds"),
                    "Icon": v("audio-headphones"),
                    "Adapter": GLib.Variant("o", ADAPTER_PATH),
                    "Paired": v(False),
                    "Bonded": v(False),
                    "Trusted": v(False),
                    "Blocked": v(False),
                    "Connected": v(False),
                    "ServicesResolved": v(False),
                    "RSSI": GLib.Variant("n", -52),
                    "UUIDs": v(["0000110b-0000-1000-8000-00805f9b34fb"]),
                }
            },
        }

        self._register_interfaces()

    def _register_interfaces(self) -> None:
        specs = [
            ("/", OM_XML),
            (ADAPTER_PATH, ADAPTER_XML),
            (DEVICE_PATH, DEVICE_XML),
            (AGENT_MANAGER_PATH, AGENT_MANAGER_XML),
        ]
        for path, xml in specs:
            node = Gio.DBusNodeInfo.new_for_xml(xml)
            for interface in node.interfaces:
                self.conn.register_object(
                    path,
                    interface,
                    self._on_method,
                    self._on_get_property,
                    self._on_set_property,
                )

    def _device_props(self) -> dict[str, GLib.Variant]:
        return self.props[DEVICE_PATH]["org.bluez.Device1"]

    def _adapter_props(self) -> dict[str, GLib.Variant]:
        return self.props[ADAPTER_PATH]["org.bluez.Adapter1"]

    def _set(self, path: str, interface: str, prop: str, value) -> None:
        self.props[path][interface][prop] = value

    def _get(self, path: str, interface: str, prop: str):
        return self.props.get(path, {}).get(interface, {}).get(prop)

    def _managed_objects(self) -> dict:
        result = {}
        for path, interfaces in self.props.items():
            if path == DEVICE_PATH and self.gone:
                continue
            result[path] = {
                name: props for name, props in interfaces.items()
            }
        return result

    def _on_get_property(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        path: str,
        interface: str,
        prop: str,
    ):
        return self._get(path, interface, prop)

    def _on_set_property(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        path: str,
        interface: str,
        prop: str,
        value: GLib.Variant,
    ) -> bool:
        self._set(path, interface, prop, value)
        if path == ADAPTER_PATH and interface == "org.bluez.Adapter1" and prop == "Powered":
            if not value.unpack():
                self.discovering = False
        return True

    def _agent_call(self, method: str, params: GLib.Variant) -> None:
        if not self.agent_owner or not self.agent_path:
            return
        self.conn.call_sync(
            self.agent_owner,
            self.agent_path,
            "org.bluez.Agent1",
            method,
            params,
            None,
            Gio.DBusCallFlags.NONE,
            15_000,
            None,
        )

    def _on_method(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        path: str,
        interface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        try:
            args = params.unpack()
        except Exception:
            args = ()

        try:
            if interface == "org.freedesktop.DBus.ObjectManager":
                if method == "GetManagedObjects":
                    invocation.return_value(
                        GLib.Variant("(a{oa{sa{sv}}})", (self._managed_objects(),))
                    )
                else:
                    invocation.return_dbus_error(
                        "org.freedesktop.DBus.Error.UnknownMethod", method
                    )

            elif interface == "org.bluez.Adapter1":
                if method == "StartDiscovery":
                    self.discovering = True
                    self._set(
                        ADAPTER_PATH,
                        "org.bluez.Adapter1",
                        "Discovering",
                        v(True),
                    )
                    invocation.return_value(None)
                elif method == "StopDiscovery":
                    self.discovering = False
                    self._set(
                        ADAPTER_PATH,
                        "org.bluez.Adapter1",
                        "Discovering",
                        v(False),
                    )
                    invocation.return_value(None)
                elif method == "SetDiscoveryFilter":
                    invocation.return_value(None)
                elif method == "RemoveDevice":
                    self.gone = True
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error(
                        "org.bluez.Error.NotSupported", method
                    )

            elif interface == "org.bluez.Device1":
                if method == "Pair":
                    if not self._device_props()["Paired"].unpack():
                        self._agent_call(
                            "RequestConfirmation",
                            GLib.Variant("(ou)", (DEVICE_PATH, 123456)),
                        )
                        self._set(DEVICE_PATH, "org.bluez.Device1", "Paired", v(True))
                        self._set(DEVICE_PATH, "org.bluez.Device1", "Bonded", v(True))
                    invocation.return_value(None)
                elif method == "CancelPairing":
                    invocation.return_value(None)
                elif method == "Connect":
                    self._set(
                        DEVICE_PATH, "org.bluez.Device1", "Connected", v(True)
                    )
                    self._set(
                        DEVICE_PATH,
                        "org.bluez.Device1",
                        "ServicesResolved",
                        v(True),
                    )
                    invocation.return_value(None)
                elif method == "Disconnect":
                    self._set(
                        DEVICE_PATH, "org.bluez.Device1", "Connected", v(False)
                    )
                    self._set(
                        DEVICE_PATH,
                        "org.bluez.Device1",
                        "ServicesResolved",
                        v(False),
                    )
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error(
                        "org.bluez.Error.NotSupported", method
                    )

            elif interface == "org.bluez.AgentManager1":
                if method == "RegisterAgent":
                    self.agent_owner = sender
                    self.agent_path = args[0]
                    invocation.return_value(None)
                elif method == "UnregisterAgent":
                    if self.agent_path == args[0]:
                        self.agent_owner = None
                        self.agent_path = None
                    invocation.return_value(None)
                elif method == "RequestDefaultAgent":
                    invocation.return_value(None)
                else:
                    invocation.return_dbus_error(
                        "org.bluez.Error.NotSupported", method
                    )
            else:
                invocation.return_dbus_error(
                    "org.freedesktop.DBus.Error.UnknownMethod", method
                )
        except Exception as error:  # pragma: no cover - test helper
            print(f"fake error in {interface}.{method}: {error!r}", file=sys.stderr, flush=True)
            invocation.return_dbus_error(
                "org.bluez.Error.Failed", f"fake BlueZ error: {error}"
            )


def main() -> int:
    connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    reply = connection.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "RequestName",
        GLib.Variant("(su)", ("org.bluez", 0)),
        GLib.VariantType.new("(u)"),
        Gio.DBusCallFlags.NONE,
        5_000,
        None,
    )
    if reply is not None and reply.unpack()[0] not in (1, 4):
        print("could not own org.bluez", file=sys.stderr)
        return 1
    FakeBluez(connection)
    print("fake-bluez ready", file=sys.stderr, flush=True)
    loop = GLib.MainLoop()

    def stop(*_args):
        loop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
