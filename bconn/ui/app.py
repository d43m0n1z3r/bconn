"""BConn tray application and device controller."""

from __future__ import annotations

import math
import signal
import threading
import time
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import audio, bluez, transaction  # noqa: E402
from ..config import Config, State  # noqa: E402
from ..errors import BconnError, SystemNotReady  # noqa: E402
from . import icons, model  # noqa: E402
from .details import DeviceDetailsDialog  # noqa: E402
from .doctor import DoctorDialog  # noqa: E402
from .notifications import Notifier  # noqa: E402
from .pairing import GtkPrompter  # noqa: E402
from .preferences import PreferencesWindow  # noqa: E402
from .scan_window import ScanWindow  # noqa: E402

APP_ID = "org.bconn.Bconn"

CSS = """
.bconn-meta { font-size: 90%; opacity: 0.72; }
.bconn-signal { font-family: monospace; opacity: 0.55; letter-spacing: 1px; }
.bconn-chip {
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 88%;
    background-color: alpha(@theme_fg_color, 0.08);
}
.bconn-chip-connected { background-color: alpha(#2ec27e, 0.22); }
.bconn-chip-paired { background-color: alpha(#3584e4, 0.18); }
.bconn-chip-trusted { background-color: alpha(#3584e4, 0.12); }
.bconn-chip-blocked { background-color: alpha(#e01b24, 0.20); }
.bconn-empty-title { font-size: 145%; font-weight: 600; }
.bconn-list row { border-bottom: 1px solid alpha(@theme_fg_color, 0.08); }
"""


@dataclass
class SinkCache:
    at: float = 0.0
    sinks: list[audio.Sink] | None = None


class BconnApplication(Gtk.Application):
    def __init__(self, show_window: bool = False):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.show_window_on_start = show_window
        self._wants_window = show_window
        self.config = Config()
        self.state = State()
        self.conn = None
        self.adapters: list[bluez.Adapter] = []
        self.devices: list[bluez.Device] = []
        self.adapter: bluez.Adapter | None = None
        self.system_error: BconnError | None = None
        self.last_error: BconnError | None = None
        self._error_at = 0.0
        self.notifier: Notifier | None = None
        self.indicator = None
        self.tray_available = False
        self.window: ScanWindow | None = None
        self.busy = False
        self.scanning = False
        self._scan_source = 0
        self._scan_deadline = 0.0
        self._timer_source = 0
        self._menu: Gtk.Menu | None = None
        self._menu_building = False
        self._held = False
        self._sink_cache = SinkCache()
        self._tray_state: str | None = None
        self._last_warning: str | None = None

    # -------------------------------------------------------------- lifecycle

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(
            "bconn"
            if Gtk.IconTheme.get_default().has_icon("bconn")
            else "bluetooth"
        )
        self._install_css()
        self.notifier = Notifier(enabled=bool(self.config.data.get("notifications", True)))
        self.hold()
        self._held = True
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_sigint)
        for warning in self.config.warnings + self.state.warnings:
            self._last_warning = warning

    def _on_sigint(self) -> bool:
        self.quit_app()
        return False

    def do_command_line(self, command_line) -> int:
        # Runs in the primary instance for both the first launch and later
        # ones, so `bconn-gui --window` can raise the window of an existing
        # tray process instead of silently doing nothing.
        arguments = command_line.get_arguments()
        if "--window" in arguments:
            self._wants_window = True
        self.activate()
        return 0

    def do_activate(self) -> None:
        if self.indicator is None and not self.tray_available:
            self._create_indicator()
        self.refresh_now()
        if not self._timer_source:
            self._timer_source = GLib.timeout_add_seconds(5, self._on_timer)
        wants_window = self._wants_window or self.show_window_on_start
        self._wants_window = False
        if wants_window or not self.tray_available:
            self.show_window()
        elif self._last_warning:
            self.notifier.send("BConn", self._last_warning)
            self._last_warning = None

    def do_shutdown(self) -> None:
        self.stop_scan()
        if self._timer_source:
            GLib.source_remove(self._timer_source)
            self._timer_source = 0
        if self._held:
            self.release()
            self._held = False
        Gtk.Application.do_shutdown(self)

    def quit_app(self) -> None:
        self.stop_scan()
        self.quit()

    # ------------------------------------------------------------------- css

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_data(CSS.encode("utf-8"))
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except GLib.Error:
            pass

    # ------------------------------------------------------------------ tray

    def _create_indicator(self) -> None:
        app_indicator = None
        try:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as app_indicator  # type: ignore
        except (ValueError, ImportError):
            try:
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3 as app_indicator  # type: ignore
            except (ValueError, ImportError):
                self.tray_available = False
                return

        try:
            root = icons.ensure_icons()
            indicator = app_indicator.Indicator.new(
                "bconn",
                icons.icon_name("ready"),
                app_indicator.IndicatorCategory.HARDWARE,
            )
            indicator.set_icon_theme_path(str(root))
            indicator.set_status(app_indicator.IndicatorStatus.ACTIVE)
            indicator.set_title("BConn")
            icons.apply_icon(indicator, "ready")
            indicator.set_menu(self._build_menu())
            self.indicator = indicator
            self.tray_available = True
        except Exception:
            self.indicator = None
            self.tray_available = False

    def _on_timer(self) -> bool:
        if self.busy:
            return True
        if self.scanning:
            self._update_tray()
            return True
        self.refresh_now()
        return True

    def refresh_now(self) -> None:
        if self.busy:
            return
        self._refresh_data()
        self._update_tray()
        self._update_window()

    def _refresh_data(self) -> None:
        try:
            if self.conn is None:
                self.conn = bluez.connect_system_bus()
            adapters, devices = bluez.get_objects(self.conn)
            self.adapters = adapters
            self.devices = devices
            self.adapter = (
                bluez.select_adapter(adapters, self.config.data.get("adapter"))
                if adapters
                else None
            )
            self.system_error = None
        except SystemNotReady as error:
            self.conn = None
            self.adapters = []
            self.devices = []
            self.adapter = None
            self.system_error = error
        except BconnError as error:
            self.system_error = error
            if isinstance(error, SystemNotReady):
                self.conn = None

    def _error_active(self) -> bool:
        return self.last_error is not None and (time.monotonic() - self._error_at) < 300

    def _clear_error(self) -> None:
        self.last_error = None
        self._error_at = 0.0

    def _set_error(self, error: BconnError) -> None:
        self.last_error = error
        self._error_at = time.monotonic()

    def _update_tray(self) -> None:
        if self.indicator is None:
            return
        state = model.tray_state(
            self.adapters,
            self.devices,
            scanning=self.scanning,
            error=self._error_active(),
        )
        if self.system_error is not None and state == "ready":
            state = "attention"
        tooltip = model.tray_tooltip(
            state,
            self.devices,
            adapter_name=self.adapter.display_name if self.adapter else None,
            error=self.last_error.title if self.last_error else None,
        )
        if state != self._tray_state:
            icons.apply_icon(self.indicator, state)
            self._tray_state = state
        try:
            self.indicator.set_title(f"BConn — {tooltip}")
        except Exception:
            pass
        self._install_menu()

    def _install_menu(self) -> None:
        if self.indicator is None or self._menu_building:
            return
        self._menu_building = True
        try:
            menu = self._build_menu()
            self._menu = menu
            self.indicator.set_menu(menu)
        except Exception:
            pass
        finally:
            self._menu_building = False

    def _on_menu_show(self, _menu: Gtk.Menu) -> None:
        if self.busy:
            return
        self._refresh_data()
        if self.indicator is not None:
            state = model.tray_state(
                self.adapters,
                self.devices,
                scanning=self.scanning,
                error=self._error_active(),
            )
            if self.system_error is not None and state == "ready":
                state = "attention"
            icons.apply_icon(self.indicator, state)
            self._tray_state = state

    # ------------------------------------------------------------------ menu

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        menu.connect("show", self._on_menu_show)

        powered = bool(self.adapter and self.adapter.powered)
        has_adapter = self.adapter is not None
        if has_adapter:
            header = self._item(f"Bluetooth — {'On' if powered else 'Off'}")
            header.set_tooltip_text(
                f"{self.adapter.display_name} — click to turn Bluetooth "
                f"{'off' if powered else 'on'}"
            )
            header.connect("activate", lambda *_: self.set_power(not powered))
        else:
            header = self._item("Bluetooth — unavailable")
            header.set_sensitive(False)
        menu.append(header)

        if self.system_error is not None:
            warn = self._item("Bluetooth isn't ready — system check…")
            warn.connect("activate", lambda *_: self.show_doctor())
            menu.append(warn)

        if self._error_active() and self.last_error is not None:
            banner = self._item(f"⚠ {self.last_error.title} — details…")
            banner.connect("activate", lambda *_: self.show_error())
            menu.append(banner)

        connected = [device for device in self.devices if device.connected]
        if connected:
            menu.append(Gtk.SeparatorMenuItem())
            for device in model.sort_devices(connected):
                item = self._item(self._device_menu_label(device), model.device_icon(device))
                submenu = self._device_submenu(device)
                item.set_submenu(submenu)
                menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        quick = Gtk.MenuItem()
        quick.set_label("Quick connect")
        quick.set_use_underline(False)
        quick.set_submenu(self._quick_connect_menu(connected))
        menu.append(quick)

        scan = self._item("Scan for devices…")
        scan.connect("activate", lambda *_: self.show_window(start_scan=True))
        menu.append(scan)

        audio_item = Gtk.MenuItem()
        audio_item.set_label("Audio output")
        audio_item.set_use_underline(False)
        audio_item.set_submenu(self._audio_menu())
        menu.append(audio_item)

        menu.append(Gtk.SeparatorMenuItem())
        doctor = self._item("System check…")
        doctor.connect("activate", lambda *_: self.show_doctor())
        menu.append(doctor)

        prefs = self._item("Preferences…")
        prefs.connect("activate", lambda *_: self.show_preferences())
        menu.append(prefs)

        quit_item = self._item("Quit")
        quit_item.connect("activate", lambda *_: self.quit_app())
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _item(self, label: str, icon: str | None = None) -> Gtk.MenuItem:
        if icon:
            item = Gtk.ImageMenuItem()
            item.set_image(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
            )
            item.set_always_show_image(True)
        else:
            item = Gtk.MenuItem()
        item.set_label(label)
        item.set_use_underline(False)
        return item

    def _device_menu_label(self, device) -> str:
        battery = f" · {device.battery}%" if device.battery is not None else ""
        return f"{device.display_name}{battery}"

    def _device_submenu(self, device) -> Gtk.Menu:
        submenu = Gtk.Menu()
        details = self._item("Details…")
        details.connect("activate", lambda *_: self.show_details(device))
        submenu.append(details)
        disconnect = self._item("Disconnect")
        disconnect.connect("activate", lambda *_: self.disconnect_device(device))
        submenu.append(disconnect)
        submenu.append(Gtk.SeparatorMenuItem())
        forget = self._item("Forget device…")
        forget.connect("activate", lambda *_: self.confirm_forget(device))
        submenu.append(forget)
        submenu.show_all()
        return submenu

    def _quick_connect_menu(self, connected: list[bluez.Device]) -> Gtk.Menu:
        submenu = Gtk.Menu()
        state_devices = self.state.data.get("devices") or {}
        configured = self.config.data.get("devices") or {}
        candidates = model.quick_connect_devices(
            self.devices, state_devices, configured.keys()
        )
        visible_addresses = {device.address for device in candidates}
        if not candidates:
            empty = self._item("No known devices yet")
            empty.set_sensitive(False)
            submenu.append(empty)

        for device in candidates:
            entry = state_devices.get(device.address) or {}
            label = device.display_name
            item = self._item(label, model.device_icon(device))
            item.set_tooltip_text(
                f"{device.address} · {model.last_used_label(entry.get('last_connected'))}"
            )
            item.connect(
                "activate", lambda _item, dev=device: self.connect_device(dev)
            )
            submenu.append(item)

        missing = [
            address
            for address in configured
            if address not in visible_addresses
            and not any(device.address == address for device in self.devices)
        ]
        for address in sorted(missing):
            entry = state_devices.get(address) or {}
            pref = configured.get(address) or {}
            name = pref.get("alias") or address
            item = self._item(f"{name} — not in range")
            item.set_sensitive(False)
            item.set_tooltip_text(model.last_used_label(entry.get("last_connected")))
            submenu.append(item)

        if candidates or missing:
            submenu.append(Gtk.SeparatorMenuItem())
        scan = self._item("Scan for more…")
        scan.connect("activate", lambda *_: self.show_window(start_scan=True))
        submenu.append(scan)
        submenu.show_all()
        return submenu

    def _audio_menu(self) -> Gtk.Menu:
        submenu = Gtk.Menu()
        sinks = self._sinks()
        if sinks is None:
            error = self._item("PipeWire is unavailable")
            error.set_sensitive(False)
            submenu.append(error)
        elif not sinks:
            empty = self._item("No audio outputs found")
            empty.set_sensitive(False)
            submenu.append(empty)
        else:
            first: Gtk.RadioMenuItem | None = None
            for sink in sinks:
                label = sink.display_name
                if sink.is_bluetooth:
                    label += "  (Bluetooth)"
                item = Gtk.RadioMenuItem(label=label)
                item.set_use_underline(False)
                if first is None:
                    first = item
                else:
                    item.join_group(first)
                item.set_active(sink.is_default)
                item.connect("toggled", self._on_sink_toggled, sink)
                submenu.append(item)
            submenu.append(Gtk.SeparatorMenuItem())
            refresh = self._item("Refresh list")
            refresh.connect("activate", lambda *_: self._refresh_audio_menu())
            submenu.append(refresh)
        submenu.show_all()
        return submenu

    def _refresh_audio_menu(self) -> None:
        self._sink_cache = SinkCache()
        self._install_menu()

    def _on_sink_toggled(self, item: Gtk.RadioMenuItem, sink: audio.Sink) -> None:
        if item.get_active():
            self.set_audio_sink(sink)

    def _sinks(self) -> list[audio.Sink] | None:
        now = time.monotonic()
        if self._sink_cache.sinks is not None and now - self._sink_cache.at < 5:
            return self._sink_cache.sinks
        try:
            sinks = audio.list_sinks()
        except audio.AudioRoutingError:
            return None
        self._sink_cache = SinkCache(at=now, sinks=sinks)
        return sinks

    # --------------------------------------------------------------- windows

    def show_window(self, start_scan: bool = False) -> None:
        if self.window is None:
            self.window = ScanWindow(self)
        self.window.show_all()
        self.refresh_now()
        self.window.present()
        if start_scan:
            self.start_scan(self.window)

    def _update_window(self) -> None:
        if self.window is not None and self.window.get_visible():
            self.window.refresh()

    def close_window(self, window: Gtk.Window) -> bool:
        if self.tray_available:
            self.stop_scan()
            window.hide()
            return True
        self.quit_app()
        return False

    def window_hidden(self, _window: Gtk.Window) -> None:
        if self.scanning:
            self.stop_scan()

    def show_preferences(self, parent: Gtk.Window | None = None) -> None:
        PreferencesWindow(self, parent or self._active_window()).present()

    def show_doctor(self, parent: Gtk.Window | None = None) -> None:
        DoctorDialog(parent or self._active_window()).present()

    def show_details(self, device, parent: Gtk.Window | None = None) -> None:
        DeviceDetailsDialog(self, device, parent or self._active_window()).present()

    def show_error(self, parent: Gtk.Window | None = None) -> None:
        error = self.last_error
        if error is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=parent or self._active_window(),
            modal=False,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CLOSE,
            text=error.title,
            secondary_text=error.hint or "Run the system check for details.",
        )
        dialog.connect("response", lambda *_: dialog.destroy())
        dialog.show()

    def _active_window(self) -> Gtk.Window | None:
        return self.window if self.window is not None and self.window.get_visible() else None

    # ------------------------------------------------------------------ scan

    def scan_remaining(self) -> int:
        if not self.scanning:
            return 0
        return max(0, int(math.ceil(self._scan_deadline - time.monotonic())))

    def start_scan(self, window: ScanWindow | None = None) -> None:
        if self.scanning:
            return
        self.refresh_now()
        if self.adapter is None or not self.adapter.powered:
            self._update_window()
            return
        try:
            bluez.start_discovery(self.conn, self.adapter)
        except BconnError as error:
            self._fail(error)
            return
        timeout = float(self.config.data.get("scan_timeout_seconds", 12))
        self.scanning = True
        self._scan_deadline = time.monotonic() + timeout
        self._scan_source = GLib.timeout_add(700, self._scan_tick)
        self._update_tray()
        self._update_window()

    def stop_scan(self) -> None:
        if self._scan_source:
            GLib.source_remove(self._scan_source)
            self._scan_source = 0
        was_scanning = self.scanning
        self.scanning = False
        if was_scanning and self.conn is not None and self.adapter is not None:
            bluez.stop_discovery(self.conn, self.adapter)
        if was_scanning:
            self._update_tray()
            self._update_window()

    def toggle_scan(self, window: ScanWindow | None = None) -> None:
        if self.scanning:
            self.stop_scan()
        else:
            self.start_scan(window)

    def _scan_tick(self) -> bool:
        if not self.scanning:
            return False
        if time.monotonic() >= self._scan_deadline:
            self.stop_scan()
            return False
        try:
            if self.conn is None:
                self.conn = bluez.connect_system_bus()
            adapters, devices = bluez.get_objects(self.conn)
            self.adapters = adapters
            self.devices = devices
            self.adapter = (
                bluez.select_adapter(adapters, self.config.data.get("adapter"))
                if adapters
                else None
            )
        except BconnError as error:
            self._fail(error)
            self.stop_scan()
            return False
        self._update_window()
        return True

    # ------------------------------------------------------------- operations

    def _fail(self, error: BconnError) -> None:
        self._set_error(error)
        if error.hint:
            self.notifier.error(error.title, error.hint)
        else:
            self.notifier.error(error.title)
        self._update_tray()
        self._update_window()

    def _begin(self, device=None) -> bool:
        if self.busy:
            return False
        self.busy = True
        if device is not None and self.window is not None:
            self.window.set_footer(f"Working on {device.display_name}…")
        self._update_window()
        return True

    def _end(self) -> None:
        self.busy = False
        self._update_window()

    def connect_device(self, device, parent: Gtk.Window | None = None) -> None:
        if self.busy:
            return
        if self.scanning:
            self.stop_scan()
        if not self._begin(device):
            return
        try:
            self._refresh_data()
            if self.adapter is None:
                raise SystemNotReady("No Bluetooth adapter was found.")
            transaction.ensure_adapter_powered(self.conn, self.adapter)
            prompter = GtkPrompter(parent or self._active_window(), self.notifier)
            result = transaction.connect_device(
                self.conn, self.adapter, device, prompter
            )
            self._clear_error()
            self.config.set_paused(result.device.address, False)
            self.config.device(result.device.address)
            self.config.save()
            self.state.record_connected(result.device.address)
            self.state.record_battery(result.device.address, result.device.battery)
            if self.config.data.get("one_audio_device", False):
                self._enforce_one_audio(result.device)
            battery = (
                f" · {result.device.battery}%" if result.device.battery is not None else ""
            )
            self.notifier.success(
                f"{result.device.display_name} connected", battery.lstrip(" ·")
            )
            for warning in result.warnings:
                self.notifier.send("BConn", warning)
            self._route_audio_async(result.device)
        except BconnError as error:
            self._fail(error)
        finally:
            self._end()
            self.refresh_now()

    def disconnect_device(self, device, parent: Gtk.Window | None = None) -> None:
        if self.busy:
            return
        if not self._begin(device):
            return
        try:
            transaction.disconnect_device(self.conn, device)
            self.config.set_paused(device.address, True)
            self._clear_error()
            self._sink_cache = SinkCache()
        except BconnError as error:
            self._fail(error)
        finally:
            self._end()
            self.refresh_now()

    def _enforce_one_audio(self, target) -> None:
        for device in self.devices:
            if (
                device.connected
                and device.is_audio
                and device.address != target.address
            ):
                try:
                    transaction.disconnect_device(self.conn, device)
                    self.config.set_paused(device.address, True)
                except BconnError:
                    pass

    def _route_audio_async(self, device) -> None:
        if not device.is_audio:
            return
        pref = self.config.data.get("devices", {}).get(device.address, {})
        if not pref.get("prefer_audio", True):
            return

        def worker() -> None:
            sink = None
            error = None
            try:
                sink = audio.ensure_default_for_device(device.address)
            except audio.AudioRoutingError as exc:
                error = exc
            GLib.idle_add(self._audio_done, device, sink, error)

        threading.Thread(target=worker, daemon=True).start()

    def _audio_done(self, device, sink, error) -> bool:
        self._sink_cache = SinkCache()
        if sink is not None:
            self.notifier.success(f"Audio → {sink.display_name}")
        elif error is not None:
            self.notifier.send("Audio routing failed", error.hint or error.title)
        self._update_tray()
        self._update_window()
        return False

    def set_audio_sink(self, sink: audio.Sink) -> None:
        def worker() -> None:
            result = None
            error = None
            try:
                result = audio.set_default(sink)
            except audio.AudioRoutingError as exc:
                error = exc
            GLib.idle_add(self._sink_done, result, error)

        threading.Thread(target=worker, daemon=True).start()

    def _sink_done(self, sink, error) -> bool:
        self._sink_cache = SinkCache()
        if sink is not None:
            self.notifier.success(f"Audio → {sink.display_name}")
        elif error is not None:
            self.notifier.send("Could not change audio output", error.hint or error.title)
        self._update_tray()
        return False

    def set_power(self, on: bool, parent: Gtk.Window | None = None) -> None:
        if self.busy or self.adapter is None:
            return
        if not self._begin():
            return
        try:
            if not on:
                self.stop_scan()
            bluez.set_adapter_powered(self.conn, self.adapter, on)
            bluez.wait_property(
                self.conn,
                self.adapter.path,
                bluez.ADAPTER_IFACE,
                "Powered",
                on,
                timeout=8,
            )
            self._clear_error()
            self._sink_cache = SinkCache()
        except BconnError as error:
            self._fail(error)
        finally:
            self._end()
            self.refresh_now()

    def set_device_alias(self, device, alias: str, parent: Gtk.Window | None = None) -> None:
        try:
            bluez.set_property(
                self.conn,
                device.path,
                bluez.DEVICE_IFACE,
                "Alias",
                GLib.Variant("s", alias or device.name or device.address),
            )
            self._clear_error()
        except BconnError as error:
            self._fail(error)
            return
        self.refresh_now()

    def set_auto_connect(self, device, enabled: bool) -> None:
        self.set_auto_connect_address(device.address, enabled)

    def set_auto_connect_address(self, address: str, enabled: bool) -> None:
        self.config.set_auto_connect(address, enabled)
        if enabled and not self.config.data.get("auto_connect", True):
            self.notifier.send(
                "Auto-connect is still off",
                "Enable the master switch in Preferences.",
            )
        self._update_window()
        self._update_tray()

    def set_prefer_audio(self, device, enabled: bool) -> None:
        self.set_prefer_audio_address(device.address, enabled)

    def set_prefer_audio_address(self, address: str, enabled: bool) -> None:
        entry = self.config.device(address)
        entry["prefer_audio"] = enabled
        self.config.save()

    def set_config_value(self, key: str, value) -> None:
        self.config.data[key] = value
        self.config.save()
        if key == "notifications" and self.notifier is not None:
            self.notifier.enabled = bool(value)
        self._update_tray()
        self._update_window()

    def confirm_forget(
        self,
        device,
        parent: Gtk.Window | None = None,
        *,
        name: str | None = None,
    ) -> bool:
        if isinstance(device, str):
            address = device
            display = name or address
            real_device = next(
                (item for item in self.devices if item.address == address), None
            )
        else:
            address = device.address
            display = device.display_name
            real_device = device

        dialog = Gtk.MessageDialog(
            transient_for=parent or self._active_window(),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Forget {display}?",
            secondary_text=(
                "This removes the Bluetooth pairing. You will need to pair the "
                "device again."
            ),
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        forget = dialog.add_button("Forget", Gtk.ResponseType.OK)
        forget.get_style_context().add_class("destructive-action")
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return False

        if real_device is not None and self.adapter is not None:
            try:
                transaction.forget_device(self.conn, self.adapter, real_device)
            except BconnError as error:
                self._fail(error)
                return False
        self.config.forget(address)
        self.state.forget(address)
        self._sink_cache = SinkCache()
        self._update_window()
        self.refresh_now()
        return True
