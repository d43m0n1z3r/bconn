"""PipeWire audio routing for Bluetooth sinks.

Uses `pw-dump` for structured state and `wpctl set-default` for the change.
`pactl` is not installed on the target system.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import BconnError


class AudioRoutingError(BconnError):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(
            message,
            hint or "Check that PipeWire and WirePlumber are running (bconn doctor).",
        )


@dataclass
class Sink:
    id: int
    name: str
    description: str
    address: str | None = None
    is_default: bool = False

    @property
    def is_bluetooth(self) -> bool:
        return bool(self.address)

    @property
    def display_name(self) -> str:
        return self.description or self.name or str(self.id)


def _normalise_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", value.lower())


def _run(command: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise AudioRoutingError(
            f"'{command[0]}' is not installed.",
            "Install pipewire-bin / wireplumber.",
        ) from error
    except subprocess.TimeoutExpired as error:
        raise AudioRoutingError(
            f"'{command[0]}' did not respond within {timeout:g}s.",
            "Restart PipeWire: systemctl --user restart pipewire wireplumber",
        ) from error


def parse_snapshot(data: Iterable[dict[str, Any]]) -> list[Sink]:
    sinks: list[Sink] = []
    default_name: str | None = None

    for obj in data:
        obj_type = obj.get("type")
        if obj_type == "PipeWire:Interface:Node":
            props = (obj.get("info") or {}).get("props") or {}
            if props.get("media.class") != "Audio/Sink":
                continue
            name = str(props.get("node.name", ""))
            address = props.get("api.bluez5.address")
            if not address:
                match = re.match(r"bluez_output\.([0-9A-Fa-f_]+)\.", name)
                if match:
                    address = match.group(1).replace("_", ":")
            sinks.append(
                Sink(
                    id=int(obj.get("id", 0)),
                    name=name,
                    description=str(
                        props.get("node.description") or props.get("node.nick") or name
                    ),
                    address=str(address) if address else None,
                )
            )

        elif obj_type == "PipeWire:Interface:Metadata":
            props = obj.get("props") or {}
            if props.get("metadata.name") != "default":
                continue
            for entry in obj.get("metadata") or ():
                if entry.get("key") != "default.audio.sink":
                    continue
                value = entry.get("value")
                if isinstance(value, dict):
                    default_name = value.get("name")
                elif isinstance(value, str):
                    default_name = value

    if default_name:
        for sink in sinks:
            sink.is_default = sink.name == default_name

    return sinks


def list_sinks() -> list[Sink]:
    result = _run(["pw-dump"])
    if result.returncode != 0:
        raise AudioRoutingError(
            "Could not read PipeWire state.",
            (result.stderr or "Is PipeWire running?").strip(),
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AudioRoutingError(f"PipeWire returned invalid JSON: {error}") from error
    return parse_snapshot(data)


def default_sink(sinks: Iterable[Sink] | None = None) -> Sink | None:
    sink_list = list(sinks) if sinks is not None else list_sinks()
    return next((sink for sink in sink_list if sink.is_default), None)


def find_sink_for_address(
    sinks: Iterable[Sink], address: str
) -> Sink | None:
    key = _normalise_mac(address)
    for sink in sinks:
        if sink.address and _normalise_mac(sink.address) == key:
            return sink
        if key and key in _normalise_mac(sink.name):
            return sink
    return None


def select_sink(sinks: Iterable[Sink], query: str) -> Sink:
    sink_list = list(sinks)
    query = query.strip()
    if not query:
        raise AudioRoutingError("No audio sink specified.")

    if query.isdigit():
        match = next((sink for sink in sink_list if sink.id == int(query)), None)
        if match:
            return match

    lowered = query.lower()
    if re.fullmatch(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|[0-9a-f]{12}", lowered):
        key = _normalise_mac(lowered)
        for sink in sink_list:
            if sink.address and _normalise_mac(sink.address) == key:
                return sink

    exact = [
        sink
        for sink in sink_list
        if lowered
        in {
            sink.name.lower(),
            sink.description.lower(),
            (sink.address or "").lower(),
        }
    ]
    if len(exact) == 1:
        return exact[0]

    matches = [
        sink
        for sink in sink_list
        if lowered in sink.name.lower()
        or lowered in sink.description.lower()
        or lowered in (sink.address or "").lower()
    ]
    if not matches:
        raise AudioRoutingError(
            f"No audio sink matches '{query}'.",
            "Run 'bconn audio' to list available sinks.",
        )
    if len(matches) > 1:
        names = ", ".join(f"{sink.display_name} ({sink.id})" for sink in matches)
        raise AudioRoutingError(
            f"'{query}' matches more than one sink: {names}.",
            "Use the sink ID or a longer name.",
        )
    return matches[0]


def set_default(sink: Sink, verify_timeout: float = 5.0) -> Sink:
    result = _run(["wpctl", "set-default", str(sink.id)])
    if result.returncode != 0:
        raise AudioRoutingError(
            f"Could not make '{sink.display_name}' the default sink.",
            (result.stderr or "Check wpctl/PipeWire.").strip(),
        )

    deadline = time.monotonic() + verify_timeout
    while time.monotonic() < deadline:
        current = default_sink()
        if current and current.id == sink.id:
            return current
        time.sleep(0.25)

    raise AudioRoutingError(
        f"'{sink.display_name}' did not become the default sink.",
        "Try 'wpctl status' and 'wpctl set-default <id>' manually.",
    )


def ensure_default_for_device(address: str, timeout: float = 10.0) -> Sink:
    """Wait for a Bluetooth sink matching address, then make it default."""
    deadline = time.monotonic() + timeout
    last_sinks: list[Sink] = []
    while time.monotonic() < deadline:
        last_sinks = list_sinks()
        sink = find_sink_for_address(last_sinks, address)
        if sink is not None:
            if sink.is_default:
                return sink
            return set_default(sink)
        time.sleep(0.4)

    bluetooth_sinks = [sink for sink in last_sinks if sink.is_bluetooth]
    detail = (
        "Visible Bluetooth sinks: "
        + ", ".join(sink.display_name for sink in bluetooth_sinks)
        if bluetooth_sinks
        else "No Bluetooth sink appeared in PipeWire."
    )
    raise AudioRoutingError(
        f"No audio sink appeared for {address} within {timeout:g}s.",
        detail + " Check WirePlumber and the device's audio profile.",
    )
