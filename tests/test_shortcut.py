"""Tests for the application-menu shortcut writer."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bconn import shortcut


class DesktopEntryTests(unittest.TestCase):
    def test_render_contains_required_keys(self):
        text = shortcut.render_desktop("/opt/bconn/bin/bconn-gui")
        self.assertIn("[Desktop Entry]", text)
        self.assertIn("Type=Application", text)
        self.assertIn("Name=BConn", text)
        self.assertIn("Exec=/opt/bconn/bin/bconn-gui --window", text)
        self.assertIn("Icon=bconn", text)
        self.assertIn("Terminal=false", text)
        self.assertIn("Categories=Settings;HardwareSettings;", text)
        self.assertIn("StartupWMClass=bconn-gui", text)

    def test_render_quotes_paths_with_spaces(self):
        text = shortcut.render_desktop("/home/me/My Apps/bin/bconn-gui")
        self.assertIn('Exec="/home/me/My Apps/bin/bconn-gui" --window', text)

    def test_render_escapes_quotes_and_backslashes(self):
        text = shortcut.render_desktop('/opt/a"b\\c')
        self.assertIn('Exec="/opt/a\\"b\\\\c" --window', text)

    def test_icon_is_self_contained_svg(self):
        self.assertIn("<svg", shortcut.ICON_SVG)
        self.assertIn('stroke="#ffffff"', shortcut.ICON_SVG)
        self.assertNotIn("href", shortcut.ICON_SVG)

    def test_bare_name_is_not_quoted(self):
        text = shortcut.render_desktop("bconn-gui")
        self.assertIn("Exec=bconn-gui --window", text)


class LauncherPathTests(unittest.TestCase):
    def test_prefers_installed_console_script(self):
        with mock.patch.object(
            shortcut.shutil, "which", return_value="/home/me/.local/bin/bconn-gui"
        ):
            self.assertEqual(shortcut.launcher_path(), "bconn-gui")

    def test_falls_back_to_checkout_launcher(self):
        with mock.patch.object(shortcut.shutil, "which", return_value=None):
            expected = str(shortcut.project_root() / "bin" / "bconn-gui")
            self.assertEqual(shortcut.launcher_path(), expected)


class InstallTests(unittest.TestCase):
    def test_install_and_uninstall_honour_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": temp}, clear=False
            ):
                self.assertFalse(shortcut.is_installed())

                message = shortcut.install_shortcut()
                self.assertIn("application menu", message)
                self.assertTrue(shortcut.desktop_path().exists())
                self.assertTrue(shortcut.icon_path().exists())
                self.assertTrue(shortcut.is_installed())
                self.assertEqual(
                    shortcut.desktop_path(),
                    Path(temp) / "applications" / "bconn.desktop",
                )

                entry = shortcut.desktop_path().read_text(encoding="utf-8")
                self.assertIn("--window", entry)
                self.assertIn(shortcut.launcher_path(), entry)

                status = shortcut.status_text()
                self.assertIn("installed", status)
                self.assertIn("Launcher", status)

                shortcut.uninstall_shortcut()
                self.assertFalse(shortcut.is_installed())
                self.assertFalse(shortcut.desktop_path().exists())
                self.assertFalse(shortcut.icon_path().exists())

    def test_uninstall_when_missing_is_harmless(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": temp}, clear=False
            ):
                self.assertIn("No BConn shortcut", shortcut.uninstall_shortcut())


if __name__ == "__main__":
    unittest.main()
