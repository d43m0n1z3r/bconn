# Developing BConn

This guide is for working on BConn itself: running from source, understanding
the code, extending it, and testing without real Bluetooth hardware.

For installing BConn as a user, see [`INSTALL.md`](INSTALL.md). For the product
design and roadmap, see [`PLAN.md`](PLAN.md).

**Contents:** [Quick start](#1-quick-start) ·
[Repository layout](#2-repository-layout) · [Architecture](#3-architecture) ·
[Running and testing](#4-running-and-testing) ·
[Common tasks](#5-common-development-tasks) · [Debugging](#6-debugging) ·
[Code conventions](#7-code-conventions) · [Release checklist](#8-release-checklist)

---

## 1. Quick start

```bash
git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn

# Runtime dependencies (Debian/Kali/Ubuntu)
sudo apt install -y \
  python3-gi python3-cairo gir1.2-gtk-3.0 \
  gir1.2-notify-0.7 gir1.2-ayatanaappindicator3-0.1 \
  bluez rfkill bluez-obexd pipewire-bin wireplumber \
  dbus desktop-file-utils

# Run the tools straight from the checkout
./bin/bconn --version
./bin/bconn list
./bin/bconn-gui --window
./bin/bconn-daemon --once --no-audio --no-notify

# Tests
python3 -m unittest discover -s tests -v
```

There is no compilation or virtualenv step. BConn uses the system Python and
the distribution's PyGObject bindings.

To test the real installation (system files under `/opt/bconn`, launchers in
`/usr/local/bin`), run the installer:

```bash
sudo ./install.sh --no-daemon     # or without flags for the full experience
sudo ./install.sh --uninstall
```

---

## 2. Repository layout

```text
bt/
├── README.md               # install + quick start + project overview
├── CONTRIBUTING.md         # contribution guidelines
├── install.sh              # one-command installer + uninstaller
├── LICENSE                 # MIT
├── bin/
│   ├── bconn               # CLI launcher (repo checkout)
│   ├── bconn-gui           # tray/GUI launcher
│   ├── bconn-daemon        # auto-reconnect daemon launcher
│   └── bconn-doctor        # read-only bash diagnostic
├── bconn/
│   ├── __init__.py         # version
│   ├── __main__.py         # python -m bconn
│   ├── cli.py              # argparse commands + output formatting
│   ├── config.py           # Config/State JSON stores (atomic writes)
│   ├── bluez.py            # D-Bus client, Adapter/Device models, scanning
│   ├── obex.py             # OBEX Object Push client (session bus)
│   ├── agent.py            # org.bluez.Agent1 pairing agent
│   ├── transaction.py      # pair -> trust -> connect / disconnect / forget
│   ├── audio.py            # PipeWire sink discovery + default routing
│   ├── daemon.py           # poll loop, backoff, systemd unit management
│   ├── shortcut.py         # .desktop + icon installer
│   ├── errors.py           # BlueZ/D-Bus error translation
│   └── ui/
│       ├── __init__.py     # GUI entry point, single-instance activation
│       ├── app.py          # Gtk.Application, tray menu, operations
│       ├── scan_window.py  # device list, filters, search, row actions
│       ├── model.py        # pure presentation helpers (no GTK)
│       ├── icons.py        # generated tray state icons
│       ├── preferences.py  # general/devices/advanced settings
│       ├── pairing.py      # GTK pairing dialogs / prompter
│       ├── details.py      # device details dialog
│       ├── doctor.py       # GUI system-check window
│       └── notifications.py# libnotify wrapper
├── docs/
│   ├── INSTALL.md
│   ├── DEVELOPMENT.md
│   ├── PLAN.md
│   └── UX.md
├── tests/
│   ├── fake_bluez.py       # fake org.bluez service for integration tests
│   ├── test_integration_fake.py
│   └── test_*.py
└── pyproject.toml          # metadata + console-script entry points
```

Design rule: **the core does not import GTK.** `bconn/bluez.py`,
`transaction.py`, `obex.py`, `audio.py`, `config.py`, and `daemon.py` are usable
from a terminal or a service. Only `bconn/ui/*` imports GTK.

---

## 3. Architecture

```text
CLI (cli.py) ─────────────┐
Tray GUI (ui/app.py) ─────┼──► transaction.py ──► bluez.py ──► org.bluez
Daemon (daemon.py) ───────┘         │                 │
                                    │                 └── system D-Bus
                                    ├──► agent.py (pairing)
                                    ├──► audio.py (wpctl / pw-dump)
                                    └──► config.py (JSON)
```

Key behaviors:

- **Pair → trust → connect is one transaction.** `transaction.connect_device`
  stops discovery, pairs if needed, sets `Trusted`, connects, waits for
  `ServicesResolved`, then routes audio.
- **All BlueZ access is direct D-Bus.** No `bluetoothctl` output parsing.
- **Config is intent; state is runtime.** `Config` holds opt-in, alias, audio
  preference, and `paused`. `State` holds last-connected time and battery.
  Both tolerate corruption and write atomically.
- **Opt-in auto-connect.** `Config.opted_in_devices()` returns only devices with
  `auto_connect: true`, not `paused`, and only when the master switch is on.
- **Manual disconnect is final.** `bconn disconnect` sets `paused: true`; the
  daemon skips it until a manual connect clears the flag.
- **The daemon is a poll loop, not a second UI.** It connects via D-Bus, uses
  `prompter=None`, and never opens dialogs.

---

## 4. Running and testing

### Unit tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers error translation, config/state, name resolution, audio
parsing, Class-of-Device classification, scan filters, daemon
backoff/unit rendering/discovery guard, OBEX orchestration with a mocked
session bus, and shortcut generation.

### Fake BlueZ integration tests

`tests/test_integration_fake.py` starts a private `dbus-daemon` and
`tests/fake_bluez.py`, then runs the real `bin/bconn` against it. Your real
Bluetooth stack is never touched.

Requirements: `dbus-daemon` (package `dbus`) and `python3-gi`. No root, no
adapter, no pairing hardware.

Useful environment variables when writing your own probes:

```bash
export DBUS_SYSTEM_BUS_ADDRESS="unix:path=/tmp/my-test-bus"
export XDG_CONFIG_HOME="/tmp/bconn-test/config"
export XDG_STATE_HOME="/tmp/bconn-test/state"
```

### Real hardware

```bash
./bin/bconn doctor
./bin/bconn --verbose list
./bin/bconn daemon once --no-audio --no-notify --verbose
./bin/bconn daemon run --poll 5 --verbose
```

---

## 5. Common development tasks

### Add a CLI command

1. Implement `cmd_<name>(args: argparse.Namespace) -> int` in `bconn/cli.py`.
   Return `0` for success and raise `BconnError(title, hint)` for failures.
2. Register it in `build_parser()`:

   ```python
   p_thing = add("thing", cmd_thing, "one-line help")
   p_thing.add_argument("device", help="device name, alias, or MAC")
   p_thing.add_argument("--json", action="store_true")
   ```

3. Add a test. Use `tests/test_integration_fake.py` for end-to-end coverage
   against the fake BlueZ service.
4. Update `README.md` (features/quick start) and, if it changes installation,
   `docs/INSTALL.md`.

### Add a tray menu item or device action

- Menu construction: `bconn/ui/app.py` → `_build_menu()`.
- Device submenu: `_device_submenu()`.
- Put formatting/label/state logic in `bconn/ui/model.py` (pure, unit-testable).
- Keep operations non-blocking: long D-Bus work goes through the existing
  operation helpers, which refresh state when finished.
- After changing tray state rules, run the GUI and check the icon for
  off / ready / connected / scanning / attention / error.

### Add a doctor check

There are two implementations:

- **CLI/terminal:** `bin/bconn-doctor` (bash). Add a `pass`/`warn`/`fail` block.
- **GUI:** `bconn/ui/doctor.py` (runs the same script and renders the result).

The script must stay read-only and print an exact fix command for every failure.
Exit codes: `0` healthy, `1` blocking, `2` warnings.

### Change configuration

- Defaults live in `bconn/config.py` (`DEFAULT_CONFIG`, `DEVICE_DEFAULTS`).
- Add a migration only when the meaning of an existing key changes; otherwise
  let `_normalize()` fill defaults.
- Document user-visible keys in `README.md` and `docs/INSTALL.md`.

### Change the daemon

- Logic: `bconn/daemon.py` (`AutoConnectDaemon._cycle`, `_maybe_connect`).
- Unit file: `render_unit()` and `install_unit()`.
- Backoff is tested in `tests/test_daemon.py`; keep `backoff_delay` pure.
- Keep manual-disconnect semantics: never reconnect a `paused` device.

---

## 6. Debugging

```bash
# Human-readable CLI failures, including D-Bus detail
./bin/bconn --verbose connect buds

# Daemon: one pass with debug logging
./bin/bconn daemon run --poll 5 --verbose

# Installed service logs
bconn daemon logs -f
journalctl --user-unit bconn-daemon --no-pager -n 50

# Watch BlueZ property changes while reproducing a bug
dbus-monitor --system "interface='org.bluez.Device1'"

# Audio state
wpctl status
wpctl inspect <id>
pw-dump | less
```

GTK/PyGObject warnings usually mean a missing typelib or a version that was not
requested with `gi.require_version`. The GUI deliberately targets GTK 3, not
GTK 4.

If the daemon restarts in a loop after many crashes:

```bash
systemctl --user reset-failed bconn-daemon
bconn daemon logs -n 100
```

---

## 7. Code conventions

- Python 3.10+ syntax, `from __future__ import annotations`.
- Standard library only, plus the system-provided `gi` and `cairo`.
- Keep core modules free of GTK imports.
- Prefer small pure helpers (see `ui/model.py`) so behavior is testable without
  a display.
- Errors shown to users must have a title and a concrete hint. Use
  `BconnError`/`BluezError`, not bare exceptions.
- Tests use stdlib `unittest`; in tests, `assert_ok(result)` is used for CLI
  return codes.
- No new runtime service, no root, no background thread pool.

---

## 8. Release checklist

1. Update `__version__` in `bconn/__init__.py`. This is the single source of
   truth: `pyproject.toml` reads it through `[tool.setuptools.dynamic]`.
   Add the matching section to `CHANGELOG.md` and update its comparison links.
2. Run `python3 -m unittest discover -s tests -v` and `python3 -m pytest -q` —
   all tests must pass.
3. Run `./bin/bconn doctor` and `./bin/bconn daemon once --no-audio --no-notify`.
4. Smoke-test the installed flow from a clean checkout:

   ```bash
   sudo ./install.sh
   bconn --version
   bconn doctor
   sudo ./install.sh --uninstall
   ```

5. Smoke-test the GUI: tray icon, scan window, preferences, shortcut launch.
6. Update `README.md`, `docs/INSTALL.md`, and `docs/PLAN.md` status if behavior
   changed.
7. Check that the config and state paths still match the documentation.
8. Commit, then tag and push. The tag must be `v` plus the exact
   `bconn.__version__` value:

   ```bash
   git add -A
   git commit -m "release: BConn 0.2.0"
   git push origin main
   git tag -a v0.2.0 -m "BConn 0.2.0"
   git push origin v0.2.0
   ```

   The `Release` workflow runs the tests, verifies the tag, builds the sdist
   and wheel, and publishes the GitHub Release with generated notes. See
   [`docs/PUBLISHING.md`](PUBLISHING.md#5-release-versioning) for the full
   process.

   `.deb` packaging is still future work; the supported installs are
   `sudo ./install.sh` and `pipx install --system-site-packages`.
