"""BlueZ pairing agent (org.bluez.Agent1) for the CLI."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .bluez import AGENT_MANAGER_IFACE, AGENT_MANAGER_PATH, call_method  # noqa: E402
from .errors import BconnError, BluezError  # noqa: E402

AGENT_PATH = "/org/bconn/agent"

AGENT_XML = """
<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode">
      <arg type="o" direction="in"/>
      <arg type="s" direction="out"/>
    </method>
    <method name="DisplayPinCode">
      <arg type="o" direction="in"/>
      <arg type="s" direction="in"/>
    </method>
    <method name="RequestPasskey">
      <arg type="o" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/>
      <arg type="u" direction="in"/>
      <arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation">
      <arg type="o" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="RequestAuthorization">
      <arg type="o" direction="in"/>
    </method>
    <method name="AuthorizeService">
      <arg type="o" direction="in"/>
      <arg type="s" direction="in"/>
    </method>
    <method name="Cancel"/>
  </interface>
</node>
"""


class Prompter:
    """Default prompter: deny anything that needs input.

    The CLI replaces this with an interactive implementation.
    """

    def confirm(self, device_name: str, passkey: int) -> bool:
        return False

    def request_passkey(self, device_name: str) -> int | None:
        return None

    def request_pin(self, device_name: str) -> str | None:
        return None

    def display_passkey(
        self, device_name: str, passkey: int, entered: int
    ) -> None:
        pass

    def display_pin(self, device_name: str, pin: str) -> None:
        pass

    def authorize(self, device_name: str, uuid: str) -> bool:
        return False

    def cancel(self) -> None:
        pass


class PairingAgent:
    """Register a BlueZ agent for the duration of a pairing transaction."""

    def __init__(
        self,
        conn: Gio.DBusConnection,
        prompter: Prompter | None = None,
        name_lookup: Callable[[str], str | None] | None = None,
    ):
        self.conn = conn
        self.prompter = prompter or Prompter()
        self.name_lookup = name_lookup
        self.cancelled = False
        self.warnings: list[str] = []
        self._registration_id: int | None = None
        self._active = False

    def __enter__(self) -> "PairingAgent":
        node_info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
        interface_info = node_info.interfaces[0]
        self._registration_id = self.conn.register_object(
            AGENT_PATH,
            interface_info,
            self._on_method_call,
            None,
            None,
        )
        if not self._registration_id:
            raise BconnError(
                "Could not export the pairing agent on the system bus.",
                "Check D-Bus permissions or run 'bconn doctor'.",
            )

        self._active = True
        try:
            call_method(
                self.conn,
                AGENT_MANAGER_PATH,
                AGENT_MANAGER_IFACE,
                "RegisterAgent",
                GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")),
                5_000,
            )
        except BconnError:
            self._unexport()
            raise

        try:
            call_method(
                self.conn,
                AGENT_MANAGER_PATH,
                AGENT_MANAGER_IFACE,
                "RequestDefaultAgent",
                GLib.Variant("(o)", (AGENT_PATH,)),
                5_000,
            )
        except BconnError as error:
            # Another desktop agent (Blueman, GNOME, KDE) may already be the
            # default. Pairing can still work, but prompts may go elsewhere.
            self.warnings.append(
                "Could not become the default pairing agent "
                f"({error.name or 'unknown error'}). Close other Bluetooth "
                "applets if pairing prompts do not appear."
            )

        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._active = False
        try:
            call_method(
                self.conn,
                AGENT_MANAGER_PATH,
                AGENT_MANAGER_IFACE,
                "UnregisterAgent",
                GLib.Variant("(o)", (AGENT_PATH,)),
                5_000,
            )
        except BconnError:
            pass
        self._unexport()

    def _unexport(self) -> None:
        if self._registration_id:
            try:
                self.conn.unregister_object(self._registration_id)
            except GLib.Error:
                pass
            self._registration_id = None

    def _device_name(self, path: str) -> str:
        if self.name_lookup:
            try:
                name = self.name_lookup(path)
                if name:
                    return name
            except Exception:
                pass
        tail = path.rsplit("/", 1)[-1]
        if tail.startswith("dev_"):
            return tail[4:].replace("_", ":")
        return path

    def _reject(self, invocation: Gio.DBusMethodInvocation, reason: str) -> None:
        invocation.return_dbus_error("org.bluez.Error.Rejected", reason)

    def _on_method_call(
        self,
        connection: Gio.DBusConnection,
        sender: str,
        object_path: str,
        interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Release":
            self._active = False
            invocation.return_value(None)
            return

        if not self._active:
            self._reject(invocation, "No pairing session is active")
            return

        try:
            args = parameters.unpack()
            self._dispatch(method_name, args, invocation)
        except Exception as error:  # never let an exception cross the D-Bus call
            invocation.return_dbus_error(
                "org.bluez.Error.Failed", f"Pairing agent error: {error}"
            )

    def _dispatch(
        self,
        method_name: str,
        args: tuple,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Release":
            self._active = False
            invocation.return_value(None)

        elif method_name == "RequestPinCode":
            device = self._device_name(args[0])
            pin = self.prompter.request_pin(device)
            if pin is None:
                self._reject(invocation, "PIN entry cancelled")
            else:
                invocation.return_value(GLib.Variant("(s)", (pin,)))

        elif method_name == "DisplayPinCode":
            self.prompter.display_pin(self._device_name(args[0]), args[1])
            invocation.return_value(None)

        elif method_name == "RequestPasskey":
            device = self._device_name(args[0])
            passkey = self.prompter.request_passkey(device)
            if passkey is None:
                self._reject(invocation, "Passkey entry cancelled")
            else:
                invocation.return_value(GLib.Variant("(u)", (int(passkey),)))

        elif method_name == "DisplayPasskey":
            self.prompter.display_passkey(
                self._device_name(args[0]), int(args[1]), int(args[2])
            )
            invocation.return_value(None)

        elif method_name == "RequestConfirmation":
            device = self._device_name(args[0])
            if self.prompter.confirm(device, int(args[1])):
                invocation.return_value(None)
            else:
                self._reject(invocation, "Pairing rejected by user")

        elif method_name == "RequestAuthorization":
            device = self._device_name(args[0])
            if self.prompter.authorize(device, ""):
                invocation.return_value(None)
            else:
                self._reject(invocation, "Authorization rejected by user")

        elif method_name == "AuthorizeService":
            device = self._device_name(args[0])
            if self.prompter.authorize(device, args[1]):
                invocation.return_value(None)
            else:
                self._reject(invocation, "Service authorization rejected by user")

        elif method_name == "Cancel":
            self.cancelled = True
            self.prompter.cancel()
            invocation.return_value(None)

        else:
            invocation.return_dbus_error(
                "org.bluez.Error.NotSupported", f"Unknown agent method {method_name}"
            )


def pair_requires_agent(error: BluezError) -> bool:
    return error.name.startswith("org.bluez.Error.Authentication")
