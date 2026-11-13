# BConn

**A tray-first Bluetooth companion for Linux.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

BConn makes connecting Bluetooth earbuds, speakers, keyboards, and phones a
one-click action instead of a `bluetoothctl` ritual. It lives in the system
tray, remembers the devices you use, auto-reconnects the ones you opt in to,
routes audio through PipeWire, and explains failures with a concrete fix
instead of a bare `org.bluez.Error.Failed`.

Built for **Kali Linux + XFCE**, and expected to work on any BlueZ + GTK 3
desktop. No root required at runtime.

- **CLI first:** `bconn connect buds` works from a terminal, keybind, or script.
- **Tray GUI:** scan window, one-click connect, battery, filters, pairing dialogs.
- **Opt-in auto-reconnect:** a `systemd --user` daemon covers the tray-not-running
  case. Manual disconnects are respected.
- **Audio aware:** finds the matching PipeWire sink by Bluetooth MAC and makes it
  the default output.
- **Actionable diagnostics:** `bconn doctor` checks the whole stack and prints the
  exact fix command.

**Jump to:** [Install](#installation) · [Quick start](#quick-start) ·
[Tray app](#tray-app) · [Auto-reconnect](#auto-reconnect-daemon) ·
[Configuration](#configuration-and-files) · [Troubleshooting](#troubleshooting) ·
[Development](#development) · [Docs](#project-docs)

## Features

| Area | What you get |
|---|---|
| Connection | Pair → trust → connect as one verified transaction, with discovery stopped first |
| Pairing | Real BlueZ agent: confirmation, passkey, PIN, display, authorization |
| CLI | `list`, `scan`, `pair`, `connect`, `disconnect`, `forget`, `power`, `audio`, `auto`, `info`, `doctor`, `daemon`, `shortcut` |
| GUI | Tray menu, scan window, search/filter, per-device menus, details, preferences |
| Auto-reconnect | Opt-in per device, 30s poll, exponential backoff (15s → 300s), one-shot failure notice |
| Audio | PipeWire sink discovery via `pw-dump` and default routing via `wpctl` |
| Desktop | Application-menu shortcut with a bundled icon |
| Diagnostics | Read-only doctor for service, rfkill, adapter, audio stack, GUI deps, tray, notifications |

## Requirements

| Component | Why | Debian / Kali / Ubuntu package |
|---|---|---|
| Python 3.10+ | Runtime | `python3` |
| PyGObject + Cairo | D-Bus and tray rendering | `python3-gi`, `python3-cairo` |
| GTK 3 bindings | GUI | `gir1.2-gtk-3.0` |
| libnotify bindings | Notifications | `gir1.2-notify-0.7` |
| Ayatana AppIndicator | Tray icon | `gir1.2-ayatanaappindicator3-0.1` |
| BlueZ | Bluetooth stack | `bluez` |
| rfkill | Radio check | `rfkill` |
| PipeWire + WirePlumber | Audio routing | `pipewire-bin`, `wireplumber` |
| desktop-file-utils | Menu cache refresh (optional) | `desktop-file-utils` |

> Package names differ on Arch/Fedora. See
> [`docs/INSTALL.md`](docs/INSTALL.md#3-dependencies-on-other-distributions).

## Installation

### The one-command install (recommended)

Once the repository is published, this single command is the whole install:

```bash
curl -fsSL https://raw.githubusercontent.com/d43m0n1z3r/bconn/main/install.sh | sudo bash
```

Working from a checkout? Clone it and run the same installer:

```bash
git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn
sudo ./install.sh
```

Either form installs and configures everything:

1. Installs the required Debian/Kali packages with `apt`.
2. Copies BConn to `/opt/bconn`.
3. Adds `bconn`, `bconn-gui`, `bconn-daemon`, `bconn-doctor`, and
   `bconn-uninstall` to `/usr/local/bin`.
4. Enables `bluetooth.service` and unblocks the radio.
5. Adds the **BConn** entry to the application menu for your desktop user.
6. Installs the opt-in auto-reconnect service for your user.

Then check the stack and start using it:

```bash
bconn doctor      # read-only health check
bconn scan        # find nearby devices
```

> No `git`? Download the repository as a ZIP, extract it, then run
> `sudo ./install.sh` from inside the extracted folder.

To remove everything later:

```bash
sudo bconn-uninstall
```

The installer is safe to run again; it replaces the installed copy in place.

### Manual installation (developers)

If you prefer to run from a checkout without installing anything system-wide:

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-cairo \
  gir1.2-gtk-3.0 \
  gir1.2-notify-0.7 \
  gir1.2-ayatanaappindicator3-0.1 \
  bluez rfkill \
  pipewire-bin wireplumber \
  desktop-file-utils

sudo systemctl enable --now bluetooth
rfkill unblock bluetooth

git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn
./bin/bconn doctor
./bin/bconn-gui --window
```

There is no build step and no virtualenv: BConn uses the system Python and the
distribution's PyGObject bindings. To use the commands without the `bin/`
prefix, add the checkout to your `PATH`:

```bash
echo 'export PATH="$PWD/bin:$PATH"' >> ~/.zshrc   # use ~/.bashrc for Bash
source ~/.zshrc
```

Full details, per-distro package names, upgrades, and manual uninstall steps
live in [`docs/INSTALL.md`](docs/INSTALL.md).

## Quick start

```bash
bconn list                     # adapter + known devices
bconn scan                     # discover nearby devices (time-boxed)
bconn pair buds --connect      # pair, trust, connect, route audio
bconn connect buds             # connect a name, alias, or MAC
bconn disconnect buds          # manual disconnect; pauses auto-reconnect
bconn audio                    # list sinks / choose the default output
bconn auto buds on             # opt in to auto-reconnect
bconn info buds                # addresses, UUIDs, battery, state
bconn doctor                   # read-only system check
```

Name matching is case-insensitive (alias, name, or exact MAC), so you never have
to memorise a MAC address. If a device is not in BlueZ's cache, `connect` and
`pair` run a short scan first.

## Tray app

```bash
bconn gui                # tray icon only
bconn gui --window       # tray icon + manager window
bconn-gui --window       # same, without the `bconn` wrapper
```

The tray menu gives you adapter power, connected devices with battery, quick
connect, scan, audio output, preferences, the system check, and quit. The scan
window adds filters, search, RSSI, and per-device actions. If no StatusNotifier
host is available, BConn falls back to a normal window.

## Auto-reconnect daemon

```bash
bconn daemon install      # write the unit, enable + start it
bconn daemon status
bconn daemon logs -f
bconn daemon restart
bconn daemon uninstall    # disable + remove the unit
bconn daemon once         # single pass, foreground (debugging)
bconn daemon run          # foreground poll loop (systemd uses this)
```

The daemon is deliberately conservative:

- Only devices with `auto_connect: true` are touched.
- Unpaired devices are skipped with a one-time "pair it once" notification.
- A manual `bconn disconnect` sets `paused: true`, so the daemon will not fight
  you. Connecting again clears it.
- Failures back off: 15s → 30s → 60s → 120s → 240s → 300s (capped).
- It polls every 30s and logs a heartbeat every 10 minutes.

## Configuration and files

| Path | Purpose |
|---|---|
| `~/.config/bconn/config.json` | Per-device opt-in, aliases, audio preference, paused state |
| `~/.local/state/bconn/state.json` | Last connected device and battery (safe to delete) |
| `~/.local/share/applications/bconn.desktop` | Application-menu shortcut |
| `~/.local/share/icons/hicolor/scalable/apps/bconn.svg` | Shortcut icon |
| `~/.config/systemd/user/bconn-daemon.service` | Generated user unit (only after `daemon install`) |

Config is plain JSON and safe to edit by hand:

```json
{
  "version": 1,
  "auto_connect": true,
  "notifications": true,
  "scan_timeout_seconds": 12,
  "devices": {
    "AA:BB:CC:DD:EE:FF": {
      "alias": "Buds",
      "auto_connect": true,
      "prefer_audio": true,
      "paused": false
    }
  }
}
```

## Troubleshooting

Start here:

```bash
bconn doctor
```

| Symptom | Fix |
|---|---|
| `bluetoothctl` hangs, no adapter | `sudo systemctl enable --now bluetooth` |
| "Radio soft-blocked" | `rfkill unblock bluetooth` |
| Adapter present but powered off | `bluetoothctl power on` (BConn does this automatically too) |
| No tray icon | Install a StatusNotifier host, or run `bconn gui --window` |
| Connected but audio stays on speakers | `wpctl status`, then `bconn audio <sink-id\|name\|mac>` |
| Daemon does not reconnect | Check `bconn auto <device>`, then `journalctl --user-unit bconn-daemon -n 50` |
| Pairing prompt never appears | Another agent (Blueman) may own the default agent; quit it and retry |

More detail: [`docs/INSTALL.md`](docs/INSTALL.md#10-troubleshooting).

## Development

```bash
git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn

# System deps are the same as above; tests also need dbus-daemon.
python3 -m unittest discover -s tests -v
```

The integration suite starts its own private `dbus-daemon` and a fake BlueZ
service in [`tests/fake_bluez.py`](tests/fake_bluez.py), so it never touches your
real Bluetooth stack and needs no hardware or root.

Run the tools straight from the checkout:

```bash
./bin/bconn --help
./bin/bconn list
./bin/bconn-gui --window
./bin/bconn-daemon --once --no-audio --no-notify
```

Architecture, module map, adding commands or tray actions, debugging D-Bus, and
the release checklist live in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Project docs

| Document | Contents |
|---|---|
| [`docs/INSTALL.md`](docs/INSTALL.md) | Full installation, dependencies per distro, upgrade, uninstall, troubleshooting |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Architecture, module map, tests, extending BConn, debugging, release checklist |
| [`docs/PLAN.md`](docs/PLAN.md) | Product and technical design, reliability model, BlueZ integration, milestones |
| [`docs/UX.md`](docs/UX.md) | Tray states, menus, scan window, interaction flows |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution guidelines and bug-report checklist |
| [`docs/PUBLISHING.md`](docs/PUBLISHING.md) | Maintainer checklist for GitHub publishing and releases |

## Status and roadmap

Implemented and verified on real hardware:

- BlueZ D-Bus core, pairing transaction, CLI, doctor.
- GTK 3 tray app with scan window, preferences, details, notifications.
- PipeWire audio routing.
- Opt-in auto-reconnect daemon and application-menu shortcut.
- **68** unit and fake-BlueZ end-to-end tests.

Planned:

- AVRCP media controls and battery in the tray.
- Audio profile selection (A2DP vs HFP).
- Multiple adapters, BLE details.
- `.deb` package, autostart entry, man page.

Non-goals: replacing Blueman's OBEX/PAN features, managing Wi-Fi/NFC, running
as root, or supporting non-Linux platforms.

## License

BConn is released under the [MIT License](LICENSE).

You can use, modify, and redistribute it, including commercially, as long as
the copyright notice and permission notice are kept.
