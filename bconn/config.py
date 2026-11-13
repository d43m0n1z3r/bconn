"""Configuration and runtime state stored as small JSON files."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "bconn" / "config.json"


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "bconn" / "state.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "adapter": None,
    "auto_connect": True,
    "connect_on_start": True,
    "one_audio_device": False,
    "notifications": True,
    "scan_timeout_seconds": 12,
    "devices": {},
}

DEVICE_DEFAULTS: dict[str, Any] = {
    "alias": None,
    "auto_connect": False,
    "prefer_audio": True,
    "paused": False,
    "forget_on_disconnect": False,
}

DEFAULT_STATE: dict[str, Any] = {
    "last_device": None,
    "devices": {},
}


class JsonStore:
    """Load/save a JSON file atomically, tolerating corruption."""

    defaults: dict[str, Any] = {}

    def __init__(self, path: Path | None = None):
        self.path = path or self.default_path()
        self.warnings: list[str] = []
        self.data = self._load()

    def default_path(self) -> Path:  # pragma: no cover - overridden
        raise NotImplementedError

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._normalize({})
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            backup = self.path.with_name(
                f"{self.path.name}.corrupt-{int(time.time())}"
            )
            try:
                self.path.rename(backup)
                self.warnings.append(
                    f"Config was unreadable ({error}); backed up to {backup}."
                )
            except OSError:
                self.warnings.append(f"Config was unreadable ({error}).")
            return self._normalize({})

        if not isinstance(loaded, dict):
            self.warnings.append("Config root is not an object; using defaults.")
            return self._normalize({})

        return self._normalize(loaded)

    def _normalize(self, loaded: dict[str, Any]) -> dict[str, Any]:
        merged = {
            key: loaded.get(key, default) for key, default in self.defaults.items()
        }
        devices = loaded.get("devices")
        merged["devices"] = devices if isinstance(devices, dict) else {}
        return merged

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


class Config(JsonStore):
    defaults = DEFAULT_CONFIG

    def default_path(self) -> Path:
        return config_path()

    def _normalize(self, loaded: dict[str, Any]) -> dict[str, Any]:
        merged = super()._normalize(loaded)
        devices = merged["devices"]
        normalized_devices: dict[str, Any] = {}
        for address, entry in devices.items():
            if not isinstance(entry, dict):
                continue
            normalized_devices[str(address)] = {
                key: entry.get(key, default) for key, default in DEVICE_DEFAULTS.items()
            }
        merged["devices"] = normalized_devices
        return merged

    def device(self, address: str) -> dict[str, Any]:
        entry = self.data["devices"].get(address)
        if not isinstance(entry, dict):
            entry = dict(DEVICE_DEFAULTS)
            self.data["devices"][address] = entry
        else:
            for key, default in DEVICE_DEFAULTS.items():
                entry.setdefault(key, default)
        return entry

    def set_auto_connect(self, address: str, enabled: bool) -> None:
        entry = self.device(address)
        entry["auto_connect"] = enabled
        if enabled:
            entry["paused"] = False
        self.save()

    def set_paused(self, address: str, paused: bool) -> None:
        entry = self.device(address)
        entry["paused"] = paused
        self.save()

    def set_alias(self, address: str, alias: str | None) -> None:
        entry = self.device(address)
        entry["alias"] = alias or None
        self.save()

    def forget(self, address: str) -> None:
        if address in self.data["devices"]:
            del self.data["devices"][address]
            self.save()

    def opted_in_devices(self) -> list[str]:
        if not self.data.get("auto_connect", True):
            return []
        return [
            address
            for address, entry in self.data["devices"].items()
            if entry.get("auto_connect") and not entry.get("paused")
        ]

    def auto_connect_enabled(self, address: str) -> bool:
        return address in self.opted_in_devices()


class State(JsonStore):
    defaults = DEFAULT_STATE

    def default_path(self) -> Path:
        return state_path()

    def record_connected(self, address: str) -> None:
        entry = self.data["devices"].setdefault(address, {})
        entry["last_connected"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        self.data["last_device"] = address
        self.save()

    def record_battery(self, address: str, percentage: int | None) -> None:
        if percentage is None:
            return
        entry = self.data["devices"].setdefault(address, {})
        entry["last_battery"] = int(percentage)
        self.save()

    def forget(self, address: str) -> None:
        self.data["devices"].pop(address, None)
        if self.data.get("last_device") == address:
            self.data["last_device"] = None
        self.save()
