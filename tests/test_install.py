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
import shutil
import subprocess
import sys
import tempfile
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

    def test_requirements_are_pinned(self):
        # T07: every requirement pins the version the install sim
        # verified, so a future install cannot pull untested code.
        text = _read("requirements.txt")
        self.assertIn("PySide6-Essentials==6.12.0", text)
        self.assertIn("pypdf==7.1.0", text)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertIn("==", line, line)


class SingleSourceTests(unittest.TestCase):
    def test_no_other_python_file_hardcodes_name_or_version(self):
        from qwkhnd import VERSION
        version_pat = r"""["']%s["']""" % re.escape(VERSION)
        for name in sorted(os.listdir(PACKAGE)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            text = _read(os.path.join("qwkhnd", name))
            self.assertNotRegex(
                text, r"""["']Qwkhnd["']""",
                "%s hardcodes the app name" % name)
            self.assertNotRegex(
                text, version_pat,
                "%s hardcodes the version" % name)

    def test_init_is_the_single_source(self):
        from qwkhnd import APP_ID, APP_NAME, VERSION
        self.assertEqual(APP_NAME, "Qwkhnd")
        self.assertEqual(APP_ID, "qwkhnd")
        self.assertEqual(VERSION, "0.4")

    def test_help_text_uses_the_single_source(self):
        from qwkhnd import APP_NAME, VERSION
        from qwkhnd.app import help_text
        text = help_text()
        self.assertIn(APP_NAME, text)
        self.assertIn("v%s" % VERSION, text)


class DesktopFileTests(unittest.TestCase):
    def test_exec_has_no_nested_escaped_quotes(self):
        for name in ("Qwkhnd.desktop", "Install-Qwkhnd.desktop",
                     "Uninstall-Qwkhnd.desktop"):
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

    def test_main_desktop_calls_run_sh_directly(self):
        # T19: no python3 -c wrapper around run.sh.
        text = _read("Qwkhnd.desktop")
        exec_line = [line for line in text.splitlines()
                     if line.startswith("Exec=")][0]
        self.assertEqual(exec_line, "Exec=__APP_DIR__/run.sh")


class LauncherTests(unittest.TestCase):
    """T19: the launcher captures a failed start, and the
    installer names the real missing library."""

    def test_run_sh_captures_startup_error(self):
        text = _read("run.sh")
        self.assertIn("startup-error.txt", text)
        self.assertIn("Qwkhnd/logs", text)
        # A good start removes a stale error file.
        self.assertIn('rm -f "$TMP_ERROR" "$ERROR_FILE"', text)

    def test_install_names_missing_library(self):
        text = _read("install.sh")
        self.assertIn("The missing library is", text)
        self.assertIn('libxkbcommon.so*) package="libxkbcommon0"',
                      text)
        self.assertIn('libxcb-cursor.so*) package="libxcb-cursor0"',
                      text)
        self.assertIn('libEGL.so*) package="libegl1"', text)

    def test_install_pip_failure_is_plain_words(self):
        text = _read("install.sh")
        self.assertIn("Installing Qwkhnd's libraries failed.", text)
        self.assertIn("no internet connection", text)
        self.assertIn("run install.sh again", text)


class UninstallTests(unittest.TestCase):
    """T24: the uninstaller removes the install, and only ever
    removes the user's files when asked."""

    def test_uninstall_script_is_bash(self):
        text = _read("uninstall.sh")
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))

    def test_uninstall_removes_the_install(self):
        text = _read("uninstall.sh")
        self.assertIn('rm -rf "$DIR/.venv"', text)
        self.assertIn(
            'rm -f "$HOME/.local/share/applications/Qwkhnd.desktop"',
            text)
        self.assertIn('rm -f "$HOME/Desktop/Qwkhnd.desktop"', text)
        self.assertIn('rm -f "$HOME/.local/bin/qwkhnd"', text)

    def test_uninstall_never_deletes_data_unasked(self):
        # ~/Qwkhnd is only removed inside the "yes" branch of the
        # question, never on its own.
        text = _read("uninstall.sh")
        self.assertIn("Delete them too? [y/N]", text)
        yes_at = text.index("y|Y|yes|YES")
        rm_at = text.index('rm -rf "$HOME/Qwkhnd"')
        self.assertLess(yes_at, rm_at)
        self.assertIn("left alone", text)

    def test_uninstall_desktop_runs_uninstall_sh(self):
        text = _read("Uninstall-Qwkhnd.desktop")
        exec_line = [line for line in text.splitlines()
                     if line.startswith("Exec=")][0]
        self.assertIn("uninstall.sh", exec_line)
        self.assertIn("%k", exec_line)
        self.assertIn("Terminal=true", text)


class RenderIconsTests(unittest.TestCase):
    """T20: the icon renderer falls back to the painter when the
    SVG is corrupt, and says so plainly when the SVG is missing.
    Run in a subprocess, in a copied tree: creating a second
    QGuiApplication in-process is unsafe, and the tests corrupt
    the SVG."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = os.path.join(self.tmp.name, "tree")
        shutil.copytree(
            ROOT, self.tree,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.zip", ".venv", "*.pyc"))
        for name in ("icons/qwkhnd-48.png", "icons/qwkhnd-256.png"):
            path = os.path.join(self.tree, name)
            if os.path.exists(path):
                os.remove(path)

    def tearDown(self):
        self.tmp.cleanup()

    def _run_renderer(self):
        return subprocess.run(
            [sys.executable, "render_icons.py"],
            cwd=self.tree, capture_output=True, text=True,
            timeout=120)

    def _png_sizes(self):
        sizes = []
        for name in ("icons/qwkhnd-48.png", "icons/qwkhnd-256.png"):
            path = os.path.join(self.tree, name)
            sizes.append(os.path.getsize(path) if os.path.exists(path)
                         else 0)
        return sizes

    def test_valid_svg_renders(self):
        result = self._run_renderer()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("renderer: svg", result.stdout)
        self.assertTrue(all(size > 100
                            for size in self._png_sizes()))

    def test_corrupt_svg_falls_back_to_painter(self):
        with open(os.path.join(self.tree, "icons", "qwkhnd.svg"),
                  "w", encoding="utf-8") as fh:
            fh.write("<svg><not closed")
        result = self._run_renderer()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("renderer: painter", result.stdout)
        self.assertTrue(all(size > 100
                            for size in self._png_sizes()))

    def test_missing_svg_is_a_plain_error(self):
        os.remove(os.path.join(self.tree, "icons", "qwkhnd.svg"))
        result = self._run_renderer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


class RepoHygieneTests(unittest.TestCase):
    def test_install_checks_python_floor(self):
        # T25: Python 3.10 or newer, with a plain-words error.
        text = _read("install.sh")
        self.assertIn("sys.version_info >= (3, 10)", text)
        self.assertIn("Qwkhnd needs Python 3.10 or newer.", text)

    def test_readme_states_python_floor(self):
        text = _read("README.md")
        self.assertIn("Python 3.10 or newer", text)

    def test_readme_has_troubleshooting(self):
        # T25: the three common failures, in plain words.
        text = _read("README.md")
        self.assertIn("## Troubleshooting", text)
        self.assertIn("will not start from the menu icon", text)
        self.assertIn("startup-error.txt", text)
        self.assertIn("saved dictionary was damaged", text)
        self.assertIn("Restore previous dictionary", text)
        self.assertIn("folder moved", text)

    def test_readme_has_no_hardcoded_test_count(self):
        # T25: the count went stale in v0.2 (150 vs 151), so the
        # README no longer states one.
        text = _read("README.md")
        self.assertNotRegex(text, r"\(\d+ tests")

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

    def test_every_tree_file_is_in_the_manifest(self):
        # T23, reverse direction: a file added to the tree but
        # not to the manifest would silently never ship.
        sys.path.insert(0, ROOT)
        import build_zip
        manifest = (set(build_zip.EXEC_FILES)
                    | set(build_zip.PLAIN_FILES))
        unlisted = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".venv",
                                        ".git")]
            for name in filenames:
                if name.endswith(".zip"):
                    continue  # the built zip itself
                if name.startswith(".") and name != ".gitignore":
                    continue
                rel = os.path.relpath(
                    os.path.join(dirpath, name), ROOT)
                if rel not in manifest:
                    unlisted.append(rel)
        self.assertEqual(unlisted, [])

    def test_zip_uses_a_fixed_timestamp(self):
        # T23: the same tree must always build the same zip.
        text = _read("build_zip.py")
        self.assertIn("info.date_time = (1980, 1, 1, 0, 0, 0)",
                      text)


if __name__ == "__main__":
    unittest.main()
