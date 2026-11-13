#!/usr/bin/env bash
#
# BConn installer for Debian, Kali, and Ubuntu.
#
# Recommended (from a checkout):
#   sudo ./install.sh
#
# One-liner (after the repository is published):
#   curl -fsSL https://raw.githubusercontent.com/d43m0n1z3r/bconn/main/install.sh | sudo bash
#
# What it does:
#   1. Installs the runtime packages with apt.
#   2. Copies BConn to /opt/bconn.
#   3. Adds the bconn, bconn-gui, bconn-daemon, and bconn-doctor commands.
#   4. Enables the Bluetooth service and unblocks the radio.
#   5. Adds the application-menu shortcut for your desktop user.
#   6. Installs the opt-in auto-reconnect service.
#
# Options:
#   --prefix DIR     Install directory           (default: /opt/bconn)
#   --bindir DIR     Command directory           (default: /usr/local/bin)
#   --user NAME      Desktop user to configure   (default: the sudo user)
#   --repo URL       Git URL used when piped
#   --no-shortcut    Skip the application-menu entry
#   --no-daemon      Skip the auto-reconnect service
#   --no-user        Skip all per-user setup
#   --uninstall      Remove BConn
#   -h, --help       Show this help
#
# Environment:
#   BCONN_REPO_URL   Overrides the default clone URL
#   BCONN_USER       Overrides the desktop user

set -Eeuo pipefail

RERUN_ARGS=("$@")

APP_NAME="BConn"
PREFIX="/opt/bconn"
BINDIR="/usr/local/bin"
REPO_URL="${BCONN_REPO_URL:-https://github.com/d43m0n1z3r/bconn.git}"
TARGET_USER="${BCONN_USER:-${SUDO_USER:-}}"
INSTALL_SHORTCUT=1
INSTALL_DAEMON=1
SETUP_USER=1
UNINSTALL=0

if [ -t 1 ]; then
    BOLD=$'\e[1m'
    DIM=$'\e[2m'
    GREEN=$'\e[32m'
    YELLOW=$'\e[33m'
    RED=$'\e[31m'
    RESET=$'\e[0m'
else
    BOLD=''
    DIM=''
    GREEN=''
    YELLOW=''
    RED=''
    RESET=''
fi

step() { printf '\n%s==>%s %s%s%s\n' "$GREEN" "$RESET" "$BOLD" "$1" "$RESET"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }

die() {
    printf '\n%sCould not continue:%s %s\n' "$RED" "$RESET" "$1" >&2
    if [ -n "${2:-}" ]; then
        printf '  %s\n' "$2" >&2
    fi
    exit 1
}

usage() {
    cat <<'HELP'
BConn installer for Debian, Kali, and Ubuntu.

Usage:
  sudo ./install.sh
  curl -fsSL https://raw.githubusercontent.com/d43m0n1z3r/bconn/main/install.sh | sudo bash

Options:
  --prefix DIR     Install directory           (default: /opt/bconn)
  --bindir DIR     Command directory           (default: /usr/local/bin)
  --user NAME      Desktop user to configure   (default: the sudo user)
  --repo URL       Git URL used when piped
  --no-shortcut    Skip the application-menu entry
  --no-daemon      Skip the auto-reconnect service
  --no-user        Skip all per-user setup
  --uninstall      Remove BConn
  -h, --help       Show this help
HELP
    exit 0
}

on_error() {
    local status=$?
    if [ "$UNINSTALL" -eq 1 ]; then
        printf '\n%sUninstall failed (exit %s).%s\n' "$RED" "$status" "$RESET" >&2
    else
        printf '\n%sInstallation failed (exit %s).%s\n' "$RED" "$status" "$RESET" >&2
        printf 'Fix the problem above and run the installer again.\n' >&2
        printf 'Manual steps: https://github.com/d43m0n1z3r/bconn/blob/main/docs/INSTALL.md\n' >&2
    fi
}
trap on_error ERR

# ------------------------------------------------------------------ arguments

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
fi

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)    PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
        --bindir)    BINDIR="${2:?--bindir needs a directory}"; shift 2 ;;
        --user)      TARGET_USER="${2:?--user needs a name}"; shift 2 ;;
        --repo)      REPO_URL="${2:?--repo needs a URL}"; shift 2 ;;
        --no-shortcut) INSTALL_SHORTCUT=0; shift ;;
        --no-daemon)   INSTALL_DAEMON=0; shift ;;
        --no-user)     SETUP_USER=0; shift ;;
        --uninstall)   UNINSTALL=1; shift ;;
        -h|--help)     usage ;;
        *) die "Unknown option: $1" "Run with --help to see the available options." ;;
    esac
done

case "$PREFIX" in
    /?*) : ;;
    *) die "--prefix must be an absolute path (got: $PREFIX)" ;;
esac
case "$BINDIR" in
    /?*) : ;;
    *) die "--bindir must be an absolute path (got: $BINDIR)" ;;
esac

# Re-run as root when the script is a real file and the user forgot sudo.
if [ "$(id -u)" -ne 0 ]; then
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/install.sh" ]; then
        printf 'Root is needed for the system part of the install. Re-running with sudo...\n'
        ENV_ARGS=()
        [ -n "${BCONN_REPO_URL:-}" ] && ENV_ARGS+=(--repo "$BCONN_REPO_URL")
        [ -n "${BCONN_USER:-}" ] && ENV_ARGS+=(--user "$BCONN_USER")
        exec sudo bash "$SCRIPT_DIR/install.sh" "${ENV_ARGS[@]}" "${RERUN_ARGS[@]}"
    fi
    die "Run the installer as root." "Download the file and use: sudo bash install.sh"
fi

# --------------------------------------------------------------- target user

if [ "$SETUP_USER" -eq 1 ]; then
    if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ] || ! id "$TARGET_USER" >/dev/null 2>&1; then
        TARGET_USER="$(getent passwd | awk -F: '
            $3 >= 1000 && $3 < 60000 && $6 ~ /^\// && $7 !~ /(nologin|false)$/ { print $1; exit }
        ')"
    fi
    if [ -z "$TARGET_USER" ]; then
        warn "No desktop user found; skipping the shortcut and the user service."
        SETUP_USER=0
    fi
fi

as_user() {
    local user="$1"
    shift
    local uid home runtime
    uid="$(id -u "$user")"
    home="$(getent passwd "$user" | cut -d: -f6)"
    runtime="/run/user/$uid"
    local -a envs=("HOME=$home")
    if [ -d "$runtime" ]; then
        envs+=("XDG_RUNTIME_DIR=$runtime")
        if [ -S "$runtime/bus" ]; then
            envs+=("DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus")
        fi
    fi
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$user" -- env "${envs[@]}" "$@"
    else
        sudo -u "$user" env "${envs[@]}" "$@"
    fi
}

# ---------------------------------------------------------------- uninstall

uninstall_bconn() {
    step "Removing $APP_NAME"

    if [ "$SETUP_USER" -eq 1 ]; then
        if as_user "$TARGET_USER" "$PREFIX/bin/bconn" daemon uninstall >/dev/null 2>&1; then
            ok "Auto-reconnect service removed"
        else
            warn "No auto-reconnect service was running"
        fi
        if as_user "$TARGET_USER" "$PREFIX/bin/bconn" shortcut uninstall >/dev/null 2>&1; then
            ok "Application-menu shortcut removed"
        else
            warn "No application-menu shortcut was installed"
        fi
    fi

    local name
    for name in bconn bconn-gui bconn-daemon bconn-doctor; do
        if [ -f "$BINDIR/$name" ] && grep -qF "$PREFIX" "$BINDIR/$name" 2>/dev/null; then
            rm -f "$BINDIR/$name"
            ok "Removed $BINDIR/$name"
        fi
    done
    rm -f "$BINDIR/bconn-uninstall"

    if [ -d "$PREFIX" ]; then
        rm -rf "$PREFIX"
        ok "Removed $PREFIX"
    fi

    if [ "$SETUP_USER" -eq 0 ]; then
        printf '\n%sPer-user cleanup was skipped (--no-user).%s\n' "$YELLOW" "$RESET"
        printf 'Run "bconn shortcut uninstall" and "bconn daemon uninstall" as the\n'
        printf 'desktop user if you installed those earlier.\n'
    fi

    printf '\n%s%s is no longer installed.%s\n' "$BOLD" "$APP_NAME" "$RESET"
    printf 'Your devices and preferences were kept in:\n'
    printf '  ~/.config/bconn/  and  ~/.local/state/bconn/\n'
    printf '\nDelete them too with:\n  rm -rf ~/.config/bconn ~/.local/state/bconn\n'
    exit 0
}

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_bconn
fi

# --------------------------------------------------------------- source tree

TEMP_DIR=""
cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

SOURCE_DIR=""
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/bconn/__init__.py" ]; then
    SOURCE_DIR="$SCRIPT_DIR"
fi

printf '%s%s installer%s\n' "$BOLD" "$APP_NAME" "$RESET"
printf '%sOne command installs everything.%s\n' "$DIM" "$RESET"

# --------------------------------------------------------------- distro check

if ! command -v apt-get >/dev/null 2>&1; then
    die "This installer supports Debian, Kali, and Ubuntu." \
        "On other distributions follow docs/INSTALL.md manually."
fi

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf '  System: %s\n' "${PRETTY_NAME:-Debian-family Linux}"
fi

if [ -z "$SOURCE_DIR" ]; then
    # Kept so an older copy with the placeholder still fails with a clear message.
    case "$REPO_URL" in
        *"<your-user>"*)
            die "This script was downloaded without the repository address." \
                "Download the project archive instead, or run the installer from a checkout."
            ;;
    esac
    if ! command -v git >/dev/null 2>&1; then
        step "Installing git"
        DEBIAN_FRONTEND=noninteractive apt-get update -qq </dev/null || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y git </dev/null
    fi
    step "Downloading $APP_NAME"
    TEMP_DIR="$(mktemp -d)"
    git clone --depth 1 "$REPO_URL" "$TEMP_DIR/source" </dev/null \
        || die "Could not download $APP_NAME from $REPO_URL" \
               "Check your internet connection, then try again."
    SOURCE_DIR="$TEMP_DIR/source"
fi

if [ ! -f "$SOURCE_DIR/bconn/__init__.py" ]; then
    die "The installer could not find the BConn source files." \
        "Run install.sh from the top of the BConn folder."
fi

# --------------------------------------------------------------- dependencies

step "Installing system packages"
PACKAGES=(
    python3
    python3-gi
    python3-cairo
    gir1.2-gtk-3.0
    gir1.2-notify-0.7
    gir1.2-ayatanaappindicator3-0.1
    bluez
    rfkill
    pipewire-bin
    wireplumber
    libnotify-bin
    desktop-file-utils
)

DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

missing=()
for package in "${PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
        missing+=("$package")
    fi
done

if [ "${#missing[@]}" -gt 0 ]; then
    printf '  Installing: %s\n' "${missing[*]}"
    apt-get update -qq </dev/null || \
        warn "Could not refresh the package list; using the existing one."
    if ! apt-get install -y "${missing[@]}" </dev/null; then
        warn "The batch install failed; retrying the packages one by one."
        for package in "${missing[@]}"; do
            apt-get install -y "$package" </dev/null || \
                warn "Could not install $package (continuing)"
        done
    fi
else
    ok "All required packages are already installed"
fi

# ------------------------------------------------------------- sanity checks

step "Checking the Python environment"

if ! /usr/bin/python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    die "Python 3.10 or newer is required." \
        "This should come with Kali; check that /usr/bin/python3 exists."
fi
ok "Python $(/usr/bin/python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"

if ! /usr/bin/python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null; then
    die "The GTK 3 Python bindings are still missing." \
        "Install python3-gi and gir1.2-gtk-3.0, then run the installer again."
fi
ok "GTK 3 bindings"

if /usr/bin/python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); from gi.repository import AyatanaAppIndicator3" 2>/dev/null; then
    ok "Tray icon support"
else
    warn "Tray icon support is missing; the GUI will open as a normal window."
fi

if /usr/bin/python3 -c "import gi; gi.require_version('Notify', '0.7'); from gi.repository import Notify" 2>/dev/null; then
    ok "Desktop notifications"
else
    warn "Notifications are unavailable; connections still work."
fi

# ------------------------------------------------------------------ copy files

step "Installing $APP_NAME to $PREFIX"

STAGE="${PREFIX}.new.$$"
BACKUP="${PREFIX}.old.$$"
rm -rf "$STAGE" "$BACKUP"
install -d -m 0755 "$STAGE"

tar \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    -C "$SOURCE_DIR" -cf - . | tar -C "$STAGE" -xf -

chown -R root:root "$STAGE"
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +
chmod 0755 "$STAGE"/bin/bconn "$STAGE"/bin/bconn-gui "$STAGE"/bin/bconn-daemon "$STAGE"/bin/bconn-doctor
[ -f "$STAGE/install.sh" ] && chmod 0755 "$STAGE/install.sh"
[ -f "$STAGE/uninstall.sh" ] && chmod 0755 "$STAGE/uninstall.sh"

if [ -e "$PREFIX" ]; then
    mv "$PREFIX" "$BACKUP"
fi
mv "$STAGE" "$PREFIX"
rm -rf "$BACKUP"
ok "Files copied to $PREFIX"

# ------------------------------------------------------------------ launchers

step "Adding the commands to $BINDIR"
install -d -m 0755 "$BINDIR"

write_launcher() {
    local name="$1"
    local target="$2"
    cat > "$BINDIR/$name" <<LAUNCHER
#!/bin/sh
# Generated by the BConn installer. Re-run the installer to update.
exec "$target" "\$@"
LAUNCHER
    chmod 0755 "$BINDIR/$name"
}

write_launcher bconn "$PREFIX/bin/bconn"
write_launcher bconn-gui "$PREFIX/bin/bconn-gui"
write_launcher bconn-daemon "$PREFIX/bin/bconn-daemon"
write_launcher bconn-doctor "$PREFIX/bin/bconn-doctor"

cat > "$BINDIR/bconn-uninstall" <<LAUNCHER
#!/bin/sh
# Generated by the BConn installer.
exec sudo "$PREFIX/install.sh" --uninstall "\$@"
LAUNCHER
chmod 0755 "$BINDIR/bconn-uninstall"

ok "bconn, bconn-gui, bconn-daemon, bconn-doctor, bconn-uninstall"

if installed_version="$("$BINDIR/bconn" --version 2>/dev/null)"; then
    ok "$installed_version"
else
    warn "The bconn command did not start; run bconn doctor for details."
fi

# ------------------------------------------------------------------ bluetooth

step "Preparing Bluetooth"

if command -v systemctl >/dev/null 2>&1; then
    if systemctl enable --now bluetooth </dev/null >/dev/null 2>&1; then
        ok "bluetooth.service is enabled and running"
    else
        warn "Could not start bluetooth.service; run: sudo systemctl enable --now bluetooth"
    fi
fi

if command -v rfkill >/dev/null 2>&1; then
    if rfkill unblock bluetooth >/dev/null 2>&1; then
        ok "Bluetooth radio is unblocked"
    else
        warn "Could not unblock the radio; run: sudo rfkill unblock bluetooth"
    fi
fi

# ---------------------------------------------------------------- per-user setup

if [ "$SETUP_USER" -eq 1 ]; then
    step "Setting up the desktop for $TARGET_USER"

    if [ "$INSTALL_SHORTCUT" -eq 1 ]; then
        if as_user "$TARGET_USER" "$PREFIX/bin/bconn" shortcut install >/dev/null 2>&1; then
            ok "Application-menu shortcut added"
        else
            warn "Could not add the shortcut; run: bconn shortcut install"
        fi
    fi

    if [ "$INSTALL_DAEMON" -eq 1 ]; then
        if output="$(as_user "$TARGET_USER" "$PREFIX/bin/bconn" daemon install 2>&1)"; then
            # Pick up the new binary path if an older install was already running.
            as_user "$TARGET_USER" "$PREFIX/bin/bconn" daemon restart >/dev/null 2>&1 || true
            ok "Auto-reconnect service installed"
        else
            warn "Could not start the auto-reconnect service right now."
            printf '      %s\n' "$(printf '%s' "$output" | tail -n 1)"
            printf '      After logging in, run: bconn daemon install\n'
        fi
    fi
fi

# -------------------------------------------------------------------- summary

printf '\n%s%s is installed.%s\n\n' "$BOLD$GREEN" "$APP_NAME" "$RESET"
printf '  %sCommand%s      bconn\n' "$BOLD" "$RESET"
printf '  %sTray app%s     bconn-gui   (or open "BConn" from the application menu)\n' "$BOLD" "$RESET"
printf '  %sHealth%s       bconn doctor\n' "$BOLD" "$RESET"
printf '\nTry it:\n'
printf '  bconn scan\n'
printf '  bconn pair <device> --connect\n'
printf '  bconn auto <device> on     # reconnect it automatically\n'
printf '\nRemove it later with: sudo bconn-uninstall\n'

if [ "$SETUP_USER" -eq 1 ]; then
    printf '\n%sHealth check%s\n' "$BOLD" "$RESET"
    as_user "$TARGET_USER" "$PREFIX/bin/bconn" doctor || true
fi
