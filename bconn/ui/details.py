"""Device details dialog."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import model  # noqa: E402


class DeviceDetailsDialog(Gtk.Dialog):
    def __init__(self, app, device, parent: Gtk.Window | None = None):
        super().__init__(
            title=f"{device.display_name} — Details",
            transient_for=parent,
            modal=False,
            destroy_with_parent=True,
        )
        self.app = app
        self.device = device
        self.set_default_size(560, 520)
        self.add_button("Copy details", Gtk.ResponseType.APPLY)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", self._on_response)

        saved = app.state.data.get("devices", {}).get(device.address, {})
        fields = [
            ("Display name", device.display_name),
            ("Name", device.name or "—"),
            ("Alias", device.alias or "—"),
            ("Address", device.address),
            ("Type", device.kind),
            ("State", model.state_label(device)),
            ("Paired", "yes" if device.paired else "no"),
            ("Trusted", "yes" if device.trusted else "no"),
            ("Connected", "yes" if device.connected else "no"),
            ("Services resolved", "yes" if device.services_resolved else "no"),
            ("Battery", f"{device.battery}%" if device.battery is not None else "—"),
            ("Signal", f"{device.rssi} dBm" if device.rssi is not None else "—"),
            ("Adapter", device.adapter_path.rsplit("/", 1)[-1] or "—"),
            (
                "Auto-connect",
                model.auto_connect_label(app.config.data, device.address),
            ),
            ("Last connected", saved.get("last_connected", "—")),
        ]
        self._text = "\n".join(f"{label}: {value}" for label, value in fields)
        if device.uuids:
            self._text += "\n\nUUIDs:\n" + "\n".join(
                f"  {uuid}" for uuid in device.uuids
            )

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        for row, (label, value) in enumerate(fields):
            name = Gtk.Label(label=label, xalign=0)
            name.get_style_context().add_class("dim-label")
            grid.attach(name, 0, row, 1, 1)
            grid.attach(Gtk.Label(label=str(value), xalign=0, selectable=True), 1, row, 1, 1)
        box.add(grid)

        if device.uuids:
            box.add(Gtk.Separator())
            box.add(Gtk.Label(label="UUIDs", xalign=0))
            uuid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for uuid in device.uuids:
                uuid_box.add(Gtk.Label(label=uuid, xalign=0, selectable=True))
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_shadow_type(Gtk.ShadowType.IN)
            scroll.set_size_request(-1, 150)
            scroll.add(uuid_box)
            box.add(scroll)

        self.show_all()

    def _on_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response == Gtk.ResponseType.APPLY:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self._text, -1)
            clipboard.store()
            return
        self.destroy()
