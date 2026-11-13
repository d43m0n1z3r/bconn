"""GTK pairing prompts for the tray application."""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from ..agent import Prompter  # noqa: E402
from .notifications import Notifier  # noqa: E402


class GtkPrompter(Prompter):
    """Blocking GTK dialogs driven by BlueZ agent callbacks.

    BlueZ calls the agent from inside the transaction's nested main loop, so a
    modal dialog with its own nested loop is safe here and keeps the rest of
    the UI painting.
    """

    def __init__(self, parent: Gtk.Window | None = None, notifier: Notifier | None = None):
        self.parent = parent
        self.notifier = notifier

    def _dialog(self, title: str) -> Gtk.Dialog:
        dialog = Gtk.Dialog(
            title=title,
            transient_for=self.parent,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.set_default_size(380, -1)
        dialog.set_resizable(False)
        return dialog

    def _message(self, title: str, body: str, icon: Gtk.MessageType) -> Gtk.MessageDialog:
        return Gtk.MessageDialog(
            transient_for=self.parent,
            modal=True,
            destroy_with_parent=True,
            message_type=icon,
            buttons=Gtk.ButtonsType.NONE,
            text=title,
            secondary_text=body,
        )

    def confirm(self, device_name: str, passkey: int) -> bool:
        dialog = self._message(
            f"Pair with {device_name}?",
            f"Confirm that this code matches the one shown on the device:\n\n"
            f"{passkey:06d}",
            Gtk.MessageType.QUESTION,
        )
        dialog.add_button("Reject", Gtk.ResponseType.REJECT)
        confirm = dialog.add_button("Confirm", Gtk.ResponseType.OK)
        confirm.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def request_passkey(self, device_name: str) -> int | None:
        dialog = self._dialog(f"Passkey for {device_name}")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = dialog.add_button("Pair", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        label = Gtk.Label(
            label=f"Enter the 6-digit passkey shown on {device_name}.",
            xalign=0,
        )
        label.set_line_wrap(True)
        entry = Gtk.Entry()
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        entry.set_max_length(6)
        entry.set_activates_default(True)
        entry.set_placeholder_text("000000")
        error = Gtk.Label(xalign=0)
        error.get_style_context().add_class("error")
        box.add(label)
        box.add(entry)
        box.add(error)
        dialog.show_all()
        entry.grab_focus()

        result: int | None = None
        while True:
            response = dialog.run()
            if response != Gtk.ResponseType.OK:
                break
            raw = entry.get_text().strip()
            if re.fullmatch(r"\d{1,6}", raw):
                result = int(raw)
                break
            error.set_text("Enter between 1 and 6 digits.")
        dialog.destroy()
        return result

    def request_pin(self, device_name: str) -> str | None:
        dialog = self._dialog(f"PIN for {device_name}")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = dialog.add_button("Pair", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.add(Gtk.Label(label=f"Enter the PIN for {device_name}.", xalign=0))
        entry = Gtk.Entry()
        entry.set_max_length(16)
        entry.set_activates_default(True)
        box.add(entry)
        dialog.show_all()
        entry.grab_focus()

        result: str | None = None
        if dialog.run() == Gtk.ResponseType.OK:
            result = entry.get_text().strip() or None
        dialog.destroy()
        return result

    def display_passkey(self, device_name: str, passkey: int, entered: int) -> None:
        if self.notifier:
            self.notifier.send(
                f"Enter {passkey:06d} on {device_name}",
                f"Digits entered: {entered}",
                urgency="normal",
            )

    def display_pin(self, device_name: str, pin: str) -> None:
        if self.notifier:
            self.notifier.send(
                f"Enter PIN {pin} on {device_name}",
                "Pairing will continue automatically.",
                urgency="normal",
            )

    def authorize(self, device_name: str, uuid: str) -> bool:
        body = (
            f"{device_name} is requesting access to a Bluetooth service."
            if not uuid
            else f"{device_name} is requesting access to:\n{uuid}"
        )
        dialog = self._message(
            "Authorize device?", body, Gtk.MessageType.QUESTION
        )
        dialog.add_button("Deny", Gtk.ResponseType.REJECT)
        allow = dialog.add_button("Authorize", Gtk.ResponseType.OK)
        allow.get_style_context().add_class("suggested-action")
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def cancel(self) -> None:
        if self.notifier:
            self.notifier.send("Pairing cancelled", "The device cancelled pairing.")
