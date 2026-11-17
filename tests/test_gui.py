"""GUI tests (offscreen): the window drives a real rebuild.

The rebuild runs on a worker thread, so rebuild tests wait for
the window's _rebuild_done flag instead of assuming the click
finished the work. v0.2 adds: the first-run samples + checklist,
progressive disclosure, the Try it window, the bento results,
the inline notice, search + Show all, state preservation, the
accessibility presets, keyboard shortcuts, and the stylesheet.

NOTE: creating a MainWindow on a fresh data dir adds the 3 sample
files to the Source Material folder, so _fill_source() + rebuild
reads 7 files (3 samples + 4 fixtures), not 4.
"""

import glob
import json
import logging
import os
import re
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QMimeData, QPropertyAnimation, QTimer, Qt, QUrl)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableView, QWidget)

from fixtures import write_minimal_docx, write_minimal_pdf  # noqa: E402
from qwkhnd import APP_NAME, VERSION  # noqa: E402
from qwkhnd.app import (  # noqa: E402
    SAMPLE_DIR, SAMPLE_FILES, MainWindow, SingleInstance, app_icon,
    help_text, quick_start_text, stylesheet)
from qwkhnd.engine import (  # noqa: E402
    BuildReport, QwkhndDictionary, build_from_folder)

_app = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    _app.setStyleSheet(stylesheet(False))


def _pump():
    _app.processEvents()


class GuiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.settings_path = os.path.join(self.tmp.name, "settings.ini")
        self.window = MainWindow(data_dir=self.data_dir,
                                 settings_path=self.settings_path)
        self.window.show()
        _pump()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        _pump()
        # A preset test may have left the shared app stylesheet big.
        _app.setStyleSheet(stylesheet(False))
        # Each window adds handlers to the shared debug logger; close
        # them so later tests do not write into a deleted temp dir.
        logger = logging.getLogger("debug_log.qwkhnd")
        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)
        self.tmp.cleanup()

    def _source_folder(self):
        return os.path.join(self.data_dir, "Source Material")

    def _wait_for_rebuild(self, timeout_ms=60000):
        """Pump until the worker reports done. Returns the finish time."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while not self.window._rebuild_done:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("rebuild did not finish in %d ms"
                          % timeout_ms)
        return time.monotonic()

    def _wait_for_progress(self, timeout_ms=15000):
        """Pump until the progress bar has moved (rebuild under way).
        15 s, like _wait_for_rebuild: under suite load the worker
        can take a while to emit its first progress signal."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while self.window.progress_bar.value() == 0:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("no rebuild progress seen in %d ms"
                          % timeout_ms)

    def _cell(self, row, column=0):
        """The text of a table cell, through the model (T03)."""
        return self.window.table.model().index(row, column).data()

    def _row_count(self):
        return self.window.table.model().rowCount()

    def _wait_for_search(self, timeout_ms=2000):
        """Pump until the debounced search refill has run (T04)."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while self.window._search_timer.isActive():
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("search did not settle in %d ms"
                          % timeout_ms)
        _pump()

    def _fill_source(self):
        folder = self._source_folder()
        with open(os.path.join(folder, "a.txt"), "w") as fh:
            fh.write("the quick brown fox " * 10)
        with open(os.path.join(folder, "b.md"), "w") as fh:
            fh.write("the lazy dog " * 5)
        write_minimal_pdf(os.path.join(folder, "doc.pdf"),
                          ["the quick brown fox",
                           "jumps over the lazy dog"])
        write_minimal_docx(os.path.join(folder, "doc.docx"),
                           ["First paragraph here.",
                            "Second paragraph here."])
        with open(os.path.join(folder, "photo.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    def _open_tryit(self):
        """Open the Try it window via the button; return it."""
        self.window.tryit_button.click()
        _pump()
        tryit = self.window._tryit_window
        self.assertIsNotNone(tryit)
        self.assertTrue(tryit.isVisible())
        return tryit

    def _open_tryit_via_menu(self):
        """Open the Try it window via the View menu action.

        The button is disabled without a dictionary, so the menu
        is the only path before the first rebuild."""
        self.window.tryit_action.trigger()
        _pump()
        tryit = self.window._tryit_window
        self.assertIsNotNone(tryit)
        self.assertTrue(tryit.isVisible())
        return tryit


class WindowTests(GuiTestCase):
    def test_title_has_name_and_version(self):
        self.assertIn(APP_NAME, self.window.windowTitle())
        self.assertIn(VERSION, self.window.windowTitle())

    def test_default_source_folder_created(self):
        self.assertTrue(os.path.isdir(self._source_folder()))
        self.assertEqual(self.window.folder_edit.text(),
                         self._source_folder())

    def test_window_has_an_icon(self):
        # T2: v0.1 never called setWindowIcon.
        self.assertFalse(app_icon().isNull())
        self.assertFalse(self.window.windowIcon().isNull())

    def test_no_ampersand_in_visible_text(self):
        # Qt eats a bare "&" in button/tab text (mnemonic marker), so
        # no visible label may contain one.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        for window in (self.window, tryit):
            for button in window.findChildren(QPushButton):
                self.assertNotIn("&", button.text(), button.text())
        for index in range(self.window.tabs.count()):
            self.assertNotIn("&",
                             self.window.tabs.tabText(index))
        for action in self.window.menuBar().actions():
            self.assertNotIn("&", action.text(), action.text())
            menu = action.menu()
            if menu is not None:
                for sub in menu.actions():
                    self.assertNotIn("&", sub.text(), sub.text())
        tryit.close()

    def test_no_em_dash_in_visible_text(self):
        # U33: no em-dash in any visible string, including strings
        # that only appear after a rebuild (bento, sample, skipped
        # list, notice) and in the Try it window.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        self.window._show_notice("Test notice for the scan.")
        texts = []
        for window in (self.window, tryit):
            for widget in window.findChildren(QWidget):
                getter = getattr(widget, "text", None)
                if callable(getter):
                    try:
                        texts.append((repr(widget), getter()))
                    except Exception:
                        pass
                placeholder = getattr(widget, "placeholderText",
                                      None)
                if callable(placeholder):
                    texts.append((repr(widget), placeholder()))
        for index in range(self.window.tabs.count()):
            texts.append(("tab %d" % index,
                          self.window.tabs.tabText(index)))
        model = self.window.table.model()
        for index in range(model.columnCount()):
            texts.append(("header %d" % index,
                          model.headerData(index, Qt.Horizontal)))
        for index in range(self.window.skipped_list.count()):
            texts.append(("skipped %d" % index,
                          self.window.skipped_list.item(index).text()))
        for action in self.window.menuBar().actions():
            texts.append(("menu", action.text()))
            menu = action.menu()
            if menu is not None:
                for sub in menu.actions():
                    texts.append(("menu item", sub.text()))
        texts.append(("help", help_text()))
        texts.append(("quick start", quick_start_text()))
        texts.append(("status",
                      self.window.statusBar().currentMessage()))
        texts.append(("sample", self.window.sample_label.text()))
        texts.append(("hero", self.window.hero_value.text()))
        texts.append(("hero sub", self.window.hero_sub.text()))
        texts.append(("notice", self.window.notice_label.text()))
        for name in SAMPLE_FILES:
            with open(os.path.join(SAMPLE_DIR, name),
                      encoding="utf-8") as fh:
                texts.append(("sample " + name, fh.read()))
        for where, text in texts:
            self.assertNotIn("\u2014", text, where)
        tryit.close()

    def test_rebuild_populates_bento_table_and_skipped(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        # 3 samples + 4 fixtures read, 1 skipped.
        self.assertEqual(self.window.files_value.text(), "7")
        self.assertEqual(self.window.skipped_link.text(), "1 skipped")
        self.assertTrue(self.window.skipped_link.isVisible())
        self.assertNotEqual(self.window.codes_value.text(), "0")
        self.assertGreater(self._row_count(), 0)
        self.assertEqual(self._cell(0, 0), "the")
        self.assertEqual(
            self._cell(0, 1),
            "~" + self.window.dictionary.word_to_code["the"])
        skipped = [self.window.skipped_list.item(i).text()
                   for i in range(self.window.skipped_list.count())]
        self.assertEqual(len(skipped), 1)
        self.assertIn("photo.png", skipped[0])
        self.assertIn("OCR", skipped[0])
        self.assertIn("%", self.window.hero_value.text())
        self.assertIn("characters saved",
                      self.window.hero_sub.text())
        self.assertIn("->", self.window.sample_label.text())
        index = self.window.tabs.indexOf(
            self.window._skipped_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Skipped files (1)")

    def test_rebuild_empty_folder_is_not_a_crash(self):
        # The samples must go first: a truly empty folder is what
        # this test is about (a user who deleted them).
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertEqual(self.window.files_value.text(), "0")
        self.assertEqual(self._row_count(), 0)
        self.assertIn("No readable text",
                      self.window.statusBar().currentMessage())
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("No readable text",
                      self.window.notice_label.text())

    def test_rebuild_missing_folder_is_not_a_crash(self):
        self.window.folder_edit.setText(
            os.path.join(self.tmp.name, "does-not-exist"))
        self.window.rebuild_button.click()
        _pump()
        self.assertIn("does not exist",
                      self.window.statusBar().currentMessage())
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("does not exist",
                      self.window.notice_label.text())

    def test_rebuild_runs_off_the_ui_thread(self):
        # U30: the build runs in a worker thread, and the UI event
        # loop keeps running while it does (a timer scheduled before
        # the click fires before the rebuild finishes).
        import qwkhnd.app as app_module
        main_ident = threading.get_ident()
        real_build = app_module.build_from_folder
        seen = {}
        release = threading.Event()

        def slow_build(folder, log=None, progress=None,
                       cancelled=None, file_progress=None):
            seen["ident"] = threading.get_ident()
            if progress is not None:
                progress(1, 5, "file0.txt")
            # Wait until the test has seen the progress: under
            # load the main thread may not pump for seconds, and
            # a fast mock would finish before it ever looks.
            release.wait(timeout=30)
            for step in range(1, 5):
                if progress is not None:
                    progress(step + 1, 5, "file%d.txt" % step)
                time.sleep(0.05)
            return real_build(folder, log=log)

        marks = {}
        self._fill_source()
        with mock.patch.object(app_module, "build_from_folder",
                               slow_build):
            QTimer.singleShot(20, lambda: marks.setdefault(
                "timer", time.monotonic()))
            self.window.rebuild_button.click()
            self._wait_for_progress()
            # Mid-rebuild: the UI is alive and showing progress.
            self.assertEqual(self.window.activity_text.text(),
                             "Working...")
            self.assertTrue(self.window.cancel_button.isEnabled())
            self.assertFalse(self.window.rebuild_button.isEnabled())
            self.assertGreater(self.window.progress_bar.value(), 0)
            release.set()
            finished_at = self._wait_for_rebuild()
        self.assertIn("ident", seen)
        self.assertNotEqual(seen["ident"], main_ident)
        self.assertIn("timer", marks)
        self.assertLess(marks["timer"], finished_at)
        self.assertEqual(self.window.files_value.text(), "7")
        self.assertEqual(self.window.activity_text.text(), "Ready")
        self.assertFalse(self.window.cancel_button.isEnabled())

    def test_cancel_stops_the_rebuild(self):
        # U26: Cancel stops the build, and the old dictionary stays.
        import qwkhnd.app as app_module
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        before = dict(self.window.dictionary.word_to_code)
        self.assertTrue(before)

        release = threading.Event()

        def slow_cancel(folder, log=None, progress=None,
                        cancelled=None, file_progress=None):
            if progress is not None:
                progress(1, 100, "file.txt")
            # Wait until the test has seen the progress (see
            # test_rebuild_runs_off_the_ui_thread).
            release.wait(timeout=30)
            for step in range(1, 100):
                if cancelled is not None and cancelled():
                    report = BuildReport()
                    report.cancelled = True
                    return QwkhndDictionary(), report
                if progress is not None:
                    progress(step + 1, 100, "file.txt")
                time.sleep(0.02)
            return build_from_folder(folder, log=log)

        with mock.patch.object(app_module, "build_from_folder",
                               slow_cancel):
            self.window.rebuild_button.click()
            self._wait_for_progress()
            self.assertTrue(self.window.cancel_button.isEnabled())
            self.window.cancel_button.click()
            release.set()
            self._wait_for_rebuild()
        self.assertEqual(self.window.dictionary.word_to_code, before)
        self.assertIn("cancelled",
                      self.window.statusBar().currentMessage().lower())
        self.assertEqual(self.window.activity_text.text(), "Ready")

    def test_how_to_use_window_opens_from_menu(self):
        # U22: the Help menu opens a How to Use window.
        help_menu = None
        for action in self.window.menuBar().actions():
            if action.text() == "Help":
                help_menu = action.menu()
        self.assertIsNotNone(help_menu)
        actions = {a.text(): a for a in help_menu.actions()}
        self.assertIn("How to Use", actions)
        actions["How to Use"].trigger()
        QTest.qWait(50)
        howto = self.window._howto_window
        self.assertIsNotNone(howto)
        self.assertTrue(howto.isVisible())
        view = howto.findChildren(QPlainTextEdit)[0]
        text = view.toPlainText()
        self.assertIn("How to use", text)
        self.assertIn("Rebuild dictionary", text)
        self.assertIn("Cancel", text)
        self.assertNotIn("\u2014", text)
        howto.close()

    def test_geometry_remembered(self):
        # U5: the window size survives a restart. Offscreen the
        # virtual screen is 800 px wide, so the width is clamped to
        # the 820 px minimum and only the height can prove the
        # restore (on his 1366 px screen the width restores too).
        self.window.resize(1100, 630)
        QTest.qWait(50)
        self.window.close()
        QTest.qWait(50)
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        QTest.qWait(50)
        try:
            self.assertEqual(second.height(), 630)
            self.assertGreaterEqual(second.width(), 820)
        finally:
            second.close()
            second.deleteLater()
            QTest.qWait(50)

    def test_export_json_and_text(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        json_path = os.path.join(self.tmp.name, "out.json")
        text_path = os.path.join(self.tmp.name, "out.txt")
        with mock.patch(
                "qwkhnd.app.QFileDialog.getSaveFileName",
                return_value=(json_path, "")):
            self.window.export_json_button.click()
        _pump()
        self.assertTrue(os.path.exists(json_path))
        with open(json_path, encoding="utf-8") as fh:
            self.assertIn('"word": "the"', fh.read())
        with mock.patch(
                "qwkhnd.app.QFileDialog.getSaveFileName",
                return_value=(text_path, "")):
            self.window.export_text_button.click()
        _pump()
        self.assertTrue(os.path.exists(text_path))
        with open(text_path, encoding="utf-8") as fh:
            self.assertIn(
                "the -> ~%s"
                % self.window.dictionary.word_to_code["the"],
                fh.read())

    def test_debug_report_button_writes_a_report(self):
        self.window.debug_button.click()
        _pump()
        reports = glob.glob(os.path.join(
            self.data_dir, "logs", "debug-report-*.txt"))
        self.assertEqual(len(reports), 1)
        with open(reports[0], encoding="utf-8") as fh:
            self.assertIn("Qwkhnd %s" % VERSION, fh.read())
        self.assertIn("Debug report saved",
                      self.window.statusBar().currentMessage())

    def test_saved_dictionary_loads_on_next_start(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(os.path.exists(
            os.path.join(self.data_dir, "qwkhnd-dictionary.json")))
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertTrue(second.results_area.isVisible())
            model = second.table.model()
            self.assertGreater(model.rowCount(), 0)
            self.assertEqual(model.index(0, 0).data(), "the")
            self.assertNotEqual(second.codes_value.text(), "0")
            self.assertIn("%", second.hero_value.text())
        finally:
            second.close()
            second.deleteLater()
            _pump()


class CorruptDictionaryTests(GuiTestCase):
    """T01: a damaged saved dictionary starts empty with a notice,
    never a crash before the window opens."""

    def _start_with_dict_file(self, content):
        data_dir = os.path.join(self.tmp.name, "data-corrupt")
        os.makedirs(os.path.join(data_dir, "Source Material"))
        with open(os.path.join(data_dir, "qwkhnd-dictionary.json"),
                  "w", encoding="utf-8") as fh:
            fh.write(content)
        window = MainWindow(
            data_dir=data_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings-corrupt.ini"))
        window.show()
        _pump()
        return window

    def _close(self, window):
        window.close()
        window.deleteLater()
        _pump()

    def test_truncated_json_starts_empty_with_notice(self):
        window = self._start_with_dict_file('{"app": "Qwkhnd", "en')
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
            self.assertIn("damaged", window.notice_label.text())
            self.assertIn("Rebuild", window.notice_label.text())
            self.assertFalse(window.results_area.isVisible())
        finally:
            self._close(window)

    def test_wrong_shape_starts_empty_with_notice(self):
        window = self._start_with_dict_file('[{"word": "the"}]')
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
            self.assertIn("damaged", window.notice_label.text())
        finally:
            self._close(window)

    def test_duplicate_codes_start_empty_with_notice(self):
        content = json.dumps(
            {"app": "Qwkhnd", "version": "0.3", "marker": "~",
             "entries": [{"word": "first", "code": "a"},
                         {"word": "second", "code": "a"}]})
        window = self._start_with_dict_file(content)
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
        finally:
            self._close(window)

    def test_missing_code_starts_empty_with_notice(self):
        content = json.dumps(
            {"app": "Qwkhnd", "version": "0.3", "marker": "~",
             "entries": [{"word": "the"}]})
        window = self._start_with_dict_file(content)
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
        finally:
            self._close(window)


class FirstRunTests(GuiTestCase):
    """T1: sample files + getting-started checklist."""

    def test_samples_added_on_first_run(self):
        folder = self._source_folder()
        for name in SAMPLE_FILES:
            path = os.path.join(folder, name)
            self.assertTrue(os.path.exists(path), name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            # Real prose about Qwkhnd, not lorem ipsum.
            self.assertIn("Qwkhnd", text)
            self.assertGreater(len(text.split()), 100)
            self.assertNotIn("\u2014", text)
            self.assertNotIn("&", text)

    def test_samples_not_readded_after_deletion(self):
        folder = self._source_folder()
        for name in SAMPLE_FILES:
            os.remove(os.path.join(folder, name))
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            for name in SAMPLE_FILES:
                self.assertFalse(
                    os.path.exists(os.path.join(folder, name)), name)
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_samples_not_added_when_folder_not_empty(self):
        data_dir = os.path.join(self.tmp.name, "data2")
        folder = os.path.join(data_dir, "Source Material")
        os.makedirs(folder)
        with open(os.path.join(folder, "mine.txt"), "w") as fh:
            fh.write("my own words here")
        window = MainWindow(
            data_dir=data_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings2.ini"))
        window.show()
        _pump()
        try:
            for name in SAMPLE_FILES:
                self.assertFalse(
                    os.path.exists(os.path.join(folder, name)), name)
        finally:
            window.close()
            window.deleteLater()
            _pump()

    def test_samples_not_added_when_dictionary_exists(self):
        # Build a dictionary, then start fresh settings: the dict
        # file exists, so no samples.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        self.window.close()
        _pump()
        window = MainWindow(
            data_dir=self.data_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings-fresh.ini"))
        window.show()
        _pump()
        try:
            for name in SAMPLE_FILES:
                self.assertFalse(
                    os.path.exists(os.path.join(folder, name)), name)
        finally:
            window.close()
            window.deleteLater()
            _pump()

    def test_checklist_visible_on_first_run(self):
        self.assertTrue(self.window.checklist_frame.isVisible())
        # Step 1 honestly ticked: the samples are in the folder.
        self.assertTrue(
            self.window.check_step1.text().startswith("\u2713"))
        self.assertTrue(
            self.window.check_step2.text().startswith("\u25cb"))
        self.assertTrue(
            self.window.check_step3.text().startswith("\u25cb"))
        self.assertIn("Rebuild", self.window.check_step2.text())
        self.assertIn("Try it", self.window.check_step3.text())

    def test_checklist_dismiss_never_returns(self):
        self.window.checklist_dismiss.click()
        _pump()
        self.assertFalse(self.window.checklist_frame.isVisible())
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertFalse(second.checklist_frame.isVisible())
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_checklist_goes_away_after_first_rebuild(self):
        self.assertTrue(self.window.checklist_frame.isVisible())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertFalse(self.window.checklist_frame.isVisible())
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertFalse(second.checklist_frame.isVisible())
        finally:
            second.close()
            second.deleteLater()
            _pump()


class DisclosureTests(GuiTestCase):
    """T3: the first screen is three choices; results appear after
    the first rebuild; Try it is its own window."""

    def test_first_screen_shows_only_folder_rebuild_checklist(self):
        self.assertFalse(self.window.results_area.isVisible())
        self.assertTrue(self.window.checklist_frame.isVisible())
        self.assertTrue(self.window.folder_edit.isVisible())
        self.assertTrue(self.window.rebuild_button.isVisible())

    def test_results_appear_after_first_rebuild(self):
        self.assertFalse(self.window.results_area.isVisible())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window.results_area.isVisible())
        self.assertTrue(self.window.tabs.isVisible())
        self.assertTrue(self.window.tryit_button.isVisible())
        self.assertTrue(self.window.export_json_button.isVisible())
        self.assertTrue(self.window.debug_button.isVisible())

    def test_results_visible_at_once_with_saved_dictionary(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertTrue(second.results_area.isVisible())
            self.assertFalse(second.checklist_frame.isVisible())
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_no_tryit_tab(self):
        labels = [self.window.tabs.tabText(i)
                  for i in range(self.window.tabs.count())]
        self.assertEqual(labels,
                         ["Dictionary", "Skipped files", "Help"])

    def test_tryit_opens_from_button_and_menu(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        tryit.close()
        _pump()
        # And from the View menu.
        view_menu = None
        for action in self.window.menuBar().actions():
            if action.text() == "View":
                view_menu = action.menu()
        self.assertIsNotNone(view_menu)
        actions = {a.text(): a for a in view_menu.actions()}
        self.assertIn("Try it", actions)
        actions["Try it"].trigger()
        QTest.qWait(50)
        self.assertIsNotNone(self.window._tryit_window)
        self.assertTrue(self.window._tryit_window.isVisible())
        self.window._tryit_window.close()


class SearchTests(GuiTestCase):
    """T4: search over the whole dictionary, Show all."""

    def _fill_many_words(self, count=150):
        folder = self._source_folder()
        words = ["term%03d" % i for i in range(count)]
        with open(os.path.join(folder, "many.txt"), "w") as fh:
            fh.write(" ".join(words))
        return words

    def test_default_view_is_top_100(self):
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertGreater(len(self.window.dictionary), 100)
        self.assertEqual(self._row_count(), 100)
        self.assertIn("top 100",
                      self.window.table_count_label.text())

    def test_show_all_shows_every_code(self):
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        total = len(self.window.dictionary)
        self.window.show_all_button.click()
        _pump()
        self.assertEqual(self._row_count(), total)
        self.assertEqual(self.window.show_all_button.text(),
                         "Top 100")
        self.window.show_all_button.click()
        _pump()
        self.assertEqual(self._row_count(), 100)
        self.assertEqual(self.window.show_all_button.text(),
                         "Show all")

    def test_search_finds_a_word_past_the_top_100(self):
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        entries = self.window._table_entries()
        beyond = entries[120][0]  # past the default top 100
        self.window.search_edit.setText(beyond)
        self._wait_for_search()
        shown = [self._cell(row)
                 for row in range(self._row_count())]
        self.assertIn(beyond, shown)

    def test_search_narrows_live(self):
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.search_edit.setText("term14")
        self._wait_for_search()
        # term140 through term149: 10 matches.
        self.assertEqual(self._row_count(), 10)
        self.assertIn("10 matches",
                      self.window.table_count_label.text())
        self.window.search_edit.setText("")
        self._wait_for_search()
        self.assertEqual(self._row_count(), 100)

    def test_search_singular_match_label(self):
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.search_edit.setText("term149")
        self._wait_for_search()
        self.assertEqual(self._row_count(), 1)
        self.assertIn("1 match for 'term149'",
                      self.window.table_count_label.text())

    def test_table_is_virtualized(self):
        # T03: the table is a view over a model, not a widget
        # with one item per cell.
        from qwkhnd.app import DictionaryTableModel
        self.assertIsInstance(self.window.table, QTableView)
        self.assertIsInstance(self.window.table.model(),
                              DictionaryTableModel)
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        model = self.window.table.model()
        self.assertEqual(model.columnCount(), 3)
        self.assertEqual(model.headerData(0, Qt.Horizontal),
                         "Word")
        self.assertEqual(model.headerData(1, Qt.Horizontal),
                         "Code")
        self.assertEqual(model.headerData(2, Qt.Horizontal),
                         "Times used")
        self.assertEqual(model.index(0, 0).data(), "the")

    def test_search_uses_cached_sort(self):
        # T04: the sort runs once per dictionary, not once per
        # keystroke; a rebuild drops the cache.
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        first = self.window._table_entries()
        second = self.window._table_entries()
        self.assertIs(first, second)
        self.assertIsNotNone(self.window._lower_words)
        self.assertEqual(len(self.window._lower_words),
                         len(first))
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIsNot(self.window._table_entries(), first)

    def test_search_debounces(self):
        # T04: typing starts the timer and the old results stay
        # visible until it fires.
        self._fill_many_words()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertEqual(self._row_count(), 100)
        self.window.search_edit.setText("term14")
        self.assertTrue(self.window._search_timer.isActive())
        self.assertEqual(self._row_count(), 100)
        self._wait_for_search()
        self.assertEqual(self._row_count(), 10)


class BentoTests(GuiTestCase):
    """T6: the bento results grid (entry 005 numbers)."""

    def test_bento_layout_numbers(self):
        grid = self.window.hero_tile.parent().layout()
        self.assertEqual(grid.spacing(), 16)
        row, column, rowspan, colspan = grid.getItemPosition(
            grid.indexOf(self.window.hero_tile))
        self.assertEqual((row, column, rowspan, colspan),
                         (0, 0, 1, 2))
        tiles = [self.window.hero_tile, self.window.files_tile,
                 self.window.words_tile, self.window.codes_tile,
                 self.window.sample_tile]
        self.assertEqual(len(tiles), 5)

    def test_bento_shows_the_rebuild(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("%", self.window.hero_value.text())
        self.assertRegex(self.window.hero_sub.text(),
                         r"\d+ characters saved")
        self.assertEqual(self.window.files_value.text(), "7")
        self.assertGreater(int(self.window.words_value.text()), 0)
        self.assertGreater(int(self.window.codes_value.text()), 0)
        self.assertIn("different", self.window.words_label.text())
        self.assertIn("100 characters",
                      self.window.sample_caption.text())
        self.assertIn("->", self.window.sample_label.text())


class FitTests(GuiTestCase):
    """T09: the window fits the screen under Big text, and the
    sample tile never clips."""

    def test_big_text_fits_the_screen(self):
        # The window minimum was 811 px tall under Big text on a
        # 768 px screen; the scrollable results area fixes it.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.big_text_action.trigger()
        _pump()
        self.assertLess(
            self.window.minimumSizeHint().height(), 768)

    def test_sample_never_clips(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        for width, big in ((1100, False), (1100, True), (820, True)):
            if big != self.window._big_text:
                self.window.big_text_action.trigger()
                _pump()
            self.window.resize(width, 720)
            QTest.qWait(100)
            label = self.window.sample_label
            needed = label.heightForWidth(label.width())
            self.assertGreaterEqual(
                label.height(), needed,
                "sample clips at width %d big %s" % (width, big))

    def test_results_area_scrolls(self):
        from PySide6.QtWidgets import QScrollArea
        self.assertIsInstance(self.window.results_area, QScrollArea)
        self.assertTrue(self.window.results_area.widgetResizable())


class PersistedBuildTests(GuiTestCase):
    """T10: the skipped list and the sample survive a restart."""

    def _rebuild_with_skipped_file(self):
        self._fill_source()
        with open(os.path.join(self._source_folder(), "photo.png"),
                  "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()

    def _open_second_window(self):
        window = MainWindow(
            data_dir=self.data_dir,
            settings_path=os.path.join(self.tmp.name, "second.ini"))
        window.show()
        _pump()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        return window

    def test_saved_dictionary_holds_skipped_and_sample(self):
        self._rebuild_with_skipped_file()
        with open(self.window.dict_path, encoding="utf-8") as fh:
            data = json.load(fh)
        build = data["build"]
        names = [entry[0] for entry in build["files_skipped_list"]]
        self.assertIn("photo.png", names)
        self.assertTrue(build["sample_before"])
        self.assertTrue(build["sample_after"])

    def test_restart_restores_skipped_and_sample(self):
        self._rebuild_with_skipped_file()
        window2 = self._open_second_window()
        self.assertGreater(window2.skipped_list.count(), 0)
        texts = [window2.skipped_list.item(i).text()
                 for i in range(window2.skipped_list.count())]
        self.assertTrue(any("photo.png" in text for text in texts))
        self.assertNotIn("Rebuild to see a sample",
                         window2.sample_label.text())
        self.assertIn("quick", window2.sample_label.text())

    def test_v02_file_without_new_keys_loads(self):
        # A v0.2 saved file has no files_skipped_list or sample
        # keys: it loads fine, with an empty skipped list and the
        # "Rebuild to see a sample" label.
        os.makedirs(self.data_dir, exist_ok=True)
        data = {
            "marker": "~",
            "version": "0.2",
            "entries": [{"word": "the", "code": "a", "count": 3}],
            "build": {"files_read": 1, "files_skipped": 0,
                      "total_words": 3, "unique_words": 1,
                      "sample_saved": 0, "sample_saved_pct": 0.0},
        }
        with open(self.window.dict_path, "w",
                  encoding="utf-8") as fh:
            json.dump(data, fh)
        window2 = self._open_second_window()
        self.assertEqual(window2.skipped_list.count(), 0)
        self.assertIn("Rebuild to see a sample",
                      window2.sample_label.text())
        self.assertEqual(window2.table.model().rowCount(), 1)


class RestoreTests(GuiTestCase):
    """T11: the previous dictionary is kept, and Restore brings
    it back. (The File menu action is wired in T15; these tests
    drive the restore itself.)"""

    def _rebuild_with(self, text):
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(text)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()

    def test_second_rebuild_keeps_previous(self):
        self._rebuild_with("the quick brown fox " * 10)
        self._rebuild_with("lazy dog sleeps soundly " * 10)
        self.assertTrue(
            os.path.exists(self.window.previous_dict_path))
        with open(self.window.previous_dict_path,
                  encoding="utf-8") as fh:
            data = json.load(fh)
        words = [entry["word"] for entry in data["entries"]]
        self.assertIn("quick", words)
        self.assertNotIn("lazy", words)

    def test_restore_brings_back_previous(self):
        self._rebuild_with("the quick brown fox " * 10)
        self._rebuild_with("lazy dog sleeps soundly " * 10)
        self.assertIn("lazy", self.window.dictionary.word_to_code)
        self.window._restore_previous_dictionary()
        self.assertIn("quick", self.window.dictionary.word_to_code)
        self.assertNotIn("lazy", self.window.dictionary.word_to_code)
        self.assertIn("Restored the previous dictionary",
                      self.window.statusBar().currentMessage())

    def test_restore_without_previous_does_nothing(self):
        self.assertFalse(
            os.path.exists(self.window.previous_dict_path))
        self.window._restore_previous_dictionary()
        self.assertEqual(len(self.window.dictionary), 0)

    def test_restore_damaged_previous_shows_notice(self):
        self._rebuild_with("the quick brown fox " * 10)
        self._rebuild_with("lazy dog sleeps soundly " * 10)
        with open(self.window.previous_dict_path, "w",
                  encoding="utf-8") as fh:
            fh.write("{ not json")
        self.window._restore_previous_dictionary()
        self.assertIn("lazy", self.window.dictionary.word_to_code)
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("damaged",
                      self.window.notice_label.text())


class NoticeTests(GuiTestCase):
    """T5: the inline notice for failures."""

    def test_missing_folder_shows_notice(self):
        self.window.folder_edit.setText(
            os.path.join(self.tmp.name, "does-not-exist"))
        self.window.rebuild_button.click()
        _pump()
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("does not exist",
                      self.window.notice_label.text())
        self.assertIn("Browse", self.window.notice_label.text())

    def test_empty_rebuild_shows_notice(self):
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("No readable text",
                      self.window.notice_label.text())

    def test_export_failure_shows_notice(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        path = os.path.join(self.tmp.name, "out.json")
        with mock.patch(
                "qwkhnd.app.QFileDialog.getSaveFileName",
                return_value=(path, "")), mock.patch.object(
                    QwkhndDictionary, "export_json",
                    side_effect=OSError("disk full")):
            self.window.export_json_button.click()
        _pump()
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("Could not write that file",
                      self.window.notice_label.text())

    def test_notice_dismisses_and_stays_dismissed(self):
        self.window._show_notice("Something went wrong.")
        self.assertTrue(self.window.notice_frame.isVisible())
        self.window.notice_dismiss.click()
        _pump()
        self.assertFalse(self.window.notice_frame.isVisible())
        QTest.qWait(200)
        self.assertFalse(self.window.notice_frame.isVisible())

    def test_notice_survives_a_status_message(self):
        self.window._show_notice("Something went wrong.")
        self.window.statusBar().showMessage("Another message")
        _pump()
        self.assertTrue(self.window.notice_frame.isVisible())


class SkippedBadgeTests(GuiTestCase):
    """T9: the skipped count is badged and linked."""

    def test_badge_and_link_after_rebuild(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        index = self.window.tabs.indexOf(
            self.window._skipped_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Skipped files (1)")
        self.assertEqual(self.window.skipped_link.text(), "1 skipped")
        self.assertTrue(self.window.skipped_link.isVisible())

    def test_no_badge_without_skips(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        index = self.window.tabs.indexOf(
            self.window._skipped_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Skipped files")
        self.assertFalse(self.window.skipped_link.isVisible())

    def test_skip_link_opens_the_skipped_tab(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.tabs.setCurrentIndex(0)
        self.window.skipped_link.click()
        _pump()
        self.assertEqual(
            self.window.tabs.currentWidget(),
            self.window._skipped_tab_widget)


class StateTests(GuiTestCase):
    """T7: the rebuild keeps the view; the tab is remembered."""

    def test_active_tab_remembered(self):
        self.window.tabs.setCurrentIndex(2)
        self.window.close()
        QTest.qWait(50)
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        QTest.qWait(50)
        try:
            self.assertEqual(second.tabs.currentIndex(), 2)
        finally:
            second.close()
            second.deleteLater()
            QTest.qWait(50)

    def test_selection_and_scroll_survive_rebuild(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertGreater(self._row_count(), 60)
        # Scroll row 49 to the top the way the view does it: a raw
        # scrollbar setValue is dropped by the view's lazy layout,
        # so the setup itself must go through scrollTo. T27: retry
        # the scrollTo until it sticks (the layout pass finishes
        # on its own schedule), not a fixed 100 ms. Waiting for
        # the scrollbar range to appear is not enough: the range
        # exists before scrollTo starts working.
        model = self.window.table.model()
        bar = self.window.table.verticalScrollBar()
        deadline = time.monotonic() + 5.0
        while bar.value() != 49:
            self.window.table.scrollTo(
                model.index(49, 0), QTableView.PositionAtTop)
            QTest.qWait(20)
            if time.monotonic() > deadline:
                break
        self.assertEqual(bar.value(), 49)
        # Select the top row itself: setCurrentIndex only scrolls
        # when the cell is not visible, so the scroll stays put.
        self.window.table.setCurrentIndex(model.index(49, 0))
        word = self._cell(49, 0)
        self.assertEqual(bar.value(), 49)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        # T27: wait for the scroll to be restored, not a fixed
        # 100 ms.
        bar = self.window.table.verticalScrollBar()
        deadline = time.monotonic() + 5.0
        while bar.value() != 49:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                break
        current = self.window.table.currentIndex().row()
        self.assertGreaterEqual(current, 0)
        self.assertEqual(self._cell(current, 0), word)
        self.assertEqual(
            self.window.table.verticalScrollBar().value(), 49)


class HelpSplitTests(GuiTestCase):
    """T8: the Help tab is the quick-start; the window is the full
    index. No sentence appears in both."""

    def test_help_tab_is_the_quick_start(self):
        help_tab = self.window._help_tab_widget
        view = help_tab.findChildren(QPlainTextEdit)[0]
        text = view.toPlainText()
        self.assertIn("Quick start", text)
        self.assertIn("Rebuild dictionary", text)
        self.assertIn("Try it window", text)
        self.assertNotIn("OCR", text)

    def test_how_to_use_window_keeps_the_limits(self):
        # T15: the window is an index now, so the test clicks
        # through every section and checks the joined text.
        self.window._show_how_to_use()
        _pump()
        howto = self.window._howto_window
        view = howto.findChildren(QPlainTextEdit)[0]
        seen = []
        for row in range(howto.section_list.count()):
            howto.section_list.setCurrentRow(row)
            _pump()
            seen.append(view.toPlainText())
        text = "\n".join(seen)
        self.assertIn("OCR", text)
        self.assertIn("offline", text)
        self.assertIn(".docx", text)
        howto.close()

    def test_how_to_use_index_switches_sections(self):
        # T15: the section list on the left, the text on the right.
        self.window._show_how_to_use()
        _pump()
        howto = self.window._howto_window
        titles = [howto.section_list.item(i).text()
                  for i in range(howto.section_list.count())]
        self.assertEqual(titles[0], "How to use")
        self.assertIn("What it reads", titles)
        self.assertIn("What it skips", titles)
        self.assertIn("Keyboard shortcuts", titles)
        howto.section_list.setCurrentRow(
            titles.index("What it skips"))
        _pump()
        self.assertIn("OCR",
                      howto.section_view.toPlainText())
        howto.section_list.setCurrentRow(0)
        _pump()
        self.assertIn("Rebuild dictionary",
                      howto.section_view.toPlainText())
        howto.close()

    def test_no_sentence_shared(self):
        def sentences(text):
            parts = re.split(r"[.\n]", text)
            return {part.strip() for part in parts
                    if len(part.split()) >= 4}

        shared = sentences(help_text()) & sentences(
            quick_start_text())
        self.assertEqual(shared, set())


class MotionTests(GuiTestCase):
    """T10: the button dip and the finish moment, under 300 ms,
    off under Reduced motion."""

    def test_rebuild_button_dips_and_returns(self):
        start = self.window.rebuild_button.geometry()
        self.window._dip_rebuild_button()
        anim = self.window._dip_anim
        self.assertIsNotNone(anim)
        self.assertEqual(anim.duration(), 150)
        # Wait for the animation to stop, not a fixed delay: under
        # suite load the timer can lag the wall clock.
        deadline = time.monotonic() + 2.0
        while anim.state() != QPropertyAnimation.State.Stopped:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("dip animation did not stop")
        self.assertEqual(self.window.rebuild_button.geometry(),
                         start)

    def test_no_motion_when_reduced_motion_on(self):
        self.window._reduced_motion = True
        self.window._dip_rebuild_button()
        self.assertIsNone(self.window._dip_anim)

    def test_finish_moment_ticks_up_then_settles(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIsNotNone(self.window._tick_anim)
        self.assertEqual(self.window._tick_anim.duration(), 250)
        # T27: wait for the animation to stop, not a fixed 400 ms:
        # under suite load the timer can lag the wall clock.
        anim = self.window._tick_anim
        deadline = time.monotonic() + 5.0
        while anim.state() != QPropertyAnimation.State.Stopped:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("tick animation did not stop")
        self.assertEqual(self.window.codes_value.text(),
                         str(len(self.window.dictionary)))

    def test_finish_moment_skipped_when_reduced_motion_on(self):
        self.window._reduced_motion = True
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIsNone(self.window._tick_anim)
        self.assertIsNone(self.window._hero_anim)
        self.assertEqual(self.window.codes_value.text(),
                         str(len(self.window.dictionary)))


class PresetTests(GuiTestCase):
    """T11: Big text and Reduced motion, one tap each, remembered."""

    def test_big_text_scales_the_stylesheet(self):
        # trigger() toggles a checkable action: no setChecked first.
        self.window.big_text_action.trigger()
        _pump()
        sheet = _app.styleSheet()
        self.assertIn("font-size: 14pt", sheet)
        self.assertIn("font-size: 34pt", sheet)
        self.assertTrue(self.window._big_text)
        self.window.big_text_action.trigger()
        _pump()
        self.assertIn("font-size: 11pt", _app.styleSheet())

    def test_presets_remembered(self):
        # trigger() toggles a checkable action: no setChecked first.
        self.window.big_text_action.trigger()
        self.window.reduced_motion_action.trigger()
        _pump()
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertTrue(second._big_text)
            self.assertTrue(second._reduced_motion)
            self.assertTrue(second.big_text_action.isChecked())
            self.assertTrue(
                second.reduced_motion_action.isChecked())
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_stylesheet_has_palette_and_focus_ring(self):
        sheet = stylesheet(False)
        self.assertIn("#14202e", sheet)
        self.assertIn("#f2c14e", sheet)
        self.assertIn("#7fd4ff", sheet)
        self.assertGreaterEqual(
            sheet.count("2px solid #f2c14e"), 4)
        big = stylesheet(True)
        self.assertIn("font-size: 14pt", big)
        self.assertIn("font-size: 34pt", big)
        self.assertNotIn("\u2014", sheet)


class ShortcutTests(GuiTestCase):
    """T12: Ctrl+R rebuilds, Ctrl+E opens Try it (and encodes
    inside it), / focuses the search."""

    def test_ctrl_r_rebuilds(self):
        self._fill_source()
        QTest.keyClick(self.window, Qt.Key_R, Qt.ControlModifier)
        self._wait_for_rebuild()
        self.assertEqual(self.window.files_value.text(), "7")

    def test_ctrl_e_opens_tryit(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        QTest.keyClick(self.window, Qt.Key_E, Qt.ControlModifier)
        QTest.qWait(100)
        self.assertIsNotNone(self.window._tryit_window)
        self.assertTrue(self.window._tryit_window.isVisible())
        self.window._tryit_window.close()

    def test_ctrl_e_encodes_inside_tryit(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        text = "the quick brown fox jumps over the lazy dog"
        tryit.try_input.setPlainText(text)
        QTest.keyClick(tryit, Qt.Key_E, Qt.ControlModifier)
        QTest.qWait(100)
        encoded = tryit.try_output.toPlainText()
        self.assertIn("~", encoded)
        self.assertLess(len(encoded), len(text))
        tryit.close()

    def test_slash_focuses_search(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.table.setFocus()
        _pump()
        QTest.keyClick(self.window.table, Qt.Key_Slash)
        QTest.qWait(50)
        self.assertEqual(_app.focusWidget(),
                         self.window.search_edit)
        self.assertEqual(self.window.tabs.currentWidget(),
                         self.window._dictionary_tab_widget)

    def test_slash_types_normally_in_text_fields(self):
        edit = self.window.folder_edit
        edit.setText("abc")
        edit.setFocus()
        _pump()
        QTest.keyClick(edit, Qt.Key_Slash)
        QTest.qWait(50)
        self.assertEqual(edit.text(), "abc/")
        self.assertNotEqual(_app.focusWidget(),
                            self.window.search_edit)


class FileMenuTests(GuiTestCase):
    """T15: the File menu, and T11's Restore action in it."""

    def _file_menu_actions(self):
        for action in self.window.menuBar().actions():
            if action.text() == "File":
                return {a.text(): a for a in action.menu().actions()
                        if a.text()}
        self.fail("no File menu")

    def test_file_menu_lists_everything(self):
        actions = self._file_menu_actions()
        for label in ("Open folder", "Export JSON",
                      "Export text file", "Debug report",
                      "Restore previous dictionary", "Quit"):
            self.assertIn(label, actions)

    def test_file_menu_is_first(self):
        labels = [a.text() for a in
                  self.window.menuBar().actions()]
        self.assertEqual(labels[0], "File")

    def test_exports_disabled_without_dictionary(self):
        actions = self._file_menu_actions()
        self.assertFalse(actions["Export JSON"].isEnabled())
        self.assertFalse(actions["Export text file"].isEnabled())

    def test_exports_enabled_after_rebuild(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        actions = self._file_menu_actions()
        self.assertTrue(actions["Export JSON"].isEnabled())
        self.assertTrue(actions["Export text file"].isEnabled())

    def test_restore_disabled_until_previous_exists(self):
        actions = self._file_menu_actions()
        self.assertFalse(
            actions["Restore previous dictionary"].isEnabled())
        folder = self._source_folder()
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("the quick brown fox " * 10)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        actions = self._file_menu_actions()
        self.assertFalse(
            actions["Restore previous dictionary"].isEnabled())
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("lazy dog sleeps soundly " * 10)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        actions = self._file_menu_actions()
        self.assertTrue(
            actions["Restore previous dictionary"].isEnabled())
        actions["Restore previous dictionary"].trigger()
        _pump()
        self.assertIn("quick", self.window.dictionary.word_to_code)
        self.assertNotIn("lazy",
                         self.window.dictionary.word_to_code)

    def test_quit_closes_the_window(self):
        actions = self._file_menu_actions()
        self.assertEqual(actions["Quit"].shortcut().toString(),
                         "Ctrl+Q")
        actions["Quit"].trigger()
        _pump()
        self.assertFalse(self.window.isVisible())


class _FakeDropEvent:
    """A stand-in for QDragEnterEvent/QDropEvent: constructing the
    real ones from Python segfaults on PySide6 6.12 (their
    constructor is deprecated). The handlers only use mimeData(),
    acceptProposedAction() and ignore()."""

    def __init__(self, mime):
        self._mime = mime
        self._accepted = False

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


class DragDropTests(GuiTestCase):
    """T16: drag and drop files and folders onto the window."""

    def _mime_with(self, paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return mime

    def _drag_event(self, paths):
        return _FakeDropEvent(self._mime_with(paths))

    def _drop_event(self, paths):
        return _FakeDropEvent(self._mime_with(paths))

    def test_drag_enter_accepts_files_and_highlights(self):
        event = self._drag_event(
            [os.path.join(self.tmp.name, "x.txt")])
        self.window.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertIn("c9a227",
                      self.window.folder_edit.styleSheet())

    def test_drag_enter_ignores_text(self):
        mime = QMimeData()
        mime.setText("hello")
        event = _FakeDropEvent(mime)
        self.window.dragEnterEvent(event)
        self.assertFalse(event.isAccepted())

    def test_drop_file_copies_into_source_folder(self):
        source = os.path.join(self.tmp.name, "dropped.txt")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("the quick brown fox")
        event = self._drop_event([source])
        self.window.dropEvent(event)
        self.assertTrue(event.isAccepted())
        dest = os.path.join(self._source_folder(), "dropped.txt")
        self.assertTrue(os.path.exists(dest))
        with open(dest, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "the quick brown fox")
        self.assertEqual(self.window.folder_edit.styleSheet(), "")
        self.assertIn("Added 1 file",
                      self.window.statusBar().currentMessage())

    def test_drop_name_clash_gets_numbered(self):
        folder = self._source_folder()
        with open(os.path.join(folder, "same.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("first")
        source = os.path.join(self.tmp.name, "same.txt")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("second")
        self.window.dropEvent(self._drop_event([source]))
        numbered = os.path.join(folder, "same (2).txt")
        self.assertTrue(os.path.exists(numbered))
        with open(numbered, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "second")
        with open(os.path.join(folder, "same.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "first")

    def test_drop_folder_sets_source_folder(self):
        target = os.path.join(self.tmp.name, "other")
        os.makedirs(target)
        event = self._drop_event([target])
        self.window.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.window.folder_edit.text(), target)

    def test_drop_file_already_in_folder_is_skipped(self):
        folder = self._source_folder()
        path = os.path.join(folder, "here.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("here")
        self.window.dropEvent(self._drop_event([path]))
        self.assertFalse(
            os.path.exists(os.path.join(folder, "here (2).txt")))


class ValidationTests(GuiTestCase):
    """T18: folder validation on blur, empty-search guidance."""

    def test_missing_folder_warns_on_blur(self):
        self.window.folder_edit.setText("/no/such/folder/xyz")
        self.window.folder_edit.editingFinished.emit()
        _pump()
        self.assertEqual(self.window.folder_warning.text(),
                         "That folder does not exist.")

    def test_existing_folder_clears_warning(self):
        self.window.folder_edit.setText("/no/such/folder/xyz")
        self.window.folder_edit.editingFinished.emit()
        _pump()
        self.window.folder_edit.setText(self._source_folder())
        self.window.folder_edit.editingFinished.emit()
        _pump()
        self.assertEqual(self.window.folder_warning.text(), "")

    def test_file_path_warns_it_is_a_file(self):
        path = os.path.join(self.tmp.name, "a.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        self.window.folder_edit.setText(path)
        self.window.folder_edit.editingFinished.emit()
        _pump()
        self.assertIn("not a folder",
                      self.window.folder_warning.text())

    def test_empty_search_shows_guidance(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.search_edit.setText("zzzqqq")
        self._wait_for_search()
        self.assertTrue(
            self.window.search_empty_label.isVisible())
        self.assertIn("No words match",
                      self.window.search_empty_label.text())
        self.window.search_edit.setText("")
        self._wait_for_search()
        self.assertFalse(
            self.window.search_empty_label.isVisible())


class TooltipsAndShortcutsTests(GuiTestCase):
    """T14: tooltips, the shortcuts window, the search hint, and
    the "/" off switch."""

    def test_tooltips_are_present_and_sized(self):
        # Verb-first, 60-75 chars, shortcut named where one exists.
        window = self.window
        for name in ("rebuild_button", "browse_button",
                     "open_button", "tryit_button",
                     "export_json_button", "export_text_button",
                     "debug_button", "search_edit",
                     "hero_tile", "files_tile", "words_tile",
                     "codes_tile", "sample_tile"):
            tip = getattr(window, name).toolTip()
            self.assertTrue(tip, name)
            self.assertGreaterEqual(len(tip), 60, (name, tip))
            self.assertLessEqual(len(tip), 75, (name, tip))
        self.assertIn("Ctrl+R",
                      window.rebuild_button.toolTip())
        self.assertIn("Ctrl+E",
                      window.tryit_button.toolTip())

    def test_search_hint_under_search_box(self):
        self.assertEqual(self.window.search_hint.text(),
                         "Type part of a word to find its code.")

    def test_shortcuts_window_opens_from_help_menu(self):
        help_menu = None
        for action in self.window.menuBar().actions():
            if action.text() == "Help":
                help_menu = action.menu()
        self.assertIsNotNone(help_menu)
        for action in help_menu.actions():
            if action.text() == "Keyboard shortcuts":
                action.trigger()
                break
        else:
            self.fail("no Keyboard shortcuts action in Help menu")
        _pump()
        window = self.window._shortcuts_window
        self.assertIsNotNone(window)
        self.assertTrue(window.isVisible())
        view = window.centralWidget().layout().itemAt(0).widget()
        self.assertIn("Ctrl+R", view.toPlainText())
        self.assertIn("Ctrl+E", view.toPlainText())
        window.close()

    def test_slash_key_can_be_turned_off(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.slash_search_action.trigger()  # uncheck it
        _pump()
        self.assertFalse(self.window._slash_search)
        self.window.table.setFocus()
        _pump()
        QTest.keyClick(self.window.table, Qt.Key_Slash)
        QTest.qWait(50)
        self.assertNotEqual(_app.focusWidget(),
                            self.window.search_edit)
        self.window.slash_search_action.trigger()  # check it again
        _pump()
        self.assertTrue(self.window._slash_search)
        QTest.keyClick(self.window.table, Qt.Key_Slash)
        QTest.qWait(50)
        self.assertEqual(_app.focusWidget(),
                         self.window.search_edit)

    def test_slash_setting_is_remembered(self):
        self.window.slash_search_action.trigger()
        _pump()
        self.assertEqual(
            self.window.settings.value("slash_search", True,
                                       type=bool),
            False)


class TryItWindowTests(GuiTestCase):
    """The Try it window (T3): round-trip, mismatch path (T13),
    geometry, button states."""

    def test_round_trip_exact(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        text = "the quick brown fox jumps over the lazy dog"
        tryit.try_input.setPlainText(text)
        tryit.encode_button.click()
        _pump()
        encoded = tryit.try_output.toPlainText()
        self.assertIn("~", encoded)
        self.assertLess(len(encoded), len(text))
        self.assertIn("saved", tryit.try_result.text())
        tryit.decode_button.click()
        _pump()
        self.assertIn("exact", tryit.try_result.text())
        self.assertEqual(tryit.try_output.toPlainText(), text)
        tryit.close()

    def test_buttons_disabled_without_a_dictionary(self):
        tryit = self._open_tryit_via_menu()
        self.assertFalse(tryit.encode_button.isEnabled())
        self.assertFalse(tryit.decode_button.isEnabled())
        tryit.close()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        self.assertTrue(tryit.encode_button.isEnabled())
        self.assertTrue(tryit.decode_button.isEnabled())
        tryit.close()

    def test_mismatch_names_the_saved_report(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        text = "the quick brown fox"
        tryit.try_input.setPlainText(text)
        tryit.encode_button.click()
        _pump()
        # Swap in an empty dictionary: the decode can no longer
        # match, which forces the mismatch path.
        self.window.dictionary = QwkhndDictionary()
        tryit.decode_button.click()
        _pump()
        result = tryit.try_result.text()
        self.assertIn("MISMATCH", result)
        self.assertIn("debug-report-", result)
        self.assertNotIn("Arlo", result)
        path = result.split("saved at ")[1].rstrip(".")
        self.assertTrue(os.path.exists(path), path)
        tryit.close()

    def test_tryit_geometry_remembered(self):
        tryit = self._open_tryit_via_menu()
        tryit.resize(700, 470)
        QTest.qWait(50)
        tryit.close()
        QTest.qWait(50)
        self.window._show_try_it()
        QTest.qWait(50)
        second = self.window._tryit_window
        try:
            self.assertEqual(second.height(), 470)
        finally:
            second.close()

    def test_copy_result_puts_output_on_clipboard(self):
        # T17: Copy needs a result first, then the clipboard holds
        # exactly what the output shows.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        try:
            self.assertFalse(tryit.copy_button.isEnabled())
            tryit.try_input.setPlainText("the quick brown fox")
            tryit.encode_button.click()
            _pump()
            self.assertTrue(tryit.copy_button.isEnabled())
            encoded = tryit.try_output.toPlainText()
            tryit.copy_button.click()
            _pump()
            self.assertEqual(_app.clipboard().text(), encoded)
            self.assertEqual(tryit.copy_button.text(), "Copied!")
        finally:
            tryit.close()

    def test_sample_sentence_encodes_shorter(self):
        # T17: the sample sentence is real text that the
        # dictionary shortens.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        try:
            tryit.sample_button.click()
            _pump()
            text = tryit.try_input.toPlainText()
            self.assertTrue(text)
            tryit.encode_button.click()
            _pump()
            self.assertLess(len(tryit.try_output.toPlainText()),
                            len(text))
        finally:
            tryit.close()

    def test_clear_empties_everything(self):
        # T17: Clear empties the input, the output and the result.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        try:
            tryit.try_input.setPlainText("the quick brown fox")
            tryit.encode_button.click()
            _pump()
            self.assertTrue(tryit.try_output.toPlainText())
            tryit.clear_button.click()
            _pump()
            self.assertEqual(tryit.try_input.toPlainText(), "")
            self.assertEqual(tryit.try_output.toPlainText(), "")
            self.assertEqual(tryit.try_result.text(), "")
            self.assertFalse(tryit.copy_button.isEnabled())
        finally:
            tryit.close()

    def test_sample_button_disabled_without_dictionary(self):
        tryit = self._open_tryit_via_menu()
        try:
            self.assertFalse(tryit.sample_button.isEnabled())
        finally:
            tryit.close()


class CopyTests(GuiTestCase):
    """T13: the folder hint, the sample explainer, no dead ends."""

    def test_folder_hint_says_what_the_folder_is_for(self):
        hints = [child for child in self.window.findChildren(QWidget)
                 if isinstance(child, QLabel)
                 and "Your books and documents go here" in
                 (child.text() or "")]
        self.assertEqual(len(hints), 1)
        self.assertIn("reads them to build the dictionary",
                      hints[0].text())

    def test_sample_tile_explains_itself(self):
        self.assertIn("100 characters",
                      self.window.sample_caption.text())
        self.assertIn("before and after",
                      self.window.sample_caption.text())

    def test_no_arlo_anywhere_in_help(self):
        self.assertNotIn("Arlo", help_text())
        self.assertNotIn("Arlo", quick_start_text())

    def test_help_explains_the_decoding_rule(self):
        # T22: the greedy whole-run rule, in plain words.
        self.assertIn("Put a space after\na code",
                      help_text())
        self.assertIn("~brown is read as one code", help_text())


class UntestedPathsTests(GuiTestCase):
    """T26: the paths the suite never drove before."""

    def test_open_folder_opens_the_folder(self):
        with mock.patch(
                "qwkhnd.app.QDesktopServices.openUrl") as open_url:
            self.window._open_folder()
        self.assertEqual(open_url.call_count, 1)
        url = open_url.call_args[0][0]
        self.assertEqual(url.toLocalFile(), self._source_folder())

    def test_about_dialog_shows_name_and_version(self):
        with mock.patch(
                "qwkhnd.app.QMessageBox.about") as about:
            self.window._show_about()
        self.assertEqual(about.call_count, 1)
        self.assertIn(APP_NAME, about.call_args[0][1])
        self.assertIn(VERSION, about.call_args[0][2])

    def test_closing_mid_rebuild_stops_cleanly(self):
        # Closing while a rebuild runs cancels the worker and the
        # window closes instead of hanging.
        import qwkhnd.app as app_module
        started = threading.Event()
        real_build = app_module.build_from_folder

        def slow_build(folder, log=None, progress=None,
                       cancelled=None, file_progress=None):
            started.set()
            while not (cancelled and cancelled()):
                time.sleep(0.05)
            return real_build(folder, log=log, progress=progress,
                              cancelled=cancelled,
                              file_progress=file_progress)

        with mock.patch.object(app_module, "build_from_folder",
                               slow_build):
            self._fill_source()
            self.window.rebuild_button.click()
            self.assertTrue(started.wait(timeout=10),
                            "worker never started")
            self.window.close()
            _pump()
            self.assertFalse(self.window.isVisible())
            self.assertIsNone(self.window._thread)


class DensityTests(GuiTestCase):
    """T29: the Compact/Comfortable row-height switch."""

    def _row_height(self):
        return self.window.table.verticalHeader() \
            .defaultSectionSize()

    def test_density_toggle_changes_row_height(self):
        comfortable = self._row_height()
        self.assertFalse(self.window.density_action.isChecked())
        self.window.density_action.trigger()
        _pump()
        compact = self._row_height()
        self.assertLess(compact, comfortable)
        self.window.density_action.trigger()
        _pump()
        self.assertEqual(self._row_height(), comfortable)

    def test_density_setting_is_remembered(self):
        self.window.density_action.trigger()
        _pump()
        self.assertEqual(
            self.window.settings.value("compact_table", False,
                                       type=bool),
            True)

    def test_compact_rows_scale_with_big_text(self):
        self.window.density_action.trigger()
        _pump()
        compact_normal = self._row_height()
        self.window.big_text_action.trigger()
        _pump()
        self.assertGreater(self._row_height(), compact_normal)


class PolishTests(GuiTestCase):
    """T28: the warning glyph, the disabled-button contrast, the
    saved confirmation, the safe debug report, the released
    single-instance lock."""

    def test_notice_has_warning_glyph(self):
        self.window._show_notice("Something went wrong.")
        self.assertTrue(
            self.window.notice_label.text().startswith("\u26a0"))

    def test_disabled_rebuild_button_contrast(self):
        # The disabled Rebuild text must read at 4.5:1 or better
        # against its background (v0.2 measured 2.48:1).
        sheet = stylesheet(False)
        block = re.search(
            r"QPushButton#rebuildButton:disabled \{(.*?)\}",
            sheet, re.S).group(1)
        # The lookbehind keeps "background-color" (and
        # "border-color") from matching the "color:" pattern.
        fg = re.search(r"(?<!-)color: (#[0-9a-f]{6})",
                       block).group(1)
        bg = re.search(r"background-color: (#[0-9a-f]{6})",
                       block).group(1)

        def luminance(hexs):
            channels = [int(hexs[i:i + 2], 16) / 255.0
                        for i in (1, 3, 5)]

            def linear(c):
                return (c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
            r, g, b = [linear(c) for c in channels]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        light, dark = sorted([luminance(fg), luminance(bg)],
                             reverse=True)
        self.assertGreaterEqual((light + 0.05) / (dark + 0.05), 4.5)

    def test_status_bar_confirms_save_after_rebuild(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("Dictionary saved.",
                      self.window.statusBar().currentMessage())

    def test_debug_report_failure_shows_notice(self):
        with mock.patch.object(
                self.window.log, "generate_report",
                side_effect=OSError("disk full")):
            self.window._debug_report()
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("Could not write the debug report",
                      self.window.notice_label.text())

    def test_close_releases_single_instance(self):
        instance = mock.Mock()
        self.window._single_instance = instance
        self.window.close()
        _pump()
        instance.release.assert_called_once_with()
        self.assertIsNone(self.window._single_instance)


class SingleInstanceTests(unittest.TestCase):
    """U27: a second start is refused, and the first is notified."""

    KEY = "qwkhnd-test-single-instance"

    def test_second_instance_is_refused(self):
        first = SingleInstance(self.KEY)
        second = SingleInstance(self.KEY)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
        finally:
            first.release()
            second.release()

    def test_second_start_notifies_the_first(self):
        first = SingleInstance(self.KEY)
        got = []
        first.activate_requested.connect(lambda: got.append(True))
        second = SingleInstance(self.KEY)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            # T27: wait for the notification, not a fixed 100 ms.
            deadline = time.monotonic() + 5.0
            while not got:
                QTest.qWait(20)
                if time.monotonic() > deadline:
                    break
            self.assertEqual(got, [True])
        finally:
            first.release()
            second.release()


if __name__ == "__main__":
    unittest.main()
