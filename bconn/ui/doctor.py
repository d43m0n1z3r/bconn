"""System-check window shared by the tray menu and the first-run panel."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402


def doctor_script() -> Path | None:
    candidate = Path(__file__).resolve().parents[2] / "bin" / "bconn-doctor"
    if candidate.exists():
        return candidate
    found = shutil.which("bconn-doctor")
    return Path(found) if found else None


class DoctorDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window | None = None):
        super().__init__(
            title="BConn — System check",
            transient_for=parent,
            modal=False,
            destroy_with_parent=True,
        )
        self.set_default_size(760, 520)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.recheck = self.add_button("Re-check", Gtk.ResponseType.OK)
        self.recheck.get_style_context().add_class("suggested-action")
        self.connect("response", self._on_response)

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        self.status = Gtk.Label(xalign=0)
        self.status.set_markup("<b>Checking the Bluetooth stack…</b>")
        box.add(self.status)

        self.spinner = Gtk.Spinner()
        self.spinner.set_halign(Gtk.Align.START)
        box.add(self.spinner)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(False)
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.modify_font(Pango.FontDescription("monospace 10"))
        scroller.add(self.text)
        box.add(scroller)

        self.show_all()
        self.spinner.hide()
        self.run_check()

    def _on_response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response == Gtk.ResponseType.OK:
            self.run_check()
        else:
            self.destroy()

    def run_check(self) -> None:
        script = doctor_script()
        self.text.get_buffer().set_text("")
        self.status.set_text("Running the system check…")
        self.spinner.show()
        self.spinner.start()
        self.recheck.set_sensitive(False)

        if script is None:
            self._done("Doctor script not found. Run ./bin/bconn-doctor from the project.")
            return

        thread = threading.Thread(
            target=self._worker, args=(script,), daemon=True
        )
        thread.start()

    def _worker(self, script: Path) -> None:
        try:
            result = subprocess.run(
                [str(script)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if not output:
                output = f"The check exited with status {result.returncode} and no output.\n"
        except Exception as error:  # pragma: no cover - defensive
            output = f"Could not run the system check: {error}\n"
        GLib.idle_add(self._done, output)

    def _done(self, output: str) -> bool:
        if not self.get_visible():
            return False
        self.spinner.stop()
        self.spinner.hide()
        self.recheck.set_sensitive(True)
        buffer = self.text.get_buffer()
        buffer.set_text(output)
        failed = "failed" in output.lower() or "✗" in output
        passed = "0 failed" in output
        if failed and not passed:
            self.status.set_markup("<b>Bluetooth needs attention</b>")
        else:
            self.status.set_markup("<b>Bluetooth looks healthy</b>")
        return False
