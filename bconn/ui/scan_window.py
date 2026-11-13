"""The scan / devices window."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import model  # noqa: E402


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class ScanWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Bluetooth — BConn")
        self.app = app
        self.set_default_size(900, 580)
        self.set_border_width(0)

        self._filter = "all"
        self._signature: tuple | None = None
        self._by_address: dict[str, object] = {}
        self._message_action = None

        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Bluetooth")
        header.set_subtitle("BConn")
        self.set_titlebar(header)

        self.scan_button = Gtk.Button(label="Scan")
        self.scan_button.set_tooltip_text("Scan for nearby devices (Space)")
        self.scan_button.connect("clicked", self._on_scan_clicked)
        self.scan_button.get_style_context().add_class("suggested-action")
        header.pack_start(self.scan_button)

        prefs = Gtk.Button.new_from_icon_name(
            "emblem-system-symbolic", Gtk.IconSize.BUTTON
        )
        prefs.set_tooltip_text("Preferences")
        prefs.get_accessible().set_name("Preferences")
        prefs.connect("clicked", lambda *_: self.app.show_preferences(self))
        header.pack_end(prefs)

        doctor = Gtk.Button.new_from_icon_name(
            "dialog-information-symbolic", Gtk.IconSize.BUTTON
        )
        doctor.set_tooltip_text("System check")
        doctor.get_accessible().set_name("System check")
        doctor.connect("clicked", lambda *_: self.app.show_doctor(self))
        header.pack_end(doctor)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        self.filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.filter_bar.set_border_width(8)
        outer.pack_start(self.filter_bar, False, False, 0)

        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        for key in model.FILTERS:
            button = Gtk.ToggleButton(label=model.FILTER_LABELS[key])
            button.get_style_context().add_class("flat")
            button.set_active(key == "all")
            button.connect("toggled", self._on_filter_toggled, key)
            self.filter_bar.pack_start(button, False, False, 0)
            self._filter_buttons[key] = button

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search name or MAC")
        self.search.set_width_chars(22)
        self.search.connect("search-changed", lambda *_: self.refresh_rows())
        self.filter_bar.pack_end(self.search, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(150)
        outer.pack_start(self.stack, True, True, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_activate_on_single_click(False)
        self.listbox.get_style_context().add_class("bconn-list")
        scroller.add(self.listbox)
        self.stack.add_named(scroller, "list")

        self.message_page = self._build_message_page()
        self.stack.add_named(self.message_page, "message")
        self.stack.set_visible_child_name("list")

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_border_width(8)
        self.footer = Gtk.Label(xalign=0)
        self.footer.get_style_context().add_class("dim-label")
        footer.pack_start(self.footer, True, True, 0)
        self.spinner = Gtk.Spinner()
        footer.pack_end(self.spinner, False, False, 0)
        outer.pack_start(footer, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self.connect("delete-event", self._on_delete)
        self.connect("hide", self._on_hide)

    # ---------------------------------------------------------------- building

    def _build_message_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_border_width(24)
        self.message_icon = Gtk.Image.new_from_icon_name(
            "bluetooth", Gtk.IconSize.DIALOG
        )
        box.add(self.message_icon)
        self.message_title = Gtk.Label()
        self.message_title.get_style_context().add_class("bconn-empty-title")
        box.add(self.message_title)
        self.message_body = Gtk.Label()
        self.message_body.set_line_wrap(True)
        self.message_body.set_justify(Gtk.Justification.CENTER)
        self.message_body.set_max_width_chars(52)
        self.message_body.get_style_context().add_class("dim-label")
        box.add(self.message_body)
        self.message_button = Gtk.Button()
        self.message_button.get_style_context().add_class("suggested-action")
        self.message_button.set_halign(Gtk.Align.CENTER)
        self.message_button.connect("clicked", self._on_message_action)
        self.message_button.hide()
        box.add(self.message_button)
        return box

    def _show_message(
        self,
        icon: str,
        title: str,
        body: str,
        action_label: str | None = None,
        action=None,
    ) -> None:
        self.message_icon.set_from_icon_name(icon, Gtk.IconSize.DIALOG)
        self.message_title.set_text(title)
        self.message_body.set_text(body)
        self._message_action = action
        if action_label and action is not None:
            self.message_button.set_label(action_label)
            self.message_button.show()
        else:
            self.message_button.hide()
        self.stack.set_visible_child_name("message")

    def _on_message_action(self, _button: Gtk.Button) -> None:
        if self._message_action is not None:
            self._message_action()

    # ------------------------------------------------------------------ state

    def set_scanning(self, scanning: bool) -> None:
        self.scan_button.set_label("Stop" if scanning else "Scan")
        if scanning:
            self.scan_button.get_style_context().remove_class("suggested-action")
            self.spinner.show()
            self.spinner.start()
        else:
            self.scan_button.get_style_context().add_class("suggested-action")
            self.spinner.stop()
            self.spinner.hide()

    def set_footer(self, text: str) -> None:
        self.footer.set_text(text)

    def _on_filter_toggled(self, button: Gtk.ToggleButton, key: str) -> None:
        if not button.get_active():
            return
        # ToggleButton has no radio group in GTK 3; keep the set exclusive.
        for other_key, other in self._filter_buttons.items():
            if other_key != key and other.get_active():
                other.set_active(False)
        self._filter = key
        self.refresh_rows()

    def _on_scan_clicked(self, _button: Gtk.Button) -> None:
        self.app.toggle_scan(self)

    def _on_key_press(self, _window, event) -> bool:
        state = event.state
        control = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if control and event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.search.grab_focus()
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        if event.keyval == Gdk.KEY_space and self.search.has_focus() is False:
            self.app.toggle_scan(self)
            return True
        return False

    def _on_delete(self, _window, _event) -> bool:
        return self.app.close_window(self)

    def _on_hide(self, _window) -> None:
        self.app.window_hidden(self)

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        app = self.app
        adapters = list(app.adapters)
        adapter = app.adapter

        if not adapters:
            self.filter_bar.hide()
            self.set_scanning(False)
            self._show_message(
                "bluetooth-disabled",
                "No Bluetooth adapter",
                "BConn could not find a Bluetooth radio. In a virtual machine, "
                "pass a USB adapter through to the guest. Otherwise open the "
                "system check for details.",
                "System check",
                lambda: app.show_doctor(self),
            )
            self.set_footer("No adapter found")
            return

        self.filter_bar.show_all()
        if adapter is None or not adapter.powered:
            self.set_scanning(False)
            self._show_message(
                "bluetooth-disabled",
                "Bluetooth is off",
                "Turn the radio on to scan for and connect your devices.",
                "Turn on Bluetooth",
                lambda: app.set_power(True, self),
            )
            self.set_footer("Bluetooth is off")
            return

        self.set_scanning(app.scanning)
        devices = [
            device
            for device in app.devices
            if model.matches_filter(device, self._filter)
            and model.matches_search(device, self.search.get_text())
        ]
        last_used = {
            address: str(entry.get("last_connected") or "")
            for address, entry in (app.state.data.get("devices") or {}).items()
        }
        devices = model.sort_devices(devices, last_used)
        self._populate(devices)

        if not devices and not app.devices:
            if app.scanning:
                self._show_message(
                    "bluetooth-active",
                    "No devices found yet",
                    "Put the device in pairing mode, keep it close, and wait a "
                    "few seconds.",
                    None,
                    None,
                )
            else:
                self._show_message(
                    "bluetooth",
                    "No known devices",
                    "Start a scan to find nearby headphones, speakers, "
                    "keyboards, and phones.",
                    "Scan now",
                    lambda: app.start_scan(self),
                )
        elif not devices:
            self._show_message(
                "system-search-symbolic",
                "No matching devices",
                "Try a different filter or search term.",
                "Clear search",
                self._clear_search,
            )
        else:
            self.stack.set_visible_child_name("list")

        self.set_footer(self._footer_text(len(devices)))

    def _clear_search(self) -> None:
        self.search.set_text("")

    def _footer_text(self, count: int) -> str:
        app = self.app
        adapter_name = (
            app.adapter.path.rsplit("/", 1)[-1] if app.adapter is not None else "—"
        )
        if app.scanning:
            remaining = app.scan_remaining()
            return f"{count} device(s) · {adapter_name} · scan ends in {remaining}s"
        connected = sum(1 for device in app.devices if device.connected)
        return (
            f"{count} device(s) · {adapter_name} · "
            f"{connected} connected · scan with Space"
        )

    def refresh_rows(self) -> None:
        self._signature = None
        self.refresh()

    def _populate(self, devices: list) -> None:
        signature = tuple(
            (
                device.address,
                device.display_name,
                device.connected,
                device.paired,
                device.trusted,
                device.blocked,
                device.battery,
                device.rssi,
                self.app.busy,
            )
            for device in devices
        )
        self._by_address = {device.address: device for device in devices}
        if signature == self._signature:
            return
        self._signature = signature

        for child in self.listbox.get_children():
            child.destroy()

        for device in devices:
            self.listbox.add(self._make_row(device))
        self.listbox.show_all()

    def _make_row(self, device) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_border_width(8)
        row.add(box)

        image = Gtk.Image.new_from_icon_name(
            model.device_icon(device), Gtk.IconSize.DND
        )
        image.set_size_request(32, 32)
        box.pack_start(image, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = Gtk.Label(xalign=0)
        name.set_markup(f"<b>{_escape(device.display_name)}</b>")
        name.set_ellipsize(3)
        name.set_max_width_chars(38)
        text.pack_start(name, False, False, 0)
        meta_parts = [device.address]
        if device.kind != "other":
            meta_parts.append(device.kind)
        if device.connected and device.battery is not None:
            meta_parts.append(f"{device.battery}%")
        if device.rssi is not None:
            meta_parts.append(f"{device.rssi} dBm")
        meta = Gtk.Label(label=" · ".join(meta_parts), xalign=0)
        meta.set_ellipsize(3)
        meta.set_max_width_chars(48)
        meta.get_style_context().add_class("bconn-meta")
        text.pack_start(meta, False, False, 0)
        box.pack_start(text, True, True, 0)

        signal = Gtk.Label(label=model.rssi_bars(device.rssi))
        signal.get_style_context().add_class("bconn-signal")
        box.pack_start(signal, False, False, 0)

        chip = Gtk.Label(label=model.state_label(device))
        chip.get_style_context().add_class("bconn-chip")
        chip.get_style_context().add_class(f"bconn-chip-{model.state_label(device).lower()}")
        box.pack_start(chip, False, False, 0)

        action = Gtk.Button(label=model.action_label(device))
        action.set_size_request(104, -1)
        if device.connected:
            action.get_style_context().add_class("destructive-action")
        else:
            action.get_style_context().add_class("suggested-action")
        action.set_sensitive(not self.app.busy)
        action.get_accessible().set_name(
            f"{model.action_label(device)} {device.display_name}"
        )
        action.connect("clicked", self._on_action_clicked, device.address)
        box.pack_start(action, False, False, 0)

        menu_button = Gtk.MenuButton()
        menu_button.set_popup(self._make_row_menu(device))
        menu_button.set_relief(Gtk.ReliefStyle.NONE)
        menu_button.set_tooltip_text("More actions")
        menu_button.get_accessible().set_name(f"More actions for {device.display_name}")
        image = Gtk.Image.new_from_icon_name(
            "view-more-symbolic", Gtk.IconSize.BUTTON
        )
        menu_button.add(image)
        box.pack_start(menu_button, False, False, 0)

        if device.blocked:
            row.set_sensitive(True)
            action.set_sensitive(False)
        return row

    def _make_row_menu(self, device) -> Gtk.Menu:
        menu = Gtk.Menu()
        for child in menu.get_children():
            child.destroy()

        details = Gtk.MenuItem(label="Details…")
        details.connect("activate", lambda *_: self.app.show_details(device, self))
        menu.append(details)

        rename = Gtk.MenuItem(label="Rename…")
        rename.connect("activate", lambda *_: self._rename(device))
        menu.append(rename)

        menu.append(Gtk.SeparatorMenuItem())

        auto = Gtk.CheckMenuItem(label="Auto-connect")
        auto.set_active(self.app.config.auto_connect_enabled(device.address))
        auto.connect(
            "toggled",
            lambda item: self.app.set_auto_connect(device, item.get_active()),
        )
        menu.append(auto)

        route = Gtk.CheckMenuItem(label="Route audio here")
        pref = self.app.config.data.get("devices", {}).get(device.address, {})
        route.set_active(bool(pref.get("prefer_audio", True)))
        route.set_sensitive(device.is_audio)
        route.connect(
            "toggled",
            lambda item: self.app.set_prefer_audio(device, item.get_active()),
        )
        menu.append(route)

        menu.append(Gtk.SeparatorMenuItem())

        forget = Gtk.MenuItem(label="Forget device…")
        forget.connect("activate", lambda *_: self.app.confirm_forget(device, self))
        menu.append(forget)

        menu.show_all()
        return menu

    def _on_action_clicked(self, _button: Gtk.Button, address: str) -> None:
        device = self._by_address.get(address)
        if device is None:
            self.refresh_rows()
            return
        if device.connected:
            self.app.disconnect_device(device, self)
        else:
            self.app.connect_device(device, self)

    def _rename(self, device) -> None:
        dialog = Gtk.Dialog(
            title="Rename device",
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save = dialog.add_button("Save", Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.add(Gtk.Label(label="Name shown in BConn:", xalign=0))
        entry = Gtk.Entry()
        entry.set_text(device.alias or device.name or "")
        entry.set_activates_default(True)
        box.add(entry)
        dialog.show_all()
        entry.grab_focus()
        if dialog.run() == Gtk.ResponseType.OK:
            self.app.set_device_alias(device, entry.get_text().strip(), self)
        dialog.destroy()
