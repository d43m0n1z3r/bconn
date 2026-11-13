"""Preferences window."""

from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402


class PreferencesWindow(Gtk.Dialog):
    def __init__(self, app, parent: Gtk.Window | None = None):
        super().__init__(
            title="BConn — Preferences",
            transient_for=parent,
            modal=False,
            destroy_with_parent=True,
        )
        self.app = app
        self.set_default_size(680, 520)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())

        notebook = Gtk.Notebook()
        notebook.set_border_width(8)
        self.get_content_area().add(notebook)

        notebook.append_page(self._general_page(), Gtk.Label(label="General"))
        notebook.append_page(self._devices_page(), Gtk.Label(label="Devices"))
        notebook.append_page(self._advanced_page(), Gtk.Label(label="Advanced"))
        self.show_all()

    # ---------------------------------------------------------------- general

    def _general_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(14)

        intro = Gtk.Label(
            label="Auto-connect is opt-in per device. Nothing reconnects until "
            "you enable it for that device.",
            xalign=0,
        )
        intro.set_line_wrap(True)
        intro.get_style_context().add_class("dim-label")
        box.add(intro)

        self._general_checks: dict[str, Gtk.CheckButton] = {}
        options = [
            ("auto_connect", "Enable auto-connect", "Master switch for all devices"),
            ("connect_on_start", "Connect on startup", "Reconnect opted-in devices when BConn starts"),
            ("notifications", "Show notifications", "Connection results and pairing codes"),
            ("one_audio_device", "Keep only one audio device connected", "Disconnect other audio devices when one connects"),
        ]
        for key, label, hint in options:
            check = Gtk.CheckButton(label=label)
            check.set_active(bool(self.app.config.data.get(key, False)))
            check.set_tooltip_text(hint)
            check.connect("toggled", self._on_general_toggled, key)
            box.add(check)
            self._general_checks[key] = check

        path = Gtk.Label(label=f"Settings file: {self.app.config.path}", xalign=0)
        path.set_line_wrap(True)
        path.get_style_context().add_class("bconn-meta")
        box.add(path)
        return box

    def _on_general_toggled(self, check: Gtk.CheckButton, key: str) -> None:
        self.app.set_config_value(key, check.get_active())

    # ---------------------------------------------------------------- devices

    def _devices_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.devices_list = Gtk.ListBox()
        self.devices_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(self.devices_list)
        box.pack_start(scroller, True, True, 0)
        self._populate_devices()
        return box

    def _populate_devices(self) -> None:
        for child in self.devices_list.get_children():
            child.destroy()

        addresses = set(self.app.config.data.get("devices", {}))
        by_address = {device.address: device for device in self.app.devices}
        addresses.update(by_address)

        if not addresses:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(
                label="No devices yet. Connect one from the scan window.",
                xalign=0,
            )
            label.set_border_width(12)
            label.get_style_context().add_class("dim-label")
            row.add(label)
            self.devices_list.add(row)
            self.devices_list.show_all()
            return

        for address in sorted(
            addresses,
            key=lambda value: (
                by_address[value].display_name.lower()
                if value in by_address
                else value.lower()
            ),
        ):
            device = by_address.get(address)
            name = device.display_name if device else address
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(8)
            row.add(box)

            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            title = Gtk.Label(xalign=0)
            title.set_markup(f"<b>{_escape(name)}</b>")
            text.pack_start(title, False, False, 0)
            meta = Gtk.Label(label=f"{address} · {'known' if device else 'saved'}", xalign=0)
            meta.get_style_context().add_class("bconn-meta")
            text.pack_start(meta, False, False, 0)
            box.pack_start(text, True, True, 0)

            pref = self.app.config.data.get("devices", {}).get(address, {})
            auto = Gtk.CheckButton(label="Auto-connect")
            auto.set_active(bool(pref.get("auto_connect", False)))
            auto.connect(
                "toggled",
                lambda check, addr=address: self.app.set_auto_connect_address(
                    addr, check.get_active()
                ),
            )
            box.pack_start(auto, False, False, 0)

            route = Gtk.CheckButton(label="Route audio")
            route.set_active(bool(pref.get("prefer_audio", True)))
            route.set_sensitive(bool(device.is_audio) if device else True)
            route.connect(
                "toggled",
                lambda check, addr=address: self.app.set_prefer_audio_address(
                    addr, check.get_active()
                ),
            )
            box.pack_start(route, False, False, 0)

            forget = Gtk.Button(label="Forget")
            forget.get_style_context().add_class("destructive-action")
            forget.connect(
                "clicked",
                lambda _button, addr=address: self._forget(addr, name),
            )
            box.pack_start(forget, False, False, 0)
            self.devices_list.add(row)

        self.devices_list.show_all()

    def _forget(self, address: str, name: str) -> None:
        if self.app.confirm_forget(address, self, name=name):
            self._populate_devices()

    # --------------------------------------------------------------- advanced

    def _advanced_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_border_width(14)

        scan_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        scan_row.pack_start(Gtk.Label(label="Scan duration", xalign=0), False, False, 0)
        spin = Gtk.SpinButton.new_with_range(2, 60, 1)
        spin.set_value(float(self.app.config.data.get("scan_timeout_seconds", 12)))
        spin.connect("value-changed", self._on_scan_timeout)
        scan_row.pack_end(spin, False, False, 0)
        box.add(scan_row)

        adapter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        adapter_row.pack_start(Gtk.Label(label="Preferred adapter", xalign=0), False, False, 0)
        self.adapter_combo = Gtk.ComboBoxText()
        self.adapter_combo.append("", "Automatic")
        preferred = self.app.config.data.get("adapter")
        for index, adapter in enumerate(self.app.adapters):
            name = adapter.path.rsplit("/", 1)[-1]
            self.adapter_combo.append(adapter.path, f"{name} — {adapter.address}")
            if preferred and preferred in (adapter.path, adapter.address, adapter.display_name):
                self.adapter_combo.set_active(index + 1)
        if self.adapter_combo.get_active() < 0:
            self.adapter_combo.set_active(0)
        self.adapter_combo.connect("changed", self._on_adapter_changed)
        adapter_row.pack_end(self.adapter_combo, False, False, 0)
        box.add(adapter_row)

        box.add(Gtk.Separator())

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_folder = Gtk.Button(label="Open config folder")
        open_folder.connect("clicked", self._open_config_folder)
        buttons.pack_start(open_folder, False, False, 0)
        check = Gtk.Button(label="Run system check")
        check.connect("clicked", lambda *_: self.app.show_doctor(self))
        buttons.pack_start(check, False, False, 0)
        box.add(buttons)

        note = Gtk.Label(
            label="BConn never edits system files. When the Bluetooth service is "
            "disabled, the system check shows the exact command to run.",
            xalign=0,
        )
        note.set_line_wrap(True)
        note.get_style_context().add_class("dim-label")
        box.add(note)
        return box

    def _on_scan_timeout(self, spin: Gtk.SpinButton) -> None:
        self.app.set_config_value("scan_timeout_seconds", int(spin.get_value()))

    def _on_adapter_changed(self, combo: Gtk.ComboBoxText) -> None:
        self.app.set_config_value("adapter", combo.get_active_id() or None)

    def _open_config_folder(self) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", str(self.app.config.path.parent)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
