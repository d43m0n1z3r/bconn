"""Tray icon rendering.

AppIndicator only takes icon *names*, so BConn renders a small set of state
icons into a private icon theme in the cache directory and points the
indicator at it. Rendering uses the user's current icon theme glyph, so the
tray still looks native.
"""

from __future__ import annotations

import os
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import cairo  # noqa: E402

STATE_GLYPHS: dict[str, tuple[str, str | None]] = {
    # state: (theme icon, dot colour)
    "off": ("bluetooth-disabled", None),
    "ready": ("bluetooth", "#3584e4"),
    "connected": ("bluetooth-active", "#2ec27e"),
    "scanning": ("bluetooth-active", "#3584e4"),
    "attention": ("bluetooth", "#e5a50a"),
    "error": ("bluetooth", "#e01b24"),
}

_FALLBACK_ICONS = {
    "off": "bluetooth-disabled",
    "ready": "bluetooth",
    "connected": "bluetooth-active",
    "scanning": "bluetooth-active",
    "attention": "bluetooth",
    "error": "bluetooth",
}

SIZES = (22, 24, 32, 48)


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "bconn" / "icons"


def theme_path() -> Path:
    return cache_root()


def icon_name(state: str) -> str:
    return f"bconn-{state if state in STATE_GLYPHS else 'ready'}"


def fallback_name(state: str) -> str:
    return _FALLBACK_ICONS.get(state, "bluetooth")


def _load_pixbuf(icon: str, size: int):
    theme = Gtk.IconTheme.get_default()
    for name in (icon, "bluetooth"):
        try:
            return theme.load_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE)
        except GLib.Error:
            continue
    return None


def _render(state: str, size: int, path: Path) -> bool:
    glyph, colour = STATE_GLYPHS.get(state, STATE_GLYPHS["ready"])
    pixbuf = _load_pixbuf(glyph, size)
    if pixbuf is None:
        return False

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    context = cairo.Context(surface)
    source = Gdk.cairo_surface_create_from_pixbuf(pixbuf, 0, None)
    context.set_source_surface(source, (size - pixbuf.get_width()) / 2, (size - pixbuf.get_height()) / 2)
    context.paint()

    if colour:
        radius = max(2.5, size * 0.16)
        cx = size - radius - size * 0.08
        cy = size - radius - size * 0.08
        # A subtle halo keeps the dot legible on light and dark panels.
        context.set_source_rgba(1, 1, 1, 0.85)
        context.arc(cx, cy, radius + max(1.0, size * 0.05), 0, 2 * 3.141592653589793)
        context.fill()
        red = int(colour[1:3], 16) / 255
        green = int(colour[3:5], 16) / 255
        blue = int(colour[5:7], 16) / 255
        context.set_source_rgb(red, green, blue)
        context.arc(cx, cy, radius, 0, 2 * 3.141592653589793)
        context.fill()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        surface.write_to_png(str(path))
        return True
    except (OSError, cairo.Error):
        return False


def ensure_icons() -> Path:
    """Render all tray states once per session; returns the theme root."""
    root = theme_path()
    for state in STATE_GLYPHS:
        for size in SIZES:
            target = root / "hicolor" / f"{size}x{size}" / "status" / f"{icon_name(state)}.png"
            if not target.exists():
                _render(state, size, target)
    return root


def apply_icon(indicator, state: str) -> None:
    """Set the indicator icon, with a graceful fallback to stock names."""
    try:
        indicator.set_icon_full(icon_name(state), f"BConn — {state}")
        return
    except Exception:
        pass
    try:
        indicator.set_icon_full(fallback_name(state), f"BConn — {state}")
    except Exception:
        pass
