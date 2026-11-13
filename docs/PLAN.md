# BConn — Product & Technical Plan

> Name: **BConn**. CLI: `bconn`. Config: `~/.config/bconn/`.
> Target: Kali Linux 2026.3, XFCE, X11, BlueZ 5.87, PipeWire/WirePlumber.
>
> **Status:** phases 1–3 are implemented and verified on real hardware. OBEX
> Object Push is implemented and covered by mocked-D-Bus tests, with a
> hardware smoke test against `obexd`. This document keeps the original
> design, the reliability rules, and the roadmap.
> For installation see [`INSTALL.md`](INSTALL.md); for the codebase, tests, and
> extension points see [`DEVELOPMENT.md`](DEVELOPMENT.md); for the user-facing
> overview see the [README](../README.md).

---

## 1. Product definition

**One sentence:** a tray-first Bluetooth companion that connects the devices you
use in one click, keeps them connected, routes their audio correctly, and tells
you what is wrong when they are not.

**The core insight:** `bluetoothctl` exposes *mechanism*, not *intent*. The user
does not want to "pair a remote device and attach an A2DP profile"; they want
"my earbuds are working". BConn is an intent layer over BlueZ.

**Success looks like:**

- From boot to music playing: one click (or zero, with auto-connect).
- A failed connection produces a specific cause and a fix, never a bare `Failed`.
- The app starts in under a second and uses a few dozen MB of RAM.
- Nothing requires the user to remember a MAC address.
- The CLI is good enough that the GUI is optional.

**Non-goals:**

- Full Blueman replacement (PAN, network tethering).
- Wi-Fi/NFC/other radios.
- Kernel modules, custom firmware, or running as root.
- Cross-platform support. Linux/BlueZ only.

---

## 2. Users and scenarios

### Persona A — the daily earbuds user

Boots the laptop, puts in earbuds, wants audio in under five seconds. Cares
about auto-reconnect, battery level, and "why did it connect to the laptop
speakers instead?".

### Persona B — the tinkerer/security user

Uses Kali for work, has several devices (headset, speaker, keyboard, phone),
switches often, and is comfortable with a CLI. Cares about control, logs,
diagnostics, and not having a heavy desktop environment dependency.

### Persona C — the confused first-timer

`bluetoothctl` hangs, Blueman shows nothing, and they do not know that
`bluetoothd` is disabled. Cares about a clear error and a copy-paste fix.

### Key scenarios

1. **First pairing:** open scan window → device appears → click Pair → trusted,
   connected, audio routed.
2. **Daily reconnect:** tray → click favorite → connected in one action.
3. **Auto-reconnect:** resume from suspend → earbuds reconnect → audio restored
   → notification with battery.
4. **Manual disconnect:** user disconnects; the app does **not** immediately
   reconnect and fight them.
5. **Failure:** earbuds are still bonded to the phone; app reports "paired but
   connection refused — remove the pairing on the other device" with details.
6. **Headless use:** `bconn connect buds` from a terminal or keyboard shortcut.
7. **Broken system:** `bconn doctor` identifies the disabled service, missing
   D-Bus alias, rfkill block, or audio stack problem.

---

## 3. Reliability model

Reliability is not one feature; it is a set of rules applied consistently.

### 3.1 Failure taxonomy

| Layer | Failure | Detection | User-facing response |
|---|---|---|---|
| System | `bluetoothd` not running | `systemctl is-active` / D-Bus name missing | "Bluetooth service is off" + `sudo systemctl enable --now bluetooth` |
| System | D-Bus activation alias missing | `dbus-org.bluez.service` not found | Same fix; explain why `bluetoothctl` hangs |
| Radio | rfkill soft/hard block | `rfkill list bluetooth` | "Radio blocked" + `rfkill unblock bluetooth` / hardware switch |
| Controller | No adapter / firmware failed | no `hci*` objects | "No Bluetooth adapter found" + VM/USB passthrough hint |
| Controller | Adapter powered off | `Adapter1.Powered == false` | Power on automatically, or show toggle |
| Permissions | Access denied | D-Bus `AccessDenied` | Explain bluetooth group/polkit |
| Device | Out of range/asleep | connect timeout / `NotAvailable` | Retry with backoff, then "device not responding" |
| Device | Bonded to another host | `AuthenticationFailed` after repeated attempts | "Remove the pairing on the other device, then retry" |
| Device | Not paired/trusted | properties | Run the pair → trust → connect transaction |
| Pairing | PIN/passkey needed | Agent callbacks | Show a modal dialog with the number |
| Profile | No audio sink appears | `wpctl` lookup by MAC | "Connected, but no audio sink — check WirePlumber" |
| Audio | Sink exists, not default | `wpctl` default vs device MAC | Set default automatically |
| State | Stale BlueZ cache | `UnknownObject` / old properties | Refresh ObjectManager, retry once |
| User intent | Manual disconnect | explicit action | Mark not-wanted; do not auto-reconnect |

### 3.2 Reliability rules (non-negotiable)

1. **Stop discovery before connect.** Discovery and connection contend for the
   controller; this is one of the most common "random" failures.
2. **Pair, trust, then connect — as one transaction, with verification.** Never
   report success until `Paired`, `Trusted`, and `Connected` are observed.
3. **Wait for `ServicesResolved` before touching audio.** The sink does not
   exist until profiles are attached.
4. **Serialize connection attempts per adapter.** No parallel connects.
5. **Retry with exponential backoff, capped.** 15s, 30s, 60s, 120s, 240s,
   300s (cap). Reset on success or explicit user action.
6. **Respect manual intent.** A user disconnect disables auto-reconnect for that
   device until the user connects again.
7. **Never scan continuously.** Scanning is explicit and time-boxed; it costs
   battery and degrades audio.
8. **One source of truth.** The GUI and CLI call the same core; no shelling out
   to `bluetoothctl` and parsing text.
9. **Every async operation has a timeout.** BlueZ calls can hang; wrap them.
10. **Log the layer, not just the error.** Include adapter, device, operation,
    D-Bus error name, and retry count.

---

## 4. Scope

### 4.1 Phase 1 — core + CLI (done)

**Core**

- D-Bus client for BlueZ: adapters, devices, properties, cache refresh.
- Pairing agent with confirmation/passkey/PIN prompts (CLI first).
- Pair → trust → connect transaction.
- Explicit disconnect; remember user intent.
- Audio sink discovery by MAC and `wpctl set-default`.
- Diagnostics engine.
- Per-device **opt-in** auto-connect configuration (no daemon yet).

**CLI**

```text
bconn list                         # adapters + known devices
bconn scan [--timeout 10]          # nearby devices
bconn pair <name|mac> [--connect]
bconn connect <name|mac>
bconn disconnect <name|mac>
bconn send <name|mac> <file...>   # OBEX Object Push
bconn forget <name|mac> [--yes]
bconn power [on|off|toggle]
bconn audio [sink]                 # list/choose the default output
bconn auto [<name|mac> on|off]     # opt-in auto-connect; no args = list
bconn info <name|mac>
bconn doctor
bconn shortcut install|uninstall|status
bconn daemon status|install|uninstall|start|stop|restart|logs|run|once
bconn version
```

Name matching: case-insensitive substring on alias/name, exact MAC, or an exact
`AA:BB:CC:DD:EE:FF` / `AABBCCDDEEFF` form. Ambiguity produces a disambiguation
error, never a guess. When a device is not in the cache, `connect`/`pair` run a
short scan first, then resolve again.

### 4.2 Phase 2 — tray (done)

- Tray icon with state (off / ready / connected / scanning / error).
- Tray menu: power toggle, connected devices + battery, quick-connect list,
  scan, audio output, diagnostics, preferences, quit.
- Scan window: filter, search, RSSI, status chips, one primary action per row.
- Notifications on connect/disconnect/failure.
- First-run "system not ready" panel with the exact fix.

### 4.3 Phase 3 — background daemon (done)

- `systemd --user` service for auto-reconnect without the tray:
  `bconn daemon install` renders `~/.config/systemd/user/bconn-daemon.service`
  with an absolute `ExecStart` (and `PYTHONPATH` when run from the repo), then
  runs `systemctl --user enable --now`.
- The tray can run standalone **or** alongside the daemon; both modes work.
- Only devices with `auto_connect: true` and `paused: false` are touched.
- Unpaired devices are skipped with a one-time "pair it once" notification.
- Failures back off exponentially (15s → 30s → 60s → 120s → 240s → 300s).
- A manual `bconn disconnect` sets `paused: true`, so the daemon will not fight
  the user; connecting again clears it.
- `bconn daemon once` runs a single pass for debugging; `logs -f` follows the
  journal. The implementation lives in `bconn/daemon.py` with a thin launcher
  at `bin/bconn-daemon`.
- Future: logind `PrepareForSleep` resume hook (the poll loop already covers
  the common case within one 30s cycle).

### 4.4 OBEX Object Push (done)

- Device classification uses BlueZ `Icon`, service UUIDs, and the Bluetooth
  Class of Device major and minor classes, so phones, tablets, laptops,
  desktops, watches, input devices, imaging devices, and wearables are all
  recognised. Phones that also advertise A2DP/HFP audio profiles are still
  classified as phones. The scan window has Audio, Input, Phone, and Other
  filters.
- `bconn send <device> <file...>` and the tray/row-menu **Send file…** action
  send files with `org.bluez.obex` Object Push. BConn pairs on demand, creates
  one OPP session per batch, reports progress, and removes the session.
- `obexd` is a per-user service on the session bus. Missing it produces a
  specific error with `systemctl --user start obex.service`.
- The auto-reconnect daemon skips its own scan while another client owns
  discovery, so it cannot cut a GUI scan short.
- Receiving files (discoverable/pairable toggles), PBAP, and PAN remain out of
  scope for now.

### 4.5 Later

- Battery in tray menu and notifications.
- AVRCP media controls (play/pause/next/previous).
- Audio profile selection (A2DP vs HFP) with a warning that HFP lowers quality.
- Adapter selection for multi-adapter systems.
- Import/cleanup of stale BlueZ pairings.
- `.deb` package, `.desktop` entry, icon, autostart, man page.

---

## 5. Architecture

### 5.1 Stack decision

| Option | Verdict | Why |
|---|---|---|
| **Python 3 + GTK 3 + PyGObject** | **Chosen** | Already installed; native XFCE look; fast to iterate; Gio gives async D-Bus |
| Python + Qt/PySide | Rejected for now | Not installed; heavier dependency |
| C + GTK 3 | Rejected | More code and memory-safety risk for a small tool |
| Electron/Tauri | Rejected | Node/Rust absent; 100MB+ for a tray icon |
| Shell scripts around `bluetoothctl` | Rejected | Fragile parsing, slow, no signals, exactly the pain being solved |
| existing Blueman | Not reused | Installed but heavyweight and still leaves the system service broken; we want a focused UX |

**D-Bus library:** `Gio.DBusProxy` / `Gio.DBusConnection` (PyGObject). It is
async, integrates with the GLib main loop, and needs no extra package. `dbus-
python` is installed but blocking; we avoid it.

**Tray:** `AyatanaAppIndicator3`. If no StatusNotifier host is available, BConn
falls back to a normal window rather than silently disappearing.

**Notifications:** libnotify via GI (`Notify` typelib). Notifications are
best-effort: a failure never breaks a connection.

**Audio:** `pw-dump` for structured JSON state and `wpctl set-default` for the
change (PipeWire/WirePlumber is the active stack; `pactl` is not required).
Match sinks by `api.bluez5.address` (with the `bluez_output.*` node name as a
fallback). Both the CLI and the GUI call the same `audio.py` helpers, which use
`subprocess` with short timeouts.

**Persistence:** JSON files (user config + runtime state), atomic writes.

### 5.2 Process model

```text
┌──────────────────────────────┐      ┌──────────────────────────────┐
│ bconn (CLI)                  │      │ bconn-gui (Gtk.Application)  │
│  argparse ──► transaction    │      │  tray indicator + menu       │
│       │                      │      │  scan window + dialogs       │
│       └──► bluez.py          │      │       │                      │
└──────────────┬───────────────┘      └───────┬──────────────────────┘
               │                              │
               ▼                              ▼
        ┌──────────────────────────────────────────────┐
        │ BConn core (no GTK imports)                  │
        │  bluez.py ── GDBus ── org.bluez (system bus) │
        │  agent.py ── exported org.bluez.Agent1       │
        │  transaction.py ── pair/trust/connect        │
        │  audio.py ── pw-dump / wpctl                 │
        │  config.py ── JSON config + state            │
        └──────────────────────────────────────────────┘
                       ▲
                       │  same core, no dialogs
        ┌──────────────┴───────────────┐
        │ bconn-daemon (systemd --user)│
        │  poll loop + backoff         │
        └──────────────────────────────┘
```

- The CLI is short-lived and calls the core directly; no IPC is needed.
- The GUI is a single `Gtk.Application` instance (application ID
  `org.bconn.Bconn`). A second launch activates the running instance, so
  `bconn-gui --window` raises the existing window.
- The daemon is a separate `systemd --user` service. It calls the same core with
  `prompter=None`, so it can never pop a dialog.
- All BlueZ work stays on the GLib main loop or inside bounded `subprocess`
  calls; there is no thread pool.

### 5.3 Module layout

```text
bconn/
├── __init__.py          # version
├── __main__.py          # python -m bconn
├── cli.py               # argparse commands and output formatting
├── config.py            # config + state load/save, atomic writes
├── bluez.py             # object manager, proxies, models, error mapping
├── obex.py              # OBEX Object Push client (session bus)
├── agent.py             # org.bluez.Agent1 implementation
├── transaction.py       # pair → trust → connect orchestration
├── daemon.py            # poll loop, backoff, systemd unit management
├── shortcut.py          # application-menu shortcut + icon writer
├── audio.py             # wpctl/pw-dump sink discovery + routing
├── errors.py            # user-facing error translation
└── ui/
    ├── __init__.py      # GUI entry point, activation
    ├── app.py           # Gtk.Application, tray menu, operations
    ├── scan_window.py   # device list, filters, search, row actions
    ├── model.py         # pure presentation helpers (no GTK)
    ├── icons.py         # generated tray state icons
    ├── pairing.py       # GTK pairing dialogs / prompter
    ├── preferences.py   # settings window
    ├── details.py       # device details dialog
    ├── doctor.py        # system-check window
    └── notifications.py # libnotify wrapper
```

The read-only terminal diagnostic lives outside the package at
`bin/bconn-doctor`; the GUI runs the same script.

### 5.4 Data flow: connect a device

```text
UI/CLI
  │ connect("buds")
  ▼
TransactionManager
  │ 1. resolve device in cache
  │ 2. stop discovery
  │ 3. pair if !Paired (agent may prompt)
  │ 4. set Trusted=true
  │ 5. Connect()
  │ 6. wait: Connected && ServicesResolved (timeout 25s)
  │ 7. AudioRouter.ensure_default(device.address)
  │ 8. update state, notify
  ▼
BlueZ D-Bus / PipeWire
```

---

## 6. BlueZ integration blueprint

### 6.1 Objects and interfaces

Service: `org.bluez` on the **system bus**.

| Object | Interface | Use |
|---|---|---|
| `/` | `org.freedesktop.DBus.ObjectManager` | `GetManagedObjects`, `InterfacesAdded/Removed` |
| `/org/bluez/hciX` | `org.bluez.Adapter1` | power, discovery, filter, remove device |
| `/org/bluez/hciX/dev_AA_BB_...` | `org.bluez.Device1` | pair, connect, trust, properties |
| same | `org.bluez.Battery1` | percentage (when available) |
| same | `org.bluez.MediaPlayer1` | AVRCP controls (v0.2) |
| `/org/bconn/agent` | `org.bluez.Agent1` | pairing callbacks |
| `/org/bluez` | `org.bluez.AgentManager1` | register/unregister agent |

Device lookup by MAC: BlueZ path uses uppercase MAC with `:` → `_`
(`dev_AA_BB_CC_DD_EE_FF`). Do not construct paths blindly; resolve through the
ObjectManager cache.

### 6.2 Adapter startup

1. Get managed objects.
2. Pick the configured adapter, else the first `Adapter1`.
3. If `Powered == false`, set it true (with a clear error if it fails).
4. Set `Pairable` only during pairing; leave `Discoverable` off.
5. Register the pairing agent once, request default agent.
6. Subscribe to `PropertiesChanged` and `InterfacesAdded/Removed`.

### 6.3 Discovery

```text
SetDiscoveryFilter({
  "Transport": "auto",
  "DuplicateData": false,
  "RSSI": -85
})
StartDiscovery()
```

- Time-box to 10–15 seconds (configurable), with a visible countdown.
- `StopDiscovery()` on window close, on connect, and on app quit.
- Merge results into the device cache; sort by RSSI, then connected, then name.
- Do not show blocked devices by default.
- Handle `org.bluez.Error.InProgress` (already discovering) as success.

### 6.4 Pairing transaction

```text
register agent (once)
if !device.Paired:
    StopDiscovery()
    device.Pair()                      # timeout 30s
    wait for Paired == true
if !device.Trusted:
    set Trusted = true
device.Connect()                       # timeout 25s
wait for Connected == true
wait for ServicesResolved == true      # timeout 10s
route audio
```

**Agent capability:** start with `KeyboardDisplay`. Implement:

- `RequestConfirmation` → modal "Confirm code 123456 on the device" → Accept/Reject.
- `RequestPasskey` → numeric entry dialog (6 digits).
- `DisplayPasskey` / `DisplayPinCode` → show code while the user types it.
- `RequestAuthorization` / `AuthorizeService` → allow only during an active,
  user-initiated pairing session.
- `Cancel` → close dialogs, fail the transaction cleanly.

Never auto-accept a pairing that the user did not initiate. Auto-accepting every
incoming request is a security hole.

### 6.5 Error mapping

| D-Bus error | Meaning | Action |
|---|---|---|
| `org.bluez.Error.AlreadyConnected` | already connected | treat as success |
| `org.bluez.Error.InProgress` | operation pending | wait, then retry once |
| `org.bluez.Error.NotReady` | adapter off/not ready | power on, retry |
| `org.bluez.Error.NotAvailable` | device absent | wait for presence, backoff |
| `org.bluez.Error.AuthenticationFailed` | bad bond/keys | suggest re-pair / remove other host pairing |
| `org.bluez.Error.AuthenticationCanceled` | user/device cancelled | clean cancel, no retry storm |
| `org.bluez.Error.AuthenticationTimeout` | pairing timed out | retry once, then explain |
| `org.bluez.Error.AuthenticationRejected` | rejected | show reason, stop |
| `org.bluez.Error.Failed` | generic | inspect stage; usually discovery/profile/audio |
| `org.freedesktop.DBus.Error.AccessDenied` | permissions/polkit | explain, link doctor |
| timeout | device asleep/out of range | backoff, then "not responding" |

### 6.6 Stale cache and removal

- BlueZ keeps device objects after they disappear. Do not treat presence in the
  cache as "in range".
- `RemoveDevice` (forget) removes the bond; confirm with the user.
- On `UnknownObject`, refresh the ObjectManager once and retry the operation.

---

## 7. Auto-reconnect state machine

Per device, the intent is stored in the config and the retry state is in memory:

```text
auto_connect: bool      # opt-in; nothing reconnects without this
paused:       bool      # set by a manual disconnect; cleared by manual connect
attempts:     int       # runtime only
next_try:     timestamp # runtime only
```

Implemented behavior (`bconn/daemon.py`):

1. The daemon polls every 30 seconds (`BCONN_POLL_SECONDS` overrides it for
   development). There is no logind hook yet; a resume is picked up by the next
   poll, which is within one cycle.
2. `Config.opted_in_devices()` filters to `auto_connect: true`, `paused: false`,
   with the master `auto_connect` switch on.
3. If a wanted device is not in BlueZ's cache, the daemon runs a time-boxed scan,
   at most once per 90 seconds.
4. Unpaired devices are skipped. The user is notified once to pair them from the
   tray or CLI.
5. Already-connected devices are a no-op.
6. Failed attempts back off: 15s → 30s → 60s → 120s → 240s → 300s (cap).
   One failure notification is sent per device, not one per attempt.
7. Success clears the attempt state and records `last_connected`/battery.
8. Every 10 minutes the daemon logs a heartbeat so `journalctl` shows the loop is
   alive without a line every 30 seconds.

Intent rules:

- **Auto-connect is opt-in per device.** `bconn auto <device> on` (or the tray
  toggle) is the only thing that enables it.
- Explicit connect clears `paused`, resets backoff, and does **not** change
  `auto_connect`.
- Explicit disconnect sets `paused=true`. The daemon never reconnects a device
  the user just disconnected.
- Adapter power off pauses attempts; power on resumes them on the next poll.
- `auto_connect` and `paused` are persisted; attempts and timers are runtime
  only and reset when the service restarts.

The daemon does not run continuous inquiry. It scans only when a wanted device
is absent from the cache, and never more than once per 90 seconds.

---

## 8. Audio routing

After `ServicesResolved`, within a 10-second window:

1. Read PipeWire state with `pw-dump` (structured JSON) and keep only
   `media.class == "Audio/Sink"` nodes.
2. For each sink ID, `wpctl inspect <id>` and look for
   `api.bluez5.address = "AA:BB:..."`.
3. If a sink matches the device MAC:
   - Prefer profile `a2dp-sink` if the card exposes it.
   - `wpctl set-default <sink-id>`.
   - Verify by reading the default sink.
4. If none appears:
   - Retry for up to 10s (PipeWire may lag).
   - If still missing, report "Connected but no audio sink" with checks:
     WirePlumber running, `bluez5` plugin loaded, profile not `off`, codec
     support.
5. If several audio devices are connected:
   - Default policy: last explicitly selected wins.
   - Optional "one audio device at a time" setting disconnects the previous one.

Out of scope for MVP: automatic A2DP↔HFP switching when the mic is used. It is
invasive and device-dependent; expose a manual profile choice in v0.2.

---

## 9. Configuration and state

`~/.config/bconn/config.json` (user intent, hand-editable):

```json
{
  "version": 1,
  "adapter": null,
  "auto_connect": true,
  "connect_on_start": true,
  "one_audio_device": false,
  "notifications": true,
  "scan_timeout_seconds": 12,
  "devices": {
    "AA:BB:CC:DD:EE:FF": {
      "alias": "Buds",
      "auto_connect": false,
      "prefer_audio": true,
      "paused": false,
      "forget_on_disconnect": false
    }
  }
}
```

The top-level `auto_connect` is the master switch for the feature. Each device
defaults to `auto_connect: false` (opt-in); even when it is true, nothing
reconnects if the master switch is off.

`~/.local/state/bconn/state.json` (runtime only, safe to delete):

```json
{
  "last_device": "AA:BB:CC:DD:EE:FF",
  "devices": {
    "AA:BB:CC:DD:EE:FF": {
      "last_connected": "2026-11-09T14:30:00Z",
      "last_battery": 82
    }
  }
}
```

Rules: atomic write (temp + rename), tolerate corrupt files (backup + defaults),
never store PINs or secrets. MAC addresses are not sensitive but should not be
sent anywhere.

---

## 10. Diagnostics

`bconn doctor` runs the read-only shell script `bin/bconn-doctor`; the GUI's
"System check" window runs the same script and renders its output. There is one
implementation, so terminal and GUI cannot disagree.

Checks:

1. OS/session/desktop, BlueZ version.
2. `bluetooth.service` active **and** enabled.
3. `dbus-org.bluez.service` alias present (D-Bus activation works).
4. rfkill soft/hard block and kernel module.
5. Adapter present and powered; discovery state.
6. PipeWire, WirePlumber, and `pipewire-pulse`; `wpctl` present.
7. BlueZ sinks/cards visible in PipeWire.
8. Python/GTK/AppIndicator/Notify dependencies.
9. `bluetooth` group membership.
10. StatusNotifier host and notification daemon.
11. Config directory writable.
12. Running as a normal user, not root.

Output contract: every failure has (a) what is wrong, (b) why it matters, (c)
a copy-paste command or GUI action. Exit code 0 = healthy, 1 = at least one
blocking failure, 2 = warnings only.

`bconn doctor --json` and connection-history diagnostics are future work.

---

## 11. UX contract

See [`UX.md`](UX.md) for wireframes. Key rules:

- **Tray-first.** Opening a full window is the slow path, not the default.
- **One primary action per device row.** Pair, Connect, or Disconnect; never a
  menu of five verbs.
- **Show state, not jargon.** "Connected · audio on", not "A2DP sink attached".
- **Failure is a screen, not a toast.** Errors get a cause, a fix button, and a
  details expander.
- **No modal dialogs for routine success.** Connect silently, then notify.
- **Keyboard:** Ctrl+F search, Enter connect, Space scan toggle, Esc close.
- **Latency budget:** tray menu opens <100ms; connect attempt starts <200ms;
  window first paint <300ms.

---

## 12. Milestones

Status: M0–M6 done on real hardware. A one-command installer and uninstaller
exist (`sudo ./install.sh`, `sudo bconn-uninstall`); `.deb` packaging and a man
page remain.

### M0 — Groundwork (done)

- Environment audit, doctor script, product/technical plan, UX spec.
- **Acceptance:** `bin/bconn-doctor` accurately reports the disabled service and
  the missing D-Bus alias.

### M1 — BlueZ core + read-only CLI

- ObjectManager cache, adapter/device models, property signals, logging.
- `bconn list`, `bconn power`, `bconn doctor`.
- Error mapping skeleton.
- **Acceptance:** lists adapter and known devices; survives service restart;
  `power off/on` works; no UI.

### M2 — Pairing and connection transaction

- Agent with confirmation/passkey dialogs (CLI prompts first).
- `pair`, `connect`, `disconnect`; stop-discovery rule; timeouts; retries.
- **Acceptance:** fresh earbuds pair and connect from CLI; a failed attempt
  produces a specific error; manual disconnect is respected.

### M3 — Audio routing

- `wpctl` sink discovery by MAC, default sink selection, verification, retries.
- Wire into connect transaction and doctor.
- **Acceptance:** after connect, audio plays through the device without opening
  a settings app; failure is reported with a reason.

### M4 — Tray app and scan window

- Gtk.Application, indicator, menu, scan window, notifications, first-run check.
- **Acceptance:** full first pairing and daily reconnect from the GUI; menu
  state stays correct across device events; no blocking UI.

### M5 — Auto-reconnect and resume

- Opt-in (`auto_connect`) gating, serialized attempts, backoff, power events,
  persistence, and a `systemd --user` poll loop (30s) that covers resume.
- A dedicated logind `PrepareForSleep` hook is future work; the poll loop picks
  up a resume within one cycle.
- **Acceptance:** opted-in earbuds reconnect after reboot and resume; devices
  that were not opted in never auto-connect; manual disconnect is not
  overridden; a failed device does not spin the CPU or radio.

### M6 — Packaging

- `systemd --user` daemon (both modes: tray standalone or tray + daemon) — **done**
  (`bconn daemon install`).
- Application-menu shortcut + icon — **done** (`bconn shortcut install`).
- One-command installer — **done** (`sudo ./install.sh`): apt packages,
  `/opt/bconn`, `/usr/local/bin` launchers, Bluetooth service, per-user shortcut
  and daemon, and `bconn-uninstall`.
- Optional `.deb` and a man page — remaining.
- **Acceptance:** clean install on a fresh Kali XFCE VM; tray-only and
  daemon-backed auto-reconnect both work; uninstall leaves no services behind;
  `bconn doctor` passes on a healthy system.

---

## 13. Test strategy

**Unit (`unittest`, stdlib):**

- Error mapping table (`tests/test_errors.py`).
- BlueZ model/parsing helpers, including Class-of-Device classification
  (`tests/test_bluez.py`).
- Scan-window filters and search (`tests/test_model.py`).
- Config load/save, corruption recovery, atomic write (`tests/test_config.py`).
- Name resolution (`tests/test_resolve.py`).
- `wpctl` output parsing and MAC→sink matching (`tests/test_audio.py`).
- Daemon backoff, unit rendering, notification gating, and the discovery-owner
  guard (`tests/test_daemon.py`).
- OBEX session/file-send orchestration with mocked D-Bus
  (`tests/test_obex.py`).
- Shortcut rendering and install/uninstall (`tests/test_shortcut.py`).

**Integration:**

- Fake BlueZ service (`tests/fake_bluez.py`) on a private `dbus-daemon`;
  end-to-end CLI/daemon tests cover list/scan/pair/connect/disconnect/forget/
  power/auto plus the daemon's opt-in, paused, disabled, and unpaired paths.
- The fake is test-only and never touches the real Bluetooth stack.
- No hardware, no root, and no real adapter are required.

Current total: **113 tests**.

**Manual hardware matrix:**

| Device class | Cases |
|---|---|
| Earbuds | A2DP + HFP, battery, auto-reconnect, bonded to phone |
| Speaker | A2DP, aux, long idle |
| Keyboard/mouse | passkey pairing, reconnect, LE |
| Phone | pairing, profile negotiation |
| BLE sensor | discovery, GATT properties shown but not managed |
| Dual-boot | key mismatch and repair flow |

**Soak tests (manual):** repeated connect/disconnect cycles; suspend/resume;
service restart while the app is running; adapter off/on; out-of-range walk;
app start with no adapter.

---

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Device firmware quirks | connect succeeds but no audio | diagnostics, retry, profile check, repair action |
| BlueZ auto-reconnect is device-dependent | not truly zero-click | daemon retries on startup/resume; document limits |
| Dual-boot pairing keys | persistent auth failures | detect and explain; "forget and re-pair" flow |
| PipeWire `wpctl` output changes | routing breaks | isolate parser, version check, test fixtures |
| XFCE has no StatusNotifier host | no tray icon | fall back to a normal window and document the panel plugin |
| Pairing agent UI complexity | pairing flows incomplete | CLI prompts first; GTK dialogs for passkey/PIN/confirmation |
| Kali disables Bluetooth by default | app appears broken to new users | first-run check + copy-paste fix |
| VM without USB passthrough | no adapter | detect and explain |
| D-Bus API changes | breakage on upgrades | pin behavior to BlueZ 5.x, isolate in `bluez.py` |
| Aggressive retries | battery drain, audio stutter | serialized backoff, scans at most every 90s |

---

## 15. Decisions and remaining questions

**Decided**

1. **Name/CLI:** BConn / `bconn`; config in `~/.config/bconn/`.
2. **Build order:** core + CLI first, then tray, then daemon.
3. **Auto-connect:** opt-in per device; connecting once does not enable it.
4. **Background mode:** both — tray can run standalone, and a
   `systemd --user` daemon covers the tray-not-running case.
5. **First-run behavior:** the GUI starts tray-only by default; `--window`
   opens the manager, and the window is the fallback when no tray is available.
6. **Audio policy:** connecting an audio device switches the default sink but
   leaves other devices connected. `one_audio_device: true` opts into
   disconnecting the previous audio device.
7. **Packaging:** `sudo ./install.sh` is the supported install (apt packages,
   `/opt/bconn`, `/usr/local/bin` launchers, per-user desktop integration).
   `.deb` packaging remains future work; pipx installs from the checkout are
   supported.
8. **Daemon IPC:** none. The daemon is a separate service that calls the same
   core directly; there is no custom D-Bus control interface.
9. **Application shortcut:** generated per user by `bconn shortcut install`
   (`.desktop` + bundled SVG icon), not shipped system-wide.
10. **License:** MIT. See [`LICENSE`](../LICENSE).

**Still open**

1. **Media controls:** AVRCP play/pause/next and richer battery display.
2. **Resume hook:** logind `PrepareForSleep` for immediate reconnect instead of
   waiting for the next 30s poll.
3. **Packaging:** `.deb`, man page, optional autostart entry.

---

## 16. Repository layout

```text
bt/
├── README.md               # install + quick start + project overview
├── CONTRIBUTING.md         # contribution guidelines
├── install.sh              # one-command installer + uninstaller
├── LICENSE                 # MIT
├── docs/
│   ├── INSTALL.md          # full install, upgrade, uninstall, troubleshooting
│   ├── DEVELOPMENT.md      # architecture, tests, extending, release checklist
│   ├── PUBLISHING.md       # maintainer checklist for GitHub releases
│   ├── PLAN.md             # this document
│   └── UX.md               # interface and interaction flows
├── bin/
│   ├── bconn               # CLI launcher (repo checkout)
│   ├── bconn-gui           # tray/GUI launcher
│   ├── bconn-daemon        # daemon launcher
│   └── bconn-doctor        # read-only bash diagnostic
├── bconn/
│   ├── __init__.py         # version
│   ├── __main__.py         # python -m bconn
│   ├── cli.py              # argparse commands + output
│   ├── config.py           # config + state stores
│   ├── bluez.py            # D-Bus client + models
│   ├── agent.py            # pairing agent
│   ├── transaction.py      # pair/trust/connect orchestration
│   ├── audio.py            # PipeWire sink discovery/routing
│   ├── daemon.py           # poll loop + systemd unit management
│   ├── shortcut.py         # .desktop + icon installer
│   ├── errors.py           # error translation
│   └── ui/                 # GTK 3 tray, window, dialogs
├── tests/                  # unit + fake-BlueZ integration
└── pyproject.toml          # metadata + console-script entry points
```

There is no top-level `data/` directory: the shortcut icon is embedded in
`bconn/shortcut.py`, so installation works from a plain checkout.
