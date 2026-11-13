"""Thin libnotify wrapper used by the tray and pairing flow."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Notify", "0.7")
from gi.repository import Notify  # noqa: E402


class Notifier:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.available = False
        try:
            self.available = bool(Notify.init("BConn"))
        except Exception:
            self.available = False

    def send(
        self,
        summary: str,
        body: str = "",
        *,
        urgency: str = "normal",
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        if not self.enabled or not self.available:
            return
        try:
            notification = Notify.Notification.new(summary, body, "bluetooth")
            levels = {
                "low": Notify.Urgency.LOW,
                "normal": Notify.Urgency.NORMAL,
                "critical": Notify.Urgency.CRITICAL,
            }
            notification.set_urgency(levels.get(urgency, Notify.Urgency.NORMAL))
            if action_label and action is not None:
                notification.add_action(
                    "default", action_label, lambda *_: action()
                )
            notification.show()
        except Exception:
            # Notifications are best-effort; never break a connection over one.
            pass

    def error(self, title: str, hint: str | None = None) -> None:
        self.send(title, hint or "", urgency="normal")

    def success(self, title: str, body: str = "") -> None:
        self.send(title, body, urgency="low")
