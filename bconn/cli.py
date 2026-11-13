"""Command-line interface for BConn."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__, audio, bluez, obex, transaction
from .agent import Prompter
from .config import Config, State
from .errors import (
    AmbiguousDevice,
    BconnError,
    BluezError,
    DeviceNotFound,
    SystemNotReady,
)


class CliPrompter(Prompter):
    def __init__(self, auto_accept: bool = False):
        self.auto_accept = auto_accept
        self.interactive = sys.stdin.isatty()

    def _yes_no(self, question: str, default: bool = False) -> bool:
        if self.auto_accept:
            return True
        if not self.interactive:
            print(
                "  (no TTY for a pairing prompt; re-run with --yes to accept "
                "confirmations automatically)",
                file=sys.stderr,
            )
            return False
        try:
            answer = input(f"  {question} [y/N] ").strip().lower()
        except EOFError:
            return default
        return answer in {"y", "yes"}

    def confirm(self, device_name: str, passkey: int) -> bool:
        print(f"\n  Pairing code for {device_name}: {passkey:06d}")
        return self._yes_no("Confirm this code matches the device?")

    def request_passkey(self, device_name: str) -> int | None:
        if self.auto_accept:
            return None
        if not self.interactive:
            print(
                f"  {device_name} requires a passkey; re-run interactively.",
                file=sys.stderr,
            )
            return None
        try:
            raw = input(f"  Enter the 6-digit passkey shown on {device_name}: ")
        except EOFError:
            return None
        raw = raw.strip()
        if not re.fullmatch(r"\d{1,6}", raw):
            print("  Invalid passkey.", file=sys.stderr)
            return None
        return int(raw)

    def request_pin(self, device_name: str) -> str | None:
        if self.auto_accept:
            return None
        if not self.interactive:
            print(
                f"  {device_name} requires a PIN; re-run interactively.",
                file=sys.stderr,
            )
            return None
        try:
            pin = input(f"  Enter the PIN for {device_name}: ").strip()
        except EOFError:
            return None
        return pin or None

    def display_passkey(self, device_name: str, passkey: int, entered: int) -> None:
        print(f"\n  Enter {passkey:06d} on {device_name} (digits entered: {entered}).")

    def display_pin(self, device_name: str, pin: str) -> None:
        print(f"\n  Enter PIN {pin} on {device_name}.")

    def authorize(self, device_name: str, uuid: str) -> bool:
        return self._yes_no(f"Authorize {device_name} for this service?")

    def cancel(self) -> None:
        print("  Pairing cancelled by the device.", file=sys.stderr)


@dataclass
class Context:
    args: argparse.Namespace
    config: Config
    state: State
    conn: Any
    adapters: list[bluez.Adapter]
    devices: list[bluez.Device]
    adapter: bluez.Adapter | None


def _warn_warnings(config: Config, state: State) -> None:
    for warning in config.warnings + state.warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _context(args: argparse.Namespace, require_adapter: bool = False) -> Context:
    config = Config()
    state = State()
    _warn_warnings(config, state)
    conn = bluez.connect_system_bus()
    adapters, devices = bluez.get_objects(conn)
    adapter: bluez.Adapter | None = None
    if adapters:
        try:
            adapter = bluez.select_adapter(adapters, config.data.get("adapter"))
        except SystemNotReady:
            adapter = None
    if require_adapter and adapter is None:
        adapter = bluez.select_adapter(adapters, config.data.get("adapter"))
    return Context(args, config, state, conn, adapters, devices, adapter)


def _resolve(ctx: Context, query: str) -> bluez.Device:
    try:
        return bluez.find_device(ctx.devices, query)
    except DeviceNotFound:
        if getattr(ctx.args, "no_scan", False):
            raise
        if ctx.adapter is None:
            raise
        transaction.ensure_adapter_powered(ctx.conn, ctx.adapter)
        timeout = float(
            getattr(ctx.args, "timeout", None)
            or ctx.config.data.get("scan_timeout_seconds", 12)
        )
        print(
            f"'{query}' is not in the cache; scanning for {timeout:g}s…",
            file=sys.stderr,
        )
        ctx.devices = bluez.scan_devices(ctx.conn, ctx.adapter, timeout)
        return bluez.find_device(ctx.devices, query)


def _device_pref(config: Config, address: str) -> dict[str, Any]:
    entry = config.data.get("devices", {}).get(address, {})
    return entry if isinstance(entry, dict) else {}


def _auto_label(config: Config, address: str) -> str:
    pref = _device_pref(config, address)
    if not config.data.get("auto_connect", True):
        return "master off"
    if not pref.get("auto_connect"):
        return "no"
    if pref.get("paused"):
        return "paused"
    return "yes"


def _state_label(device: bluez.Device) -> str:
    label = device.state
    if device.connected and device.battery is not None:
        label += f" · {device.battery}%"
    return label


def _clip(value: str, width: int) -> str:
    value = value or ""
    return value if len(value) <= width else value[: width - 1] + "…"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


def _rssi(value: int | None) -> str:
    return f"{value} dBm" if value is not None else "—"


def _device_dict(device: bluez.Device, config: Config) -> dict[str, Any]:
    return {
        **asdict(device),
        "display_name": device.display_name,
        "kind": device.kind,
        "state": device.state,
        "auto_connect": _auto_label(config, device.address),
    }


def _format_mac(value: str) -> str:
    key = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    if len(key) == 12:
        return ":".join(key[i : i + 2] for i in range(0, 12, 2))
    return value.upper()


# --------------------------------------------------------------------- commands


def cmd_list(args: argparse.Namespace) -> int:
    ctx = _context(args)
    if args.json:
        print(
            json.dumps(
                {
                    "adapters": [asdict(adapter) for adapter in ctx.adapters],
                    "devices": [
                        _device_dict(device, ctx.config) for device in ctx.devices
                    ],
                },
                indent=2,
            )
        )
        return 0

    if ctx.adapters:
        for adapter in ctx.adapters:
            path_name = adapter.path.rsplit("/", 1)[-1]
            print(
                f"ADAPTER  {path_name}  {adapter.address}  "
                f"{'on' if adapter.powered else 'off'}  \"{adapter.display_name}\""
            )
    else:
        print("No Bluetooth adapter found.")
        print("hint: run 'bconn doctor' (VM users: check USB passthrough).")
        return SystemNotReady.exit_code

    print()
    if not ctx.devices:
        print("No known devices. Run 'bconn scan'.")
        return 0

    devices = sorted(
        ctx.devices,
        key=lambda d: (
            not d.connected,
            not d.paired,
            d.display_name.lower(),
        ),
    )
    rows = [
        [
            _clip(device.display_name, 30),
            device.address,
            device.kind,
            _state_label(device),
            _auto_label(ctx.config, device.address),
        ]
        for device in devices
    ]
    _print_table(["NAME", "ADDRESS", "TYPE", "STATE", "AUTO"], rows)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    transaction.ensure_adapter_powered(ctx.conn, ctx.adapter)
    assert ctx.adapter is not None

    timeout = float(args.timeout or ctx.config.data.get("scan_timeout_seconds", 12))
    if timeout < 2:
        raise BconnError("Scan time must be at least 2 seconds.")
    if not args.json:
        print(f"Scanning for {timeout:g}s on {ctx.adapter.path.rsplit('/', 1)[-1]}…")
        print("Put the device in pairing/discoverable mode and keep it close.")

    seen: dict[str, bluez.Device] = {}

    def on_update(devices: list[bluez.Device]) -> None:
        for device in devices:
            is_new = device.address not in seen
            seen[device.address] = device
            if is_new and not args.json and device.rssi is not None:
                print(
                    f"  found {device.display_name} ({device.address}) "
                    f"{device.rssi} dBm"
                )

    bluez.scan_devices(ctx.conn, ctx.adapter, timeout, on_update=on_update)

    devices = sorted(
        seen.values(),
        key=lambda d: (
            d.rssi is None,
            -(d.rssi or -999),
            d.display_name.lower(),
        ),
    )
    if args.json:
        print(
            json.dumps(
                [_device_dict(device, ctx.config) for device in devices],
                indent=2,
            )
        )
        return 0

    print()
    if not devices:
        print("No devices found.")
        print("hint: check pairing mode, distance, and 'bconn doctor'.")
        return 0

    rows = [
        [
            _clip(device.display_name, 30),
            device.address,
            device.kind,
            _rssi(device.rssi),
            _state_label(device),
        ]
        for device in devices
    ]
    _print_table(["NAME", "ADDRESS", "TYPE", "SIGNAL", "STATE"], rows)
    print(f"\n{len(devices)} device(s). Connect with: bconn connect <name|mac>")
    return 0


def _prompter(args: argparse.Namespace) -> CliPrompter:
    return CliPrompter(auto_accept=getattr(args, "yes", False))


def cmd_pair(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    device = _resolve(ctx, args.device)
    assert ctx.adapter is not None
    transaction.ensure_adapter_powered(ctx.conn, ctx.adapter)

    print(f"Pairing with {device.display_name} ({device.address})…")
    paired_now, warnings = transaction.pair_device(
        ctx.conn, ctx.adapter, device, _prompter(args)
    )
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if paired_now:
        print("Paired ✓  Trusted ✓")
    else:
        print("Already paired ✓  Trusted ✓")

    ctx.config.device(device.address)
    ctx.config.save()

    if args.connect:
        result = transaction.connect_device(
            ctx.conn, ctx.adapter, device, _prompter(args)
        )
        _report_connect(ctx, result)
    else:
        print(f"Connect with: bconn connect {device.address}")
    return 0


def _route_audio(ctx: Context, device: bluez.Device) -> None:
    if getattr(ctx.args, "no_audio", False):
        return
    if not device.is_audio:
        return
    if not _device_pref(ctx.config, device.address).get("prefer_audio", True):
        return
    try:
        sink = audio.ensure_default_for_device(device.address)
    except audio.AudioRoutingError as error:
        print(f"warning: {error.title}", file=sys.stderr)
        if error.hint:
            print(f"         {error.hint}", file=sys.stderr)
        return
    print(f"Audio → {sink.display_name} ✓")


def _report_connect(ctx: Context, result: transaction.ConnectResult) -> None:
    if result.paired_now:
        print("Paired ✓")
    if result.trusted_now:
        print("Trusted ✓")
    print("Connected ✓")
    if result.services_resolved:
        print("Services resolved ✓")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    address = result.device.address
    ctx.config.set_paused(address, False)
    ctx.config.device(address)
    ctx.config.save()
    ctx.state.record_connected(address)
    ctx.state.record_battery(address, result.device.battery)
    print(f"{result.device.display_name} is connected.")
    _route_audio(ctx, result.device)


def cmd_connect(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    device = _resolve(ctx, args.device)
    assert ctx.adapter is not None
    transaction.ensure_adapter_powered(ctx.conn, ctx.adapter)

    if device.connected and device.services_resolved:
        print(f"{device.display_name} is already connected.")
        ctx.config.set_paused(device.address, False)
        ctx.state.record_connected(device.address)
        _route_audio(ctx, device)
        return 0

    print(f"Connecting to {device.display_name} ({device.address})…")
    result = transaction.connect_device(
        ctx.conn, ctx.adapter, device, _prompter(args)
    )
    _report_connect(ctx, result)
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    device = _resolve(ctx, args.device)
    assert ctx.adapter is not None
    transaction.ensure_adapter_powered(ctx.conn, ctx.adapter)

    if not device.paired:
        print(f"Pairing with {device.display_name} ({device.address})…")
        paired_now, warnings = transaction.pair_device(
            ctx.conn, ctx.adapter, device, _prompter(args)
        )
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if paired_now:
            print("Paired ✓")

    files = [Path(path).expanduser() for path in args.files]
    print(
        f"Sending {len(files)} file(s) to {device.display_name} "
        f"({device.address}) over OBEX…"
    )

    last_percent: dict[str, int] = {}

    def progress(source: Path, transferred: int, size: int) -> None:
        if not sys.stderr.isatty() or size <= 0:
            return
        percent = int(transferred * 100 / size)
        step = percent // 10 * 10
        if step <= last_percent.get(source.name, -1) and percent < 100:
            return
        last_percent[source.name] = step
        print(
            f"  {source.name}: {percent}%",
            file=sys.stderr,
            end="\r",
        )
        if percent >= 100:
            print(" " * 60, file=sys.stderr, end="\r")

    timeout = float(args.timeout or 120)
    results = obex.send_files(
        device.address,
        files,
        timeout=timeout,
        progress=progress,
    )
    for result in results:
        print(f"  ✓ {result.filename.name} ({result.transferred} bytes)")
    print("Sent ✓")
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    device = _resolve(ctx, args.device)
    if not device.connected:
        print(f"{device.display_name} is not connected.")
        return 0
    print(f"Disconnecting {device.display_name}…")
    transaction.disconnect_device(ctx.conn, device)
    ctx.config.set_paused(device.address, True)
    print("Disconnected ✓")
    print("Auto-connect is paused for this device until you connect it again.")
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    try:
        ctx = _context(args, require_adapter=True)
        device = _resolve(ctx, args.device)
    except (DeviceNotFound, SystemNotReady):
        if bluez.looks_like_mac(args.device):
            address = _format_mac(args.device)
            config = Config()
            state = State()
            config.forget(address)
            state.forget(address)
            print(f"Removed saved settings for {address} (device was not present).")
            return 0
        raise

    assert ctx.adapter is not None
    if not args.yes:
        if not sys.stdin.isatty():
            raise BconnError(
                "Refusing to forget a device without confirmation.",
                "Re-run with --yes to remove the pairing non-interactively.",
            )
        answer = input(
            f"Forget {device.display_name} ({device.address})? "
            "This removes the pairing. [y/N] "
        )
        if answer.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    transaction.forget_device(ctx.conn, ctx.adapter, device)
    ctx.config.forget(device.address)
    ctx.state.forget(device.address)
    print(f"Forgot {device.display_name} ({device.address}).")
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    ctx = _context(args, require_adapter=True)
    assert ctx.adapter is not None
    action = args.state

    if action is None:
        print(f"{ctx.adapter.display_name}: {'on' if ctx.adapter.powered else 'off'}")
        return 0

    target = ctx.adapter.powered
    if action == "on":
        target = True
    elif action == "off":
        target = False
    else:
        target = not ctx.adapter.powered

    if target == ctx.adapter.powered:
        print(f"Adapter is already {'on' if target else 'off'}.")
        return 0

    bluez.set_adapter_powered(ctx.conn, ctx.adapter, target)
    if not bluez.wait_property(
        ctx.conn, ctx.adapter.path, bluez.ADAPTER_IFACE, "Powered", target, timeout=8
    ):
        raise BconnError("The adapter did not change power state.")
    print(f"Adapter is now {'on' if target else 'off'}.")
    return 0


def cmd_audio(args: argparse.Namespace) -> int:
    sinks = audio.list_sinks()
    if not sinks:
        raise audio.AudioRoutingError("No audio sinks are available.")

    if args.sink:
        sink = audio.select_sink(sinks, args.sink)
        sink = audio.set_default(sink)
        if args.json:
            print(
                json.dumps(
                    {
                        "id": sink.id,
                        "name": sink.name,
                        "description": sink.description,
                        "bluetooth": sink.is_bluetooth,
                        "default": sink.is_default,
                    },
                    indent=2,
                )
            )
        else:
            print(f"Default audio output → {sink.display_name} ({sink.id}) ✓")
        return 0

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": sink.id,
                        "name": sink.name,
                        "description": sink.description,
                        "address": sink.address,
                        "bluetooth": sink.is_bluetooth,
                        "default": sink.is_default,
                    }
                    for sink in sinks
                ],
                indent=2,
            )
        )
        return 0

    rows = []
    for sink in sinks:
        rows.append(
            [
                "*" if sink.is_default else "",
                str(sink.id),
                _clip(sink.display_name, 42),
                sink.address or "—",
                "bt" if sink.is_bluetooth else "",
            ]
        )
    _print_table(["", "ID", "SINK", "BLUETOOTH ADDRESS", "TYPE"], rows)
    print("\nChoose one with: bconn audio <id|name|mac>")
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    config = Config()
    state = State()
    _warn_warnings(config, state)

    if args.device is None:
        devices: list[bluez.Device] = []
        try:
            ctx = _context(args)
            devices = ctx.devices
        except SystemNotReady:
            pass
        by_address = {device.address: device for device in devices}

        entries = config.data.get("devices", {})
        if args.json:
            print(
                json.dumps(
                    {
                        "master_enabled": config.data.get("auto_connect", True),
                        "devices": [
                            {
                                "address": address,
                                "name": (
                                    by_address[address].display_name
                                    if address in by_address
                                    else address
                                ),
                                "auto_connect": bool(entry.get("auto_connect")),
                                "paused": bool(entry.get("paused")),
                            }
                            for address, entry in entries.items()
                        ],
                    },
                    indent=2,
                )
            )
            return 0

        if not entries:
            print("No devices configured. Connect one, then:")
            print("  bconn auto <name|mac> on")
            return 0

        print(
            "Auto-connect is opt-in per device "
            f"(master switch: {'on' if config.data.get('auto_connect', True) else 'off'})."
        )
        rows = []
        for address, entry in sorted(entries.items()):
            device = by_address.get(address)
            name = device.display_name if device else address
            if not config.data.get("auto_connect", True):
                label = "master off"
            elif entry.get("paused"):
                label = "paused"
            elif entry.get("auto_connect"):
                label = "on"
            else:
                label = "off"
            rows.append([_clip(name, 30), address, label])
        _print_table(["NAME", "ADDRESS", "AUTO-CONNECT"], rows)
        return 0

    if args.state is None:
        raise BconnError("Specify 'on' or 'off' after the device.")

    address: str
    try:
        ctx = _context(args)
        device = bluez.find_device(ctx.devices, args.device)
        address = device.address
        name = device.display_name
    except (DeviceNotFound, SystemNotReady):
        if not bluez.looks_like_mac(args.device):
            raise
        address = _format_mac(args.device)
        name = address

    enabled = args.state == "on"
    config.set_auto_connect(address, enabled)
    if enabled:
        print(f"Auto-connect enabled for {name} ({address}).")
        if not config.data.get("auto_connect", True):
            print("warning: the master auto-connect switch is off.", file=sys.stderr)
    else:
        print(f"Auto-connect disabled for {name} ({address}).")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    ctx = _context(args)
    device = _resolve(ctx, args.device)
    pref = _device_pref(ctx.config, device.address)
    saved = ctx.state.data.get("devices", {}).get(device.address, {})
    info = _device_dict(device, ctx.config)

    if args.json:
        print(
            json.dumps(
                {"device": info, "preferences": pref, "state": saved}, indent=2
            )
        )
        return 0

    fields = [
        ("Name", device.name or "—"),
        ("Alias", device.alias or "—"),
        ("Display name", device.display_name),
        ("Address", device.address),
        ("Type", device.kind),
        ("State", _state_label(device)),
        ("Adapter", device.adapter_path.rsplit("/", 1)[-1] or "—"),
        ("Paired", "yes" if device.paired else "no"),
        ("Trusted", "yes" if device.trusted else "no"),
        ("Connected", "yes" if device.connected else "no"),
        ("Services resolved", "yes" if device.services_resolved else "no"),
        ("Battery", f"{device.battery}%" if device.battery is not None else "—"),
        ("RSSI", _rssi(device.rssi)),
        ("Auto-connect", _auto_label(ctx.config, device.address)),
        ("Last connected", saved.get("last_connected", "—")),
    ]
    width = max(len(label) for label, _ in fields)
    for label, value in fields:
        print(f"{label.ljust(width)}  {value}")
    if device.uuids:
        print("\nUUIDs:")
        for uuid in device.uuids:
            print(f"  {uuid}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    script = Path(__file__).resolve().parent.parent / "bin" / "bconn-doctor"
    if not script.exists():
        found = shutil.which("bconn-doctor")
        if found:
            script = Path(found)
    if not script.exists():
        raise BconnError(
            f"Doctor script not found at {script}.",
            "Run the project copy: ./bin/bconn-doctor",
        )
    return subprocess.call([str(script)])


def cmd_daemon(args: argparse.Namespace) -> int:
    from . import daemon as daemon_mod

    action = args.action
    if action == "run":
        return daemon_mod.run_foreground(
            poll_seconds=args.poll,
            scan_seconds=args.scan,
            allow_audio=not args.no_audio,
            notifications=not args.no_notify,
        )
    if action == "once":
        results = daemon_mod.run_once(
            scan_seconds=args.scan,
            allow_audio=not args.no_audio,
            notifications=not args.no_notify,
        )
        if not results:
            print("nothing to do")
        for result in results:
            print(result)
        return 0
    if action == "install":
        poll = args.poll or daemon_mod.DEFAULT_POLL_SECONDS
        print(daemon_mod.install_unit(poll_seconds=poll))
        print()
        print(daemon_mod.service_status_text(), end="")
        return 0
    if action == "uninstall":
        print(daemon_mod.uninstall_unit())
        return 0
    if action == "logs":
        return daemon_mod.service_logs(follow=args.follow)
    if action in {"start", "stop", "restart"}:
        result = daemon_mod.service_action(action)
        print(daemon_mod.service_status_text(), end="")
        return result.returncode
    # status (default)
    print(daemon_mod.service_status_text(), end="")
    probe = daemon_mod._systemctl("is-active", daemon_mod.UNIT_NAME)
    return 0 if probe.stdout.strip() == "active" else 1


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .ui import main as ui_main
    except (ImportError, ValueError) as error:
        raise BconnError(
            "The graphical interface is unavailable (GTK 3 bindings are missing).",
            "Install python3-gi and gir1.2-gtk-3.0, then retry.",
        ) from error

    try:
        return ui_main(show_window=bool(getattr(args, "window", False)))
    except (ImportError, ValueError) as error:
        raise BconnError(
            "The graphical interface is unavailable (GTK 3 bindings are missing).",
            "Install python3-gi and gir1.2-gtk-3.0, then retry.",
        ) from error
    except RuntimeError as error:
        raise BconnError(
            "Could not open the graphical interface.",
            f"{error} — make sure DISPLAY is set and an X11 session is running.",
        ) from error


def cmd_shortcut(args: argparse.Namespace) -> int:
    from . import shortcut

    action = getattr(args, "action", "install")
    if action == "uninstall":
        print(shortcut.uninstall_shortcut())
        return 0
    if action == "status":
        print(shortcut.status_text())
        return 0 if shortcut.is_installed() else 1
    print(shortcut.install_shortcut())
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"bconn {__version__}")
    return 0


# ----------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show technical details on errors",
    )
    common.add_argument(
        "--no-scan",
        action="store_true",
        default=argparse.SUPPRESS,
        help="do not auto-scan when a device is missing from the cache",
    )

    parser = argparse.ArgumentParser(
        prog="bconn",
        description="BConn — fast, reliable Bluetooth connections from the CLI.",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"bconn {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Any, help_text: str, **kwargs: Any):
        sub = subparsers.add_parser(
            name, help=help_text, parents=[common], **kwargs
        )
        sub.set_defaults(func=func)
        return sub

    p_list = add("list", cmd_list, "list adapters and known devices")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")

    p_scan = add("scan", cmd_scan, "scan for nearby devices")
    p_scan.add_argument("--timeout", type=float, help="scan duration in seconds")
    p_scan.add_argument("--json", action="store_true", help="machine-readable output")

    p_pair = add("pair", cmd_pair, "pair and trust a device")
    p_pair.add_argument("device", help="device name, alias, or MAC address")
    p_pair.add_argument(
        "--connect", action="store_true", help="connect immediately after pairing"
    )
    p_pair.add_argument(
        "--yes", action="store_true", help="auto-accept pairing confirmations"
    )
    p_pair.add_argument(
        "--no-audio", action="store_true", help="do not route audio after connecting"
    )
    p_pair.add_argument(
        "--timeout", type=float, help="scan duration if the device is not cached"
    )

    p_connect = add("connect", cmd_connect, "connect a device (pairs if needed)")
    p_connect.add_argument("device", help="device name, alias, or MAC address")
    p_connect.add_argument(
        "--yes", action="store_true", help="auto-accept pairing confirmations"
    )
    p_connect.add_argument(
        "--no-audio", action="store_true", help="do not route audio after connecting"
    )
    p_connect.add_argument(
        "--timeout", type=float, help="scan duration if the device is not cached"
    )

    p_disconnect = add("disconnect", cmd_disconnect, "disconnect a device")
    p_disconnect.add_argument("device", help="device name, alias, or MAC address")

    p_send = add(
        "send",
        cmd_send,
        "send files to a device over OBEX Object Push",
        aliases=["push"],
    )
    p_send.add_argument("device", help="device name, alias, or MAC address")
    p_send.add_argument("files", nargs="+", help="file paths to send")
    p_send.add_argument(
        "--yes", action="store_true", help="auto-accept pairing confirmations"
    )
    p_send.add_argument(
        "--timeout", type=float, help="seconds to wait per file (default: 120)"
    )

    p_forget = add("forget", cmd_forget, "remove a pairing and its saved settings")
    p_forget.add_argument("device", help="device name, alias, or MAC address")
    p_forget.add_argument("--yes", action="store_true", help="skip confirmation")

    p_power = add("power", cmd_power, "show or change adapter power")
    p_power.add_argument(
        "state", nargs="?", choices=["on", "off", "toggle"], help="new power state"
    )

    p_audio = add(
        "audio", cmd_audio, "list audio outputs or choose the default one"
    )
    p_audio.add_argument(
        "sink", nargs="?", help="sink id, name, description, or device MAC"
    )
    p_audio.add_argument("--json", action="store_true", help="machine-readable output")

    p_auto = add(
        "auto",
        cmd_auto,
        "inspect or change opt-in auto-connect",
        aliases=["autoconnect"],
    )
    p_auto.add_argument(
        "device", nargs="?", help="device name, alias, or MAC address"
    )
    p_auto.add_argument("state", nargs="?", choices=["on", "off"])
    p_auto.add_argument("--json", action="store_true", help="machine-readable output")

    p_info = add("info", cmd_info, "show detailed device information")
    p_info.add_argument("device", help="device name, alias, or MAC address")
    p_info.add_argument("--json", action="store_true", help="machine-readable output")

    p_gui = add(
        "gui",
        cmd_gui,
        "open the tray icon (and optionally the scan window)",
        aliases=["tray", "ui"],
    )
    p_gui.add_argument(
        "--window",
        action="store_true",
        help="open the scan window immediately instead of only the tray icon",
    )

    p_daemon = add(
        "daemon",
        cmd_daemon,
        "manage the auto-reconnect daemon (systemd --user)",
    )
    p_daemon.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=[
            "status",
            "install",
            "uninstall",
            "start",
            "stop",
            "restart",
            "logs",
            "run",
            "once",
        ],
        help="service action (default: status)",
    )
    p_daemon.add_argument("--poll", type=float, help="seconds between reconnect passes")
    p_daemon.add_argument("--scan", type=float, help="scan duration for absent devices")
    p_daemon.add_argument(
        "--no-audio", action="store_true", help="do not route audio after connecting"
    )
    p_daemon.add_argument(
        "--no-notify", action="store_true", help="do not show desktop notifications"
    )
    p_daemon.add_argument(
        "--follow", "-f", action="store_true", help="follow logs (with 'logs')"
    )

    p_shortcut = add(
        "shortcut",
        cmd_shortcut,
        "install or remove the application-menu shortcut",
    )
    p_shortcut.add_argument(
        "action",
        nargs="?",
        default="install",
        choices=["install", "uninstall", "status"],
        help="shortcut action (default: install)",
    )

    add("doctor", cmd_doctor, "run the Bluetooth system check")
    add("version", cmd_version, "show the version")

    return parser


def _print_error(error: BconnError, verbose: bool) -> None:
    print(f"error: {error.title}", file=sys.stderr)
    if error.hint:
        print(f"hint: {error.hint}", file=sys.stderr)
    if verbose and isinstance(error, BluezError) and error.detail:
        print(f"detail: {error.detail}", file=sys.stderr)
    if isinstance(error, AmbiguousDevice):
        for match in error.matches:
            print(
                f"  {getattr(match, 'display_name', match)} "
                f"({getattr(match, 'address', '?')})",
                file=sys.stderr,
            )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BconnError as error:
        _print_error(error, verbose=getattr(args, "verbose", False))
        return error.exit_code
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
