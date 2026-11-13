"""Auto-reconnect daemon and systemd --user service management.

The daemon is intentionally small: it polls BlueZ, connects devices the user
explicitly opted in to, and backs off on failures. Manual disconnects pause a
device (``paused: true`` in the config), so the daemon will not fight them.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from . import audio, bluez, transaction  # noqa: E402
from .config import Config, State  # noqa: E402
from .errors import BconnError  # noqa: E402

LOGGER = logging.getLogger("bconn.daemon")

UNIT_NAME = "bconn-daemon.service"
DEFAULT_POLL_SECONDS = 30.0
DEFAULT_SCAN_SECONDS = 10.0
MIN_BACKOFF_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 300.0
SCAN_INTERVAL_SECONDS = 90.0
HEARTBEAT_SECONDS = 600.0

NotifyCallable = Callable[[str, str, str], None]


def backoff_delay(failures: int) -> float:
    """Exponential backoff, capped; ``failures`` is 1 for the first failure."""
    if failures <= 0:
        return 0.0
    return min(MAX_BACKOFF_SECONDS, MIN_BACKOFF_SECONDS * (2 ** (failures - 1)))


@dataclass
class Attempt:
    failures: int = 0
    next_at: float = 0.0
    notified: bool = False


@dataclass
class CycleResult:
    address: str
    name: str
    action: str
    detail: str = ""

    def __str__(self) -> str:
        line = f"{self.action}: {self.name} ({self.address})"
        if self.detail:
            line += f" — {self.detail}"
        return line


class AutoConnectDaemon:
    def __init__(
        self,
        *,
        config_path: Path | None = None,
        state_path: Path | None = None,
        poll_seconds: float | None = None,
        scan_seconds: float | None = None,
        allow_audio: bool = True,
        notifications: bool = True,
        notifier: NotifyCallable | None = None,
    ):
        self.config_path = config_path
        self.state_path = state_path
        self.poll_seconds = float(
            poll_seconds
            if poll_seconds is not None
            else os.environ.get("BCONN_POLL_SECONDS", DEFAULT_POLL_SECONDS)
        )
        self.scan_seconds = float(
            scan_seconds
            if scan_seconds is not None
            else os.environ.get("BCONN_SCAN_SECONDS", DEFAULT_SCAN_SECONDS)
        )
        self.allow_audio = allow_audio
        self.notifications = notifications
        self.notifier = notifier

        self.config = Config(config_path) if config_path else Config()
        self.state = State(state_path) if state_path else State()
        self.conn: Gio.DBusConnection | None = None
        self._attempts: dict[str, Attempt] = {}
        self._unpaired_notified: set[str] = set()
        self._last_scan = 0.0
        self._last_opt_in: tuple[str, ...] | None = None
        self._loop: GLib.MainLoop | None = None
        self._source_id = 0
        self._tick_count = 0

    # ------------------------------------------------------------- notifications

    def notify(self, summary: str, body: str = "", urgency: str = "normal") -> None:
        if not self.notifications:
            return
        if self.notifier is not None:
            try:
                self.notifier(summary, body, urgency)
            except Exception:
                LOGGER.debug("notifier failed", exc_info=True)
            return
        try:
            import gi

            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            if not Notify.is_initted():
                Notify.init("BConn")
            notification = Notify.Notification.new(summary, body, "bluetooth")
            levels = {
                "low": Notify.Urgency.LOW,
                "normal": Notify.Urgency.NORMAL,
                "critical": Notify.Urgency.CRITICAL,
            }
            notification.set_urgency(levels.get(urgency, Notify.Urgency.NORMAL))
            notification.show()
        except Exception:
            LOGGER.debug("could not show a notification", exc_info=True)

    # ------------------------------------------------------------------ cycles

    def run_once(self) -> list[CycleResult]:
        """Run a single reconnect pass (used by tests and `bconn daemon once`)."""
        return self._cycle()

    def run_foreground(self) -> int:
        self._loop = GLib.MainLoop()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._quit)
        LOGGER.info(
            "auto-connect daemon started (poll %.0fs, scan %.0fs)",
            self.poll_seconds,
            self.scan_seconds,
        )
        self._tick()
        self._loop.run()
        LOGGER.info("auto-connect daemon stopped")
        return 0

    def _quit(self) -> bool:
        if self._source_id:
            GLib.source_remove(self._source_id)
            self._source_id = 0
        if self._loop is not None:
            self._loop.quit()
        return False

    def _tick(self) -> bool:
        self._tick_count += 1
        LOGGER.debug("auto-connect tick #%d", self._tick_count)
        try:
            self._cycle()
        except Exception:
            LOGGER.exception("unexpected error during auto-connect pass")
        finally:
            delay = max(5, int(self.poll_seconds))
            self._source_id = GLib.timeout_add_seconds(delay, self._tick)
            LOGGER.debug("next auto-connect tick in %ss (source %s)", delay, self._source_id)
            # A quiet heartbeat proves the loop is alive without spamming the journal.
            heartbeat_every = max(1, int(HEARTBEAT_SECONDS / delay))
            if self._tick_count % heartbeat_every == 0:
                LOGGER.info(
                    "daemon alive (tick %d, %d opted-in device(s))",
                    self._tick_count,
                    len(self.config.opted_in_devices()),
                )
        return False

    def _cycle(self) -> list[CycleResult]:
        self._reload_config()
        results: list[CycleResult] = []

        if not self.config.data.get("auto_connect", True):
            self._log_opt_in([])
            return results

        opted_in = list(self.config.opted_in_devices())
        self._log_opt_in(opted_in)
        if not opted_in:
            return results

        try:
            if self.conn is None:
                self.conn = bluez.connect_system_bus()
            adapters, devices = bluez.get_objects(self.conn)
        except BconnError as error:
            self.conn = None
            LOGGER.info("Bluetooth is not ready: %s", error.title)
            return results

        if not adapters:
            LOGGER.info("no Bluetooth adapter is present")
            return results

        try:
            adapter = bluez.select_adapter(adapters, self.config.data.get("adapter"))
        except BconnError as error:
            LOGGER.info("no usable adapter: %s", error.title)
            return results

        if not adapter.powered:
            LOGGER.debug("adapter %s is off; waiting", adapter.path)
            return results

        by_address = {device.address: device for device in devices}
        missing = [address for address in opted_in if address not in by_address]
        if missing and (time.monotonic() - self._last_scan) >= SCAN_INTERVAL_SECONDS:
            LOGGER.info("scanning for %d cached-but-absent device(s)", len(missing))
            try:
                devices = bluez.scan_devices(
                    self.conn, adapter, self.scan_seconds
                )
                by_address = {device.address: device for device in devices}
            except BconnError as error:
                LOGGER.info("scan failed: %s", error.title)
            finally:
                self._last_scan = time.monotonic()

        for address in opted_in:
            device = by_address.get(address)
            result = self._maybe_connect(adapter, address, device)
            if result is not None:
                results.append(result)

        return results

    def _reload_config(self) -> None:
        self.config = (
            Config(self.config_path) if self.config_path else Config()
        )
        self.state = State(self.state_path) if self.state_path else State()

    def _log_opt_in(self, addresses: list[str]) -> None:
        signature = tuple(addresses)
        if signature == self._last_opt_in:
            return
        self._last_opt_in = signature
        if addresses:
            LOGGER.info("opted-in devices: %s", ", ".join(addresses))
        else:
            LOGGER.info("no opted-in devices; auto-connect is idle")

    def _maybe_connect(self, adapter, address: str, device) -> CycleResult | None:
        now = time.monotonic()
        if device is None:
            attempt = self._attempts.setdefault(address, Attempt())
            attempt.next_at = now + SCAN_INTERVAL_SECONDS
            return CycleResult(address, address, "absent")

        if not device.paired:
            if address not in self._unpaired_notified:
                self._unpaired_notified.add(address)
                self.notify(
                    "BConn needs a pairing",
                    f"{device.display_name} is opted in but not paired. "
                    "Pair it once from the tray or CLI.",
                    "normal",
                )
            return CycleResult(address, device.display_name, "unpaired")

        self._unpaired_notified.discard(address)

        if device.connected:
            self._attempts.pop(address, None)
            return CycleResult(address, device.display_name, "already connected")

        attempt = self._attempts.get(address)
        if attempt is not None and attempt.next_at > now:
            remaining = int(attempt.next_at - now)
            return CycleResult(
                address,
                device.display_name,
                "backoff",
                f"retrying in {remaining}s",
            )

        try:
            result = transaction.connect_device(
                self.conn, adapter, device, prompter=None
            )
        except BconnError as error:
            attempt = self._attempts.setdefault(address, Attempt())
            attempt.failures += 1
            delay = backoff_delay(attempt.failures)
            attempt.next_at = now + delay
            if not attempt.notified:
                attempt.notified = True
                self.notify(
                    f"Could not connect to {device.display_name}",
                    error.hint or error.title,
                    "normal",
                )
            LOGGER.warning(
                "could not connect %s: %s (retry in %.0fs)",
                device.display_name,
                error.title,
                delay,
            )
            return CycleResult(address, device.display_name, "failed", error.title)

        self._attempts.pop(address, None)
        self.config.device(device.address)
        self.config.set_paused(device.address, False)
        self.state.record_connected(device.address)
        self.state.record_battery(device.address, result.device.battery)

        battery = (
            f" · {result.device.battery}%" if result.device.battery is not None else ""
        )
        LOGGER.info("connected %s%s", result.device.display_name, battery)
        self.notify(
            "BConn connected",
            f"{result.device.display_name} connected{battery}",
            "low",
        )

        if (
            self.allow_audio
            and result.device.is_audio
            and self._prefers_audio(result.device.address)
        ):
            self._route_audio(result.device)

        if self.config.data.get("one_audio_device", False):
            self._enforce_one_audio(result.device)

        return CycleResult(address, result.device.display_name, "connected")

    def _prefers_audio(self, address: str) -> bool:
        entry = self.config.data.get("devices", {}).get(address) or {}
        return bool(entry.get("prefer_audio", True))

    def _route_audio(self, device) -> None:
        try:
            sink = audio.ensure_default_for_device(device.address, timeout=6.0)
            LOGGER.info("audio routed to %s", sink.display_name)
        except audio.AudioRoutingError as error:
            LOGGER.info("audio routing skipped: %s", error.title)

    def _enforce_one_audio(self, target) -> None:
        try:
            _, devices = bluez.get_objects(self.conn)
        except BconnError:
            return
        for device in devices:
            if (
                device.connected
                and device.is_audio
                and device.address != target.address
            ):
                try:
                    transaction.disconnect_device(self.conn, device)
                    LOGGER.info("disconnected %s (one-audio rule)", device.display_name)
                except BconnError:
                    pass


# --------------------------------------------------------------------- systemd


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def daemon_executable() -> str:
    candidate = project_root() / "bin" / "bconn-daemon"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("bconn-daemon")
    return found or "bconn-daemon"


def unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / UNIT_NAME


def render_unit(poll_seconds: float = DEFAULT_POLL_SECONDS) -> str:
    executable = daemon_executable()
    root = project_root()
    environment = ""
    if executable.startswith(str(root)):
        environment = f"Environment=PYTHONPATH={root}\n"
    return (
        "[Unit]\n"
        "Description=BConn Bluetooth auto-reconnect daemon\n"
        "After=graphical-session.target\n"
        "StartLimitIntervalSec=300\n"
        "StartLimitBurst=5\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={executable}\n"
        f"{environment}"
        f"Environment=BCONN_POLL_SECONDS={poll_seconds:g}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(*args: str, timeout: float = 20.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def install_unit(poll_seconds: float = DEFAULT_POLL_SECONDS) -> str:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_unit(poll_seconds), encoding="utf-8")
    os.chmod(path, 0o644)

    reload_result = _systemctl("daemon-reload")
    if reload_result.returncode != 0:
        raise BconnError(
            "Could not reload the user systemd manager.",
            (reload_result.stderr or "").strip() or "Check systemctl --user.",
        )
    enable_result = _systemctl("enable", "--now", UNIT_NAME)
    if enable_result.returncode != 0:
        raise BconnError(
            "Could not enable the BConn daemon service.",
            (enable_result.stderr or enable_result.stdout or "").strip()
            or f"Check `systemctl --user status {UNIT_NAME}`.",
        )
    return f"Installed {path}\nEnabled and started {UNIT_NAME}."


def uninstall_unit() -> str:
    path = unit_path()
    _systemctl("disable", "--now", UNIT_NAME)
    if path.exists():
        path.unlink()
    _systemctl("daemon-reload")
    return f"Removed {path} and stopped {UNIT_NAME}."


def service_action(action: str) -> subprocess.CompletedProcess:
    return _systemctl(action, UNIT_NAME)


def service_status_text() -> str:
    result = _systemctl("status", UNIT_NAME, "--no-pager", "--lines=12")
    return (result.stdout or "") + (result.stderr or "")


def service_logs(follow: bool = False) -> int:
    command = ["journalctl", "--user", "-u", UNIT_NAME, "--no-pager", "-n", "100"]
    if follow:
        command.append("-f")
    return subprocess.call(command)


# ------------------------------------------------------------------------- CLI


def run_foreground(
    *,
    poll_seconds: float | None = None,
    scan_seconds: float | None = None,
    allow_audio: bool = True,
    notifications: bool = True,
) -> int:
    daemon = AutoConnectDaemon(
        poll_seconds=poll_seconds,
        scan_seconds=scan_seconds,
        allow_audio=allow_audio,
        notifications=notifications,
    )
    return daemon.run_foreground()


def run_once(
    *,
    scan_seconds: float | None = None,
    allow_audio: bool = True,
    notifications: bool = True,
    notifier: NotifyCallable | None = None,
) -> list[CycleResult]:
    daemon = AutoConnectDaemon(
        scan_seconds=scan_seconds,
        allow_audio=allow_audio,
        notifications=notifications,
        notifier=notifier,
    )
    return daemon.run_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bconn-daemon",
        description="BConn auto-reconnect daemon (normally run by systemd --user).",
    )
    parser.add_argument("--poll", type=float, help="seconds between reconnect passes")
    parser.add_argument("--scan", type=float, help="scan duration for absent devices")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--no-audio", action="store_true", help="do not route audio")
    parser.add_argument("--no-notify", action="store_true", help="do not show notifications")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version="bconn-daemon 0.1.0")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.once:
        daemon = AutoConnectDaemon(
            scan_seconds=args.scan,
            allow_audio=not args.no_audio,
            notifications=not args.no_notify,
        )
        results = daemon.run_once()
        if not results:
            print("nothing to do")
        for result in results:
            print(result)
        return 0

    return run_foreground(
        poll_seconds=args.poll,
        scan_seconds=args.scan,
        allow_audio=not args.no_audio,
        notifications=not args.no_notify,
    )


if __name__ == "__main__":
    sys.exit(main())
