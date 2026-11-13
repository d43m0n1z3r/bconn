"""Application-menu shortcut (``.desktop``) installation.

When BConn is installed, the shortcut launches the ``bconn-gui`` console script
by name, so ``Exec=`` resolves through ``PATH`` and keeps working if the
checkout moves. From an uninstalled checkout it falls back to an absolute path
to ``bin/bconn-gui``.

The entry is written to ``~/.local/share/applications/bconn.desktop``.

No GTK import is needed here: the icon is a self-contained SVG, so the shortcut
can be installed from a plain SSH session as well.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DESKTOP_NAME = "bconn.desktop"
ICON_NAME = "bconn"

ICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"
     viewBox="0 0 256 256">
  <defs>
    <linearGradient id="bconn-bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4a9eff"/>
      <stop offset="1" stop-color="#1c6fd8"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="224" height="224" rx="52" fill="url(#bconn-bg)"/>
  <g transform="translate(64 64) scale(5.3333)" fill="none" stroke="#ffffff"
     stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M6.5 6.5l11 11L12 23V1l5.5 5.5-11 11"/>
  </g>
</svg>
"""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def launcher_path() -> str:
    """Executable to launch the GUI, preferring the installed console script.

    A bare ``bconn-gui`` is resolved through ``PATH`` by the desktop
    environment, so the shortcut survives moving or renaming the checkout.
    Only an uninstalled checkout pins an absolute path.
    """
    if shutil.which("bconn-gui"):
        return "bconn-gui"
    candidate = project_root() / "bin" / "bconn-gui"
    if candidate.exists():
        return str(candidate)
    return "bconn-gui"


def data_home() -> Path:
    return Path(
        os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    )


def desktop_path() -> Path:
    return data_home() / "applications" / DESKTOP_NAME


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"


def _quote_exec(value: str) -> str:
    """Quote a path for a desktop entry ``Exec=`` line when needed."""
    if not any(character in value for character in ' \t"\\'):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_desktop(exec_path: str | None = None) -> str:
    executable = exec_path or launcher_path()
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=BConn\n"
        "GenericName=Bluetooth Manager\n"
        "Comment=Pair, connect, and auto-reconnect Bluetooth devices\n"
        f"Exec={_quote_exec(executable)} --window\n"
        f"Icon={ICON_NAME}\n"
        "Terminal=false\n"
        "Categories=Settings;HardwareSettings;\n"
        "Keywords=bluetooth;headset;earbuds;speaker;audio;pair;connect;\n"
        "StartupNotify=true\n"
        "StartupWMClass=bconn-gui\n"
    )


def _refresh_caches() -> None:
    """Best-effort menu/icon cache refresh; both helpers are optional."""
    applications = desktop_path().parent
    if shutil.which("update-desktop-database") and applications.is_dir():
        subprocess.run(
            ["update-desktop-database", str(applications)],
            capture_output=True,
            check=False,
        )
    hicolor = icon_path().parent.parent.parent
    if shutil.which("gtk-update-icon-cache") and (hicolor / "index.theme").exists():
        subprocess.run(
            ["gtk-update-icon-cache", "-f", "-t", str(hicolor)],
            capture_output=True,
            check=False,
        )


def is_installed() -> bool:
    return desktop_path().exists() and icon_path().exists()


def install_shortcut() -> str:
    desktop = desktop_path()
    icon = icon_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(render_desktop(), encoding="utf-8")
    os.chmod(desktop, 0o755)
    icon.write_text(ICON_SVG, encoding="utf-8")
    _refresh_caches()
    return (
        f"Installed {desktop}\n"
        f"Installed {icon}\n"
        "BConn is now available in the application menu."
    )


def uninstall_shortcut() -> str:
    removed: list[str] = []
    for path in (desktop_path(), icon_path()):
        if path.exists():
            path.unlink()
            removed.append(str(path))
    _refresh_caches()
    if not removed:
        return "No BConn shortcut is installed."
    return "Removed:\n" + "\n".join(removed)


def status_text() -> str:
    desktop = desktop_path()
    icon = icon_path()
    lines = [
        f"Shortcut   {'installed' if desktop.exists() else 'not installed'}  {desktop}",
        f"Icon       {'installed' if icon.exists() else 'not installed'}  {icon}",
    ]
    if desktop.exists():
        lines.append(f"Launcher   {shutil.which('bconn-gui') or launcher_path()}")
        lines.append("Open it from the application menu (search for BConn).")
    else:
        lines.append("Install it with: bconn shortcut install")
    return "\n".join(lines)
