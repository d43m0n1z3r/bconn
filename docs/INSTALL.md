# Installing BConn

This guide covers a complete installation on Debian-family systems (Kali,
Ubuntu, Debian), notes for other distributions, upgrades, uninstall, and
troubleshooting.

For a one-screen overview, see the [README](../README.md#installation).

**Contents:** [Supported systems](#1-supported-systems) ·
[Dependencies (Debian/Kali)](#2-dependencies-on-debian-kali-and-ubuntu) ·
[Other distributions](#3-dependencies-on-other-distributions) ·
[Enable Bluetooth](#4-enable-bluetooth-once) ·
[One-command install](#5-install-bconn-one-command) ·
[Manual install](#6-manual-installation-from-a-checkout-developers) ·
[Auto-reconnect service](#7-auto-reconnect-service) · [Updating](#8-updating) ·
[Uninstall](#9-uninstall) · [Troubleshooting](#10-troubleshooting)

---

## 1. Supported systems

| Requirement | Notes |
|---|---|
| Linux with BlueZ 5.x | BConn talks to `org.bluez` over the system D-Bus |
| Python 3.10+ | Tested on Python 3.14 |
| GTK 3 + PyGObject | GTK 4 is not supported |
| PipeWire + WirePlumber | For Bluetooth audio routing (`wpctl`, `pw-dump`) |
| X11 or Wayland | Audio + tray tested on XFCE/X11 |

BConn runs entirely as your normal user. Root is needed for the installer
(system packages and the Bluetooth service) and for nothing else at runtime.

---

## 2. Dependencies on Debian, Kali, and Ubuntu

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
```

What each group does:

| Package | Used for |
|---|---|
| `python3-gi`, `python3-cairo` | PyGObject D-Bus bindings and icon rendering |
| `gir1.2-gtk-3.0` | GTK 3 tray window, dialogs, preferences |
| `gir1.2-notify-0.7` | Desktop notifications |
| `gir1.2-ayatanaappindicator3-0.1` | Tray icon (`AyatanaAppIndicator3`) |
| `bluez` | `bluetoothd`, `bluetoothctl`, D-Bus API |
| `rfkill` | Radio block detection |
| `pipewire-bin`, `wireplumber` | `pw-dump`, `wpctl`, audio routing |
| `desktop-file-utils` | Refreshes the application-menu cache (optional) |

Optional desktop helpers:

```bash
# Notification daemon, if your desktop does not already run one
sudo apt install -y xfce4-notifyd
```

BConn needs XFCE's **Status Tray Plugin** (`systray`) in the panel. It is
usually present by default; if not, add it from **Panel → Add New Items →
Status Tray Plugin** (or run `xfce4-panel --add=systray`).

## 3. Dependencies on other distributions

Package names vary. The same components are needed.

| Component | Arch Linux | Fedora |
|---|---|---|
| PyGObject | `python-gobject` | `python3-gobject` |
| Cairo bindings | `python-cairo` | `python3-cairo` |
| GTK 3 | `gtk3` | `gtk3` |
| libnotify | `libnotify` | `libnotify` |
| Ayatana AppIndicator | `libayatana-appindicator` | `libayatana-appindicator-gtk3` |
| BlueZ | `bluez` | `bluez` |
| rfkill | `util-linux` | `util-linux` |
| PipeWire | `pipewire` | `pipewire` |
| WirePlumber | `wireplumber` | `wireplumber` |
| Desktop cache tools | `desktop-file-utils` | `desktop-file-utils` |

Verify the GI typelibs after installing:

```bash
python3 - <<'PY'
import gi
for name, version in [
    ("Gtk", "3.0"),
    ("Notify", "0.7"),
    ("AyatanaAppIndicator3", "0.1"),
]:
    gi.require_version(name, version)
    __import__("gi.repository", fromlist=[name]).__dict__[name]
    print("ok:", name, version)
PY
```

---

## 4. Enable Bluetooth once

The installer in [section 5](#5-install-bconn-one-command) runs these commands
for you. To do it manually:

```bash
sudo systemctl enable --now bluetooth
rfkill unblock bluetooth

systemctl is-active bluetooth                 # active
systemctl is-enabled dbus-org.bluez.service  # alias (or enabled)
```

On Kali, `bluetooth.service` is often disabled and the
`dbus-org.bluez.service` alias missing. In that state `bluetoothctl` can hang
instead of reporting an error; the commands above fix both.

---

## 5. Install BConn (one command)

Install BConn with one command:

```bash
curl -fsSL https://raw.githubusercontent.com/d43m0n1z3r/bconn/main/install.sh | sudo bash
```

Working from a checkout? Clone it and run the same installer:

```bash
git clone https://github.com/d43m0n1z3r/bconn.git
cd bconn
sudo ./install.sh
```

If you downloaded a ZIP instead of cloning, extract it and run
`sudo ./install.sh` from inside the extracted folder.

The script is safe to run more than once; it upgrades the installed copy in
place and restarts the service if needed.

### What the installer does

1. Installs the packages from [section 2](#2-dependencies-on-debian-kali-and-ubuntu)
   with `apt`.
2. Copies BConn to `/opt/bconn` (owned by root, readable by everyone).
3. Adds launchers to `/usr/local/bin`.
4. Enables `bluetooth.service` and runs `rfkill unblock bluetooth`.
5. Adds the application-menu shortcut and icon for your desktop user.
6. Installs and starts the `systemd --user` auto-reconnect service.

It runs as root only for the system parts. The shortcut and the user service are
created as **your** user, so no root-owned files end up in your home directory.

### Installed layout

| Path | Contents |
|---|---|
| `/opt/bconn` | Application files (do not edit; re-run the installer to upgrade) |
| `/usr/local/bin/bconn` | CLI |
| `/usr/local/bin/bconn-gui` | Tray app |
| `/usr/local/bin/bconn-daemon` | Auto-reconnect service entry point |
| `/usr/local/bin/bconn-doctor` | Read-only system check |
| `/usr/local/bin/bconn-uninstall` | Removes the system install |
| `~/.config/bconn/config.json` | Your settings and per-device opt-in |
| `~/.local/state/bconn/state.json` | Runtime state (safe to delete) |

### Installer options

| Option | Meaning |
|---|---|
| `--user NAME` | Configure this desktop user instead of the `sudo` user |
| `--no-shortcut` | Skip the application-menu entry |
| `--no-daemon` | Skip the auto-reconnect service |
| `--no-user` | Skip all per-user setup (system install only) |
| `--prefix DIR` | Install somewhere other than `/opt/bconn` |
| `--bindir DIR` | Put the commands somewhere other than `/usr/local/bin` |
| `--uninstall` | Remove BConn |

For example, a system-only install without touching any desktop account:

```bash
sudo ./install.sh --no-user
```

### After installing

```bash
bconn doctor        # read-only health check
bconn scan          # find nearby devices
bconn pair buds --connect
```

A healthy machine ends with something like this (the exact count depends on your
desktop):

```text
Summary  21 passed · 0 warnings · 0 failed

Bluetooth looks ready.
```

---

## 6. Manual installation from a checkout (developers)

Use this when you are working on BConn and do not want a system-wide install.
There is no build step: BConn runs with the system Python and the
distribution's PyGObject.

```bash
# Dependencies from section 2, if you have not installed them already.
sudo systemctl enable --now bluetooth
rfkill unblock bluetooth

git clone https://github.com/d43m0n1z3r/bconn.git ~/.local/opt/bconn
cd ~/.local/opt/bconn

./bin/bconn --version
./bin/bconn doctor
```

### Optional: install the checkout with pipx

To put `bconn`, `bconn-gui`, and `bconn-daemon` on `PATH` without editing your
shell profile, install the checkout as an editable pipx app:

```bash
pipx install --editable --system-site-packages ~/.local/opt/bconn
```

`--system-site-packages` lets the app import the distribution's PyGObject
(`gi`). Editable mode means edits in the checkout take effect immediately.

### Alternative: add the checkout commands to `PATH`

```bash
# Zsh (the default on Kali)
echo 'export PATH="$HOME/.local/opt/bconn/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

```bash
# Bash
echo 'export PATH="$HOME/.local/opt/bconn/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Then use plain commands from anywhere:

```bash
bconn list
bconn-gui --window
bconn-daemon --once --no-audio --no-notify
```

### Add the application-menu shortcut manually

```bash
bconn shortcut install
bconn shortcut status
```

Files created:

- `~/.local/share/applications/bconn.desktop`
- `~/.local/share/icons/hicolor/scalable/apps/bconn.svg`

Search for **BConn** in the application menu. The shortcut runs
`bconn-gui --window`. When `bconn-gui` is on `PATH` (a pipx or system install),
`Exec=` uses the bare name so the shortcut survives moving the checkout; an
uninstalled checkout falls back to an absolute path. Clicking it while the tray
is already running raises the existing window instead of starting a second copy.

---

## 7. Auto-reconnect service

The installer already enables this. You only need this section for a manual
checkout install, or to change the service later.

Auto-connect is opt-in per device. Pair or connect the device first, then:

```bash
bconn auto buds on        # mark this device as wanted
bconn daemon install      # write the unit, enable + start it
bconn daemon status
```

The generated unit lives at
`~/.config/systemd/user/bconn-daemon.service`. It uses an absolute `ExecStart`,
preferring the installed `bconn-daemon` and falling back to the checkout
launcher, with an explicit `PYTHONPATH` only in the checkout case.

Useful commands:

```bash
bconn daemon logs -f      # follow the journal
bconn daemon restart
bconn daemon once         # one foreground pass, for debugging
bconn daemon uninstall    # disable + remove the unit
```

The daemon is a `systemd --user` service, so it starts with your user session.
If you want it to run before you log in (for example, reconnect earbuds at
boot), enable lingering:

```bash
sudo loginctl enable-linger "$USER"
```

Behavior reminders:

- `bconn auto <device> off` (or `paused: true` in the config) prevents reconnects.
- `bconn disconnect <device>` sets `paused: true`; connecting again clears it.
- Unpaired devices are skipped with a one-time notification.
- Failures back off exponentially, capped at 5 minutes.

---

## 8. Updating

### Installed with `install.sh`

```bash
cd /path/to/bconn     # the checkout you used
git pull --ff-only
sudo ./install.sh
```

The installer replaces `/opt/bconn`, refreshes the launchers, and restarts the
user service so it loads the new code. Your settings are kept.

### Manual checkout install

```bash
cd ~/.local/opt/bconn
git pull --ff-only

# Re-check the environment
./bin/bconn doctor

# If the service is installed, restart it so it loads the new code
bconn daemon restart

# If the shortcut or icon changed, reinstall it
bconn shortcut install
```

Run the test suite after updating if you develop against the checkout:

```bash
python3 -m unittest discover -s tests
```

### Installed with `pipx`

An editable pipx install already tracks the checkout, so pull and restart:

```bash
cd ~/.local/opt/bconn
git pull --ff-only
bconn daemon restart
```

For a non-editable pipx install, reinstall to pick up new code:

```bash
pipx reinstall bconn
bconn daemon restart
```

---

## 9. Uninstall

For a system install:

```bash
sudo bconn-uninstall
```

That stops and removes the user service, removes the shortcut, deletes the
launchers and `/opt/bconn`, and keeps your settings. To delete those too:

```bash
rm -rf ~/.config/bconn ~/.local/state/bconn
```

If `bconn-uninstall` is unavailable, run the installer directly:

```bash
sudo ./install.sh --uninstall
```

For a manual checkout install:

```bash
bconn daemon uninstall        # stop + remove the user unit
bconn shortcut uninstall      # remove the menu entry + icon

rm -rf ~/.local/opt/bconn
rm -rf ~/.config/bconn ~/.local/state/bconn   # optional: forget saved devices
```

If you added the `PATH` line, remove it from `~/.bashrc` or `~/.zshrc`.

For a pipx install:

```bash
bconn daemon uninstall        # stop + remove the user unit
bconn shortcut uninstall      # remove the menu entry + icon
pipx uninstall bconn
```

Your settings and state are kept unless you delete them as shown above.

---

## 10. Troubleshooting

Always start with the read-only doctor:

```bash
bconn doctor
# or, from the checkout:
./bin/bconn doctor
```

Exit codes: `0` healthy, `1` blocking problem, `2` warnings only.

### `bluetoothctl` hangs or reports no controller

```bash
sudo systemctl enable --now bluetooth
systemctl is-active bluetooth
systemctl is-enabled dbus-org.bluez.service
systemctl restart bluetooth
```

If the adapter is still missing:

```bash
rfkill list bluetooth
lsusb | grep -i bluetooth
dmesg | grep -i blue | tail -20
```

In a VM, make sure the Bluetooth USB adapter is passed through to the guest.

### Radio is soft-blocked

```bash
rfkill unblock bluetooth
```

A **hard** block is a hardware switch or firmware/BIOS setting; software cannot
clear it.

### Adapter is powered off

BConn powers the adapter on automatically when it needs to. You can also do it
manually:

```bash
bluetoothctl power on
```

### Permission or polkit errors

The user should be in the `bluetooth` group:

```bash
id -nG | tr ' ' '\n' | grep bluetooth
# if missing:
sudo usermod -aG bluetooth "$USER"
```

Log out and back in after changing groups.

### No tray icon

BConn needs a StatusNotifier host. On XFCE that is the **Status Tray Plugin**
(`systray`) in the panel:

```bash
xfce4-panel --add=systray
```

You can also add it from **Panel → Add New Items → Status Tray Plugin**.

If no host can be used, BConn falls back to a normal window:

```bash
bconn gui --window
```

### No notifications

Install and start a notification daemon:

```bash
sudo apt install -y xfce4-notifyd
```

Notifications can also be disabled in the config
(`"notifications": false`). When running the daemon in the foreground, pass
`--no-notify` (`bconn daemon run --no-notify`).

### Connected, but audio still comes from the laptop

```bash
wpctl status
systemctl --user status wireplumber
bconn audio
```

Pick the Bluetooth sink explicitly:

```bash
bconn audio <sink-id|name|mac>
```

If no Bluetooth sink appears, check that WirePlumber is running and that the
device negotiated an audio profile (A2DP). Reconnect the device and retry.

### Pairing prompt never appears

Only one BlueZ pairing agent can be the default. If Blueman's applet is running,
quit it and try again. BConn reports a clear error if it cannot claim the agent.

### A device is paired to another host

Phones and some headsets keep a single active bond. Remove the pairing on the
other device, then re-pair from BConn:

```bash
bconn forget buds
bconn pair buds --connect
```

### The daemon does not reconnect a device

```bash
bconn auto <device>            # show current setting
bconn auto <device> on
bconn daemon status
bconn daemon logs              # last 100 journal lines
# or:
journalctl --user-unit bconn-daemon -n 50
```

Common causes:

- `auto_connect` is off for that device.
- The device was manually disconnected and is `paused`.
- The device is not paired yet (the daemon asks you to pair once).
- The adapter is off or the Bluetooth service is not running.
- The service hit its restart limit after repeated crashes; clear it with
  `systemctl --user reset-failed bconn-daemon`.

### Reset the configuration

Config is JSON and corruption is tolerated: an unreadable file is renamed to
`config.json.corrupt-<timestamp>` and defaults are used. To reset manually:

```bash
rm -f ~/.config/bconn/config.json
```

State is runtime-only and safe to delete:

```bash
rm -f ~/.local/state/bconn/state.json
```

### `bconn doctor` says the doctor script is missing

This happens when `bin/bconn-doctor` is not next to the package, which is
expected for a pipx install. Use the subcommand instead:

```bash
bconn doctor
```

From a checkout, run `./bin/bconn-doctor`.

### `pipx` install fails to import `gi`

An isolated virtualenv cannot see the distribution's PyGObject. Install with
system site packages:

```bash
pipx install --system-site-packages git+https://github.com/d43m0n1z3r/bconn.git
```

From a checkout, add `--editable` to track your working tree:

```bash
pipx install --editable --system-site-packages .
```

There is no PyPI release or `.deb` yet — use `pipx` or `sudo ./install.sh`.
