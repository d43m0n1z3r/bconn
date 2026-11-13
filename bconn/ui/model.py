"""Pure presentation helpers shared by the tray and the scan window.

Keeping these free of GTK makes them easy to unit-test and lets the CLI use the
same labels when it wants to.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

FILTERS: tuple[str, ...] = ("all", "audio", "input", "phone")
FILTER_LABELS: dict[str, str] = {
    "all": "All",
    "audio": "Audio",
    "input": "Input",
    "phone": "Phone",
}

TRAY_STATES = ("off", "ready", "connected", "scanning", "attention", "error")


def device_filter(device: Any) -> str:
    """Return the filter tab a device belongs to."""
    kind = getattr(device, "kind", "other")
    if kind in {"audio", "input", "phone"}:
        return kind
    return "other"


def matches_filter(device: Any, selected: str) -> bool:
    if selected in (None, "", "all"):
        return True
    return device_filter(device) == selected


def matches_search(device: Any, query: str) -> bool:
    needle = (query or "").strip().lower()
    if not needle:
        return True
    fields = (
        getattr(device, "display_name", ""),
        getattr(device, "name", ""),
        getattr(device, "alias", ""),
        getattr(device, "address", ""),
    )
    return any(needle in (field or "").lower() for field in fields)


def device_state_rank(device: Any) -> int:
    if getattr(device, "connected", False):
        return 0
    if getattr(device, "paired", False):
        return 1
    if getattr(device, "trusted", False):
        return 2
    return 3


def sort_devices(devices: Iterable[Any], last_used: dict[str, str] | None = None) -> list[Any]:
    """Connected first, then paired, then by most recently used and signal."""
    last_used = last_used or {}

    def key(device: Any) -> tuple[int, int, int, str]:
        address = getattr(device, "address", "")
        last = last_used.get(address) or ""
        rssi = getattr(device, "rssi", None)
        return (
            device_state_rank(device),
            0 if last else 1,
            -(rssi if rssi is not None else -999),
            (getattr(device, "display_name", "") or "").lower(),
        )

    return sorted(devices, key=key)


def sort_known_devices(
    devices: Iterable[Any],
    state_devices: dict[str, Any] | None = None,
) -> list[Any]:
    state_devices = state_devices or {}

    def last_key(device: Any) -> str:
        entry = state_devices.get(getattr(device, "address", "")) or {}
        return str(entry.get("last_connected") or "")

    ordered = sorted(
        devices,
        key=lambda device: (
            device_state_rank(device),
            _negative_timestamp(last_key(device)),
            (getattr(device, "display_name", "") or "").lower(),
        ),
    )
    return ordered


def _negative_timestamp(value: str) -> int:
    """Sort newest first inside a stable ascending key."""
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return -int(parsed.timestamp())
    except ValueError:
        return 0


def tray_state(
    adapters: Iterable[Any],
    devices: Iterable[Any],
    *,
    scanning: bool = False,
    error: bool = False,
) -> str:
    adapters = list(adapters)
    devices = list(devices)
    if error:
        return "error"
    if not adapters:
        return "attention"
    if not any(getattr(adapter, "powered", False) for adapter in adapters):
        return "off"
    if scanning:
        return "scanning"
    if any(getattr(device, "connected", False) for device in devices):
        return "connected"
    return "ready"


def tray_tooltip(
    state: str,
    devices: Iterable[Any],
    *,
    adapter_name: str | None = None,
    error: str | None = None,
) -> str:
    devices = [device for device in devices if getattr(device, "connected", False)]
    if state == "error":
        return error or "Last connection failed"
    if state == "attention":
        return "Bluetooth needs attention"
    if state == "off":
        return "Bluetooth is off"
    if state == "scanning":
        return "Scanning for devices…"
    if state == "connected" and devices:
        primary = devices[0]
        name = getattr(primary, "display_name", "Device")
        battery = getattr(primary, "battery", None)
        suffix = f" — {battery}%" if battery is not None else ""
        extra = f" (+{len(devices) - 1})" if len(devices) > 1 else ""
        return f"{name}{suffix}{extra}"
    if adapter_name:
        return f"Bluetooth ready · {adapter_name}"
    return "Bluetooth ready"


def state_label(device: Any) -> str:
    if getattr(device, "blocked", False):
        return "Blocked"
    if getattr(device, "connected", False):
        return "Connected"
    if getattr(device, "paired", False):
        return "Paired"
    if getattr(device, "trusted", False):
        return "Trusted"
    return "New"


def action_label(device: Any) -> str:
    if getattr(device, "connected", False):
        return "Disconnect"
    if getattr(device, "paired", False):
        return "Connect"
    return "Pair"


def device_icon(device: Any) -> str:
    icon = (getattr(device, "icon", "") or "").lower()
    if icon.startswith("audio-speakers"):
        return "audio-speakers"
    if icon.startswith(("audio-headset", "audio-headphones")):
        return "audio-headphones"
    if icon.startswith("audio-card"):
        return "audio-card"
    if icon.startswith("input-keyboard"):
        return "input-keyboard"
    if icon.startswith("input-mouse"):
        return "input-mouse"
    if icon.startswith("input-gaming"):
        return "input-gaming"
    if icon.startswith(("phone", "smartphone")):
        return "phone"
    if icon.startswith(("computer", "laptop")):
        return "computer"
    kind = getattr(device, "kind", "other")
    return {
        "audio": "audio-headphones",
        "input": "input-keyboard",
        "phone": "phone",
        "computer": "computer",
    }.get(kind, "bluetooth")


def rssi_bars(rssi: int | None) -> str:
    if rssi is None:
        return "—"
    if rssi >= -55:
        return "▂▄▆█"
    if rssi >= -67:
        return "▂▄▆_"
    if rssi >= -77:
        return "▂▄__"
    return "▂___"


def last_used_label(value: str | None, now: datetime | None = None) -> str:
    if not value:
        return "not used yet"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "not used yet"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - parsed).total_seconds()))
    if seconds < 60:
        return "last used just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"last used {minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"last used {hours}h ago"
    days = hours // 24
    if days < 7:
        return f"last used {days}d ago"
    weeks = days // 7
    return f"last used {weeks}w ago"


def quick_connect_devices(
    devices: Iterable[Any],
    state_devices: dict[str, Any] | None = None,
    configured_addresses: Iterable[str] | None = None,
) -> list[Any]:
    """Known devices worth offering in the tray's quick-connect list."""
    known = set(configured_addresses or ())
    state_devices = state_devices or {}
    candidates = [
        device
        for device in devices
        if not getattr(device, "connected", False)
        and (
            getattr(device, "paired", False)
            or getattr(device, "trusted", False)
            or getattr(device, "address", "") in known
            or getattr(device, "address", "") in state_devices
        )
    ]
    return sort_known_devices(candidates, state_devices)


def auto_connect_label(config_data: dict[str, Any] | None, address: str) -> str:
    config_data = config_data or {}
    pref = (config_data.get("devices") or {}).get(address) or {}
    if not config_data.get("auto_connect", True):
        return "master off"
    if not pref.get("auto_connect"):
        return "no"
    if pref.get("paused"):
        return "paused"
    return "yes"


def menu_safe(text: str) -> str:
    """Escape underscores so GTK does not treat device names as mnemonics."""
    return (text or "").replace("_", "__")
