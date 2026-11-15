"""Installer + packaging pins: the lessons that must not regress.

- The installed Qt distribution is PySide6-Essentials, not "PySide6"
  (importlib.metadata.version("PySide6") fails on an Essentials-only
  install even though `import PySide6` works — the install sim caught
  this on the first run).
- The app name + version live only in qwkhnd/__init__.py: no other
  Python file may carry them as literals.
- The .desktop Exec lines carry no nested escaped quotes (GLib's
  desktop parser rejects the whole file when they appear).
- install.sh is BASH, the repo has a secrets .gitignore + MIT LICENSE.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "qwkhnd")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class DistributionNameTests(unittest.TestCase):
    def test_installer_checks_essentials_distribution(self):
        text = _read("install.sh")
        self.assertIn("PySide6-Essentials", text)
        # The bare distribution name must not be metadata-checked in
        # live code (the NOTE comment explains the trap, so comments
        # are stripped before asserting).
        code = "\n".join(line for line in text.splitlines()
                         if not line.strip().startswith("#"))
        self.assertNotIn('("PySide6", "pypdf")', code)
        self.assertNotIn("metadata.version(\"PySide6\")", code)

    def test_app_registers_essentials_distribution(self):
        text = _read("qwkhnd/app.py")
        self.assertIn('register_dependency("PySide6-Essentials")', text)

    def test_requirements_match(self):
        text = _read("requirements.txt")
        self.assertIn("PySide6-Essentials", text)
        self.assertIn("pypdf", text)


class SingleSourceTests(unittest.TestCase):
    def test_no_other_python_file_hardcodes_name_or_version(self):
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            text = _read(os.path.join("qwkhnd", name))
            self.assertNotRegex(
                text, r"""["']Qwkhnd["']""",
                "%s hardcodes the app name" % name)
            self.assertNotRegex(
                text, r"""["']0\.2["']""",
                "%s hardcodes the version" % name)

    def test_init_is_the_single_source(self):
        from qwkhnd import APP_ID, APP_NAME, VERSION
        self.assertEqual(APP_NAME, "Qwkhnd")
        self.assertEqual(APP_ID, "qwkhnd")
        self.assertEqual(VERSION, "0.2")

    def test_help_text_uses_the_single_source(self):
        from qwkhnd import APP_NAME, VERSION
        from qwkhnd.app import help_text
        text = help_text()
        self.assertIn(APP_NAME, text)
        self.assertIn("v%s" % VERSION, text)


class DesktopFileTests(unittest.TestCase):
    def test_exec_has_no_nested_escaped_quotes(self):
        for name in ("Qwkhnd.desktop", "Install-Qwkhnd.desktop"):
            text = _read(name)
            exec_line = [line for line in text.splitlines()
                         if line.startswith("Exec=")][0]
            self.assertNotIn('\\"', exec_line, name)

    def test_desktop_files_have_wmclass_and_icon(self):
        text = _read("Qwkhnd.desktop")
        self.assertIn("StartupWMClass=Qwkhnd", text)
        self.assertIn("Icon=__APP_DIR__/icons/qwkhnd-48.png", text)
        self.assertIn("Terminal=false", text)

    def test_main_desktop_bakes_app_dir_instead_of_percent_k(self):
        # %k expands to the desktop file's own path; the installed
        # copy lives in ~/.local/share/applications, where run.sh
        # is not. The app dir must be baked in by install.sh.
        text = _read("Qwkhnd.desktop")
        exec_line = [line for line in text.splitlines()
                     if line.startswith("Exec=")][0]
        self.assertIn("__APP_DIR__/run.sh", exec_line)
        self.assertNotIn("%k", exec_line)

    def test_install_desktop_keeps_percent_k(self):
        # The installer desktop lives in the app folder next to
        # install.sh, so %k genuinely resolves to the app dir there.
        text = _read("Install-Qwkhnd.desktop")
        exec_line = [line for line in text.splitlines()
                     if line.startswith("Exec=")][0]
        self.assertIn("%k", exec_line)
        self.assertIn("install.sh", exec_line)


class RepoHygieneTests(unittest.TestCase):
    def test_install_sh_is_bash(self):
        text = _read("install.sh")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn("sudo apt install python3-venv", text)

    def test_gitignore_covers_secrets(self):
        text = _read(".gitignore")
        for fragment in (".env", "*.key", "*.pem", "providers.json",
                         "credentials*", "*secret*"):
            self.assertIn(fragment, text)

    def test_license_is_mit_for_joshua(self):
        text = _read("LICENSE")
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 Joshua Lofland", text)

    def test_build_zip_lists_every_shipped_file(self):
        # Every file build_zip.py names must exist in the tree.
        text = _read("build_zip.py")
        names = set(re.findall(r'"([^"]+\.[a-z0-9]+)"', text))
        # "%s-v%s.zip" is a format string, not a filename.
        names = {n for n in names if "%" not in n}
        missing = [n for n in sorted(names)
                   if not os.path.exists(os.path.join(ROOT, n))]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
