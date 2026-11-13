"""GTK 3 tray and scan window for BConn."""

from __future__ import annotations

import sys


def main(show_window: bool = False) -> int:
    from gi.repository import GLib

    from .app import BconnApplication

    # Keep WM_CLASS stable no matter whether the user ran `bconn gui`,
    # `bconn-gui`, or the application-menu shortcut (StartupWMClass).
    GLib.set_prgname("bconn-gui")
    GLib.set_application_name("BConn")
    app = BconnApplication(show_window=show_window)
    return int(app.run(sys.argv))


__all__ = ["main"]
