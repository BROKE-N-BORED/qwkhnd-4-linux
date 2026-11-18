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
    QMimeData, QPoint, QPropertyAnimation, QTimer, Qt, QUrl)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableView, QWidget)

from fixtures import write_minimal_docx, write_minimal_pdf  # noqa: E402
from qwkhnd import APP_NAME, VERSION  # noqa: E402
from qwkhnd.app import (  # noqa: E402
    SAMPLE_DIR, SAMPLE_FILES, DictionaryTableModel, MainWindow,
    SingleInstance, TryItWindow, app_icon, _trim_sample,
    _whole_words, help_text, quick_start_text, stylesheet)
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
        self.assertIn("empty",
                      self.window.statusBar().currentMessage())
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("empty",
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
        # T12 (v0.4): file name in the bar, full path in the
        # tooltip.
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Dictionary exported to out.json")
        self.assertEqual(
            self.window.statusBar().toolTip(),
            "Last JSON export: %s" % json_path)
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
        # T12 (v0.4): the status bar names the file, not the
        # whole path; the full path is the tooltip.
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Dictionary exported to out.txt")
        self.assertEqual(
            self.window.statusBar().toolTip(),
            "Last text export: %s" % text_path)

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
        # T12 (v0.4): the status bar names the file only; the
        # full path is the tooltip.
        self.assertNotIn(self.data_dir,
                         self.window.statusBar().currentMessage())
        self.assertEqual(
            self.window.statusBar().toolTip(),
            "Last debug report: %s" % reports[0])

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
            # T18 (v0.4): the scroll area stays visible (it
            # holds the checklist); the results inside it hide.
            self.assertFalse(window._bento_widget.isVisible())
            self.assertFalse(window.tabs.isVisible())
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

    def test_checklist_sits_at_the_top_on_first_run(self):
        # V04-FIX (verify): with the results hidden, the checklist
        # was the only visible item in the scroll area and the
        # layout centred it — 220 px of dead space above it on
        # the first screen. It must sit at the top, before and
        # after the first rebuild.
        _pump()
        y = self.window.checklist_frame.geometry().y()
        self.assertLessEqual(y, 2, "checklist floats: y=%d" % y)
        self.window.folder_edit.setText(SAMPLE_DIR)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        _pump()
        y = self.window.checklist_frame.geometry().y()
        self.assertLessEqual(y, 2, "checklist floats: y=%d" % y)

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

    def test_checklist_stays_until_try_it_done(self):
        # T13 (v0.4): the checklist no longer vanishes with the
        # first rebuild — it stays until step 3 (Try it) is
        # done, and it survives a restart in between.
        self.assertTrue(self.window.checklist_frame.isVisible())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window.checklist_frame.isVisible())
        self.assertTrue(
            self.window.check_step1.text().startswith("\u2713"))
        self.assertTrue(
            self.window.check_step2.text().startswith("\u2713"))
        self.assertTrue(
            self.window.check_step3.text().startswith("\u25cb"))
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            # A loaded dictionary still counts as a rebuild.
            self.assertTrue(second.checklist_frame.isVisible())
            self.assertTrue(
                second.check_step2.text().startswith("\u2713"))
            second._show_try_it()
            tryit = second._tryit_window
            tryit.try_input.setPlainText("the quick brown fox")
            tryit.encode_button.click()
            _pump()
            self.assertFalse(second.checklist_frame.isVisible())
        finally:
            second.close()
            second.deleteLater()
            _pump()
        third = MainWindow(data_dir=self.data_dir,
                           settings_path=self.settings_path)
        third.show()
        _pump()
        try:
            self.assertFalse(third.checklist_frame.isVisible())
        finally:
            third.close()
            third.deleteLater()
            _pump()


class DisclosureTests(GuiTestCase):
    """T3: the first screen is three choices; results appear after
    the first rebuild; Try it is its own window."""

    def test_first_screen_shows_only_folder_rebuild_checklist(self):
        # T18 (v0.4): the scroll area itself stays visible (it
        # holds the checklist); the results inside it hide.
        self.assertFalse(self.window._bento_widget.isVisible())
        self.assertFalse(self.window.tabs.isVisible())
        self.assertFalse(self.window.tryit_button.isVisible())
        self.assertTrue(self.window.checklist_frame.isVisible())
        self.assertTrue(self.window.folder_edit.isVisible())
        self.assertTrue(self.window.rebuild_button.isVisible())

    def test_results_appear_after_first_rebuild(self):
        self.assertFalse(self.window._bento_widget.isVisible())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window._bento_widget.isVisible())
        self.assertTrue(self.window.results_area.isVisible())
        self.assertTrue(self.window.tabs.isVisible())
        self.assertTrue(self.window.tryit_button.isVisible())
        self.assertTrue(self.window.export_json_button.isVisible())
        self.assertTrue(self.window.debug_button.isVisible())

    def test_results_visible_at_once_with_saved_dictionary(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        # T13 (v0.4): the checklist only hides once step 3
        # (Try it) is done, so finish it before restarting.
        self.window._show_try_it()
        tryit = self.window._tryit_window
        tryit.try_input.setPlainText("the quick brown fox")
        tryit.encode_button.click()
        _pump()
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
        self.assertEqual(
            labels,
            ["Dictionary", "Skipped files", "Help",
             "Words without codes"])

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
        self.assertIn("before and after",
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


class NoResultRebuildTests(GuiTestCase):
    """T01/T02 (v0.4): a rebuild that produces zero codes never
    wipes the dictionary, and the notice names the real case."""

    def _rebuild_with(self, text=None, files=None):
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        if text is not None:
            with open(os.path.join(folder, "a.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write(text)
        if files:
            for name, data in files.items():
                with open(os.path.join(folder, name), "wb") as fh:
                    fh.write(data)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()

    def _saved_entries(self, path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {entry["word"]: entry["code"]
                for entry in data["entries"]}

    def test_empty_rebuild_keeps_the_dictionary(self):
        self._rebuild_with("the quick brown fox " * 10)
        before = dict(self.window.dictionary.word_to_code)
        self.assertGreater(len(before), 0)
        with open(self.window.dict_path, encoding="utf-8") as fh:
            saved_before = fh.read()
        self._rebuild_with()  # empty folder
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        with open(self.window.dict_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), saved_before)
        self.assertFalse(
            os.path.exists(self.window.previous_dict_path))
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("empty", self.window.notice_label.text())
        self.assertIn("unchanged", self.window.notice_label.text())
        self.assertTrue(self.window.results_area.isVisible())
        self.assertNotEqual(self.window.codes_value.text(), "0")

    def test_second_empty_rebuild_keeps_it_too(self):
        # The task list's own scenario: two good rebuilds, then
        # an empty folder, then an images-only folder.
        self._rebuild_with("the quick brown fox " * 10)
        first = dict(self.window.dictionary.word_to_code)
        self._rebuild_with("lazy dog sleeps soundly " * 10)
        second = dict(self.window.dictionary.word_to_code)
        self.assertNotEqual(first, second)
        with open(self.window.previous_dict_path,
                  encoding="utf-8") as fh:
            previous_before = fh.read()
        self._rebuild_with()  # empty folder
        self._rebuild_with(files={
            "photo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64})
        self.assertEqual(self.window.dictionary.word_to_code,
                         second)
        self.assertEqual(
            self._saved_entries(self.window.dict_path), second)
        with open(self.window.previous_dict_path,
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), previous_before)
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("Skipped files tab",
                      self.window.notice_label.text())
        # Restore still brings back the first dictionary.
        self.window._restore_previous_dictionary()
        self.assertEqual(self.window.dictionary.word_to_code,
                         first)

    def test_restore_of_empty_previous_warns(self):
        self._rebuild_with("the quick brown fox " * 10)
        before = dict(self.window.dictionary.word_to_code)
        empty = {"app": "Qwkhnd", "version": "0.4", "marker": "~",
                 "entries": []}
        with open(self.window.previous_dict_path, "w",
                  encoding="utf-8") as fh:
            json.dump(empty, fh)
        self.window._restore_previous_dictionary()
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("empty", self.window.notice_label.text())
        self.assertNotIn(
            "Restored the previous dictionary",
            self.window.statusBar().currentMessage())

    def test_tiny_words_rebuild_keeps_dictionary_and_explains(self):
        self._rebuild_with("the quick brown fox " * 10)
        before = dict(self.window.dictionary.word_to_code)
        self._rebuild_with("ab cd ef gh " * 50)
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("long enough to shorten",
                      self.window.notice_label.text())
        self.assertIn("unchanged", self.window.notice_label.text())

    def test_empty_folder_with_no_dictionary_says_so(self):
        folder = self._source_folder()
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertEqual(len(self.window.dictionary), 0)
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("empty", self.window.notice_label.text())
        self.assertNotIn("unchanged",
                         self.window.notice_label.text())

    def test_unreadable_files_case_points_at_skipped_tab(self):
        self._rebuild_with(files={
            "photo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64})
        self.assertTrue(self.window.notice_frame.isVisible())
        self.assertIn("Skipped files tab",
                      self.window.notice_label.text())
        self.assertIn("1 skipped", self.window.notice_label.text())
        self.assertEqual(self.window.skipped_list.count(), 1)

    def _start_with_dict_and_previous(self, content, previous):
        data_dir = os.path.join(self.tmp.name, "data-corrupt-prev")
        os.makedirs(os.path.join(data_dir, "Source Material"))
        with open(os.path.join(data_dir,
                               "qwkhnd-dictionary.json"),
                  "w", encoding="utf-8") as fh:
            fh.write(content)
        if previous is not None:
            with open(os.path.join(
                    data_dir,
                    "qwkhnd-dictionary.previous.json"),
                    "w", encoding="utf-8") as fh:
                json.dump(previous, fh)
        window = MainWindow(
            data_dir=data_dir,
            settings_path=os.path.join(
                self.tmp.name, "settings-corrupt-prev.ini"))
        window.show()
        _pump()
        return window

    def test_corrupt_notice_names_restore_when_previous_exists(self):
        good = {"app": "Qwkhnd", "version": "0.4", "marker": "~",
                "entries": [{"word": "the", "code": "a",
                             "count": 5}]}
        window = self._start_with_dict_and_previous(
            "{ not json", good)
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
            self.assertIn("Restore previous dictionary",
                          window.notice_label.text())
        finally:
            window.close()
            window.deleteLater()
            _pump()

    def test_corrupt_notice_omits_restore_without_previous(self):
        window = self._start_with_dict_and_previous(
            "{ not json", None)
        try:
            self.assertFalse(window.dictionary)
            self.assertTrue(window.notice_frame.isVisible())
            self.assertNotIn("Restore",
                             window.notice_label.text())
        finally:
            window.close()
            window.deleteLater()
            _pump()


class TabScrollTests(GuiTestCase):
    """T03 (v0.4): switching tabs keeps the results scroll
    position, so the hero tile stays visible."""

    def test_tab_switch_keeps_scroll_at_zero(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        bar = self.window.results_area.verticalScrollBar()
        self.assertEqual(bar.value(), 0)
        # The bug needs focus inside the scroll area and a
        # programmatic switch: after a mouse rebuild focus lands
        # on the search box (the rebuild button is disabled
        # during the run, so focus moves on), and the switch
        # then moves focus to the new page's first widget — the
        # scroll area scrolls to show it. A plain .click()
        # leaves focus on the folder field, so the scroll never
        # fires — set it the way a real rebuild does.
        self.window.search_edit.setFocus()
        _pump()
        self.assertEqual(bar.value(), 0)
        for widget in (self.window._skipped_tab_widget,
                       self.window._help_tab_widget,
                       self.window._dictionary_tab_widget):
            self.window.tabs.setCurrentWidget(widget)
            QTest.qWait(300)
            _pump()
            self.assertEqual(bar.value(), 0)
        # The same, through the paths a user takes: the Skipped
        # link, then a mouse click on the tab bar.
        self.window.search_edit.setFocus()
        _pump()
        self.assertTrue(self.window.skipped_link.isVisible())
        QTest.mouseClick(self.window.skipped_link, Qt.LeftButton)
        QTest.qWait(300)
        _pump()
        self.assertEqual(self.window.tabs.currentIndex(), 1)
        self.assertEqual(bar.value(), 0)
        tabbar = self.window.tabs.tabBar()
        QTest.mouseClick(tabbar, Qt.LeftButton,
                         pos=tabbar.tabRect(0).center())
        QTest.qWait(300)
        _pump()
        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertEqual(bar.value(), 0)
        # The hero tile is fully visible in the viewport: its top
        # edge sits at or below the viewport's top edge.
        top = self.window.hero_tile.mapTo(
            self.window.results_area.viewport(), QPoint(0, 0)).y()
        self.assertGreaterEqual(top, 0)

    def test_tab_switch_keeps_a_deliberate_scroll(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        bar = self.window.results_area.verticalScrollBar()
        # The post-rebuild layout is scheduled, not instant: under
        # full-suite load the maximum still reads 0 right after
        # the rebuild returns (suite-final.log, 1 failure).
        # Poll briefly instead of asserting on a stale layout.
        deadline = time.monotonic() + 2.0
        while bar.maximum() == 0 and time.monotonic() < deadline:
            QTest.qWait(100)
            _pump()
        self.assertGreater(bar.maximum(), 0)
        self.window.search_edit.setFocus()
        _pump()
        bar.setValue(bar.maximum() // 2)
        _pump()
        saved = bar.value()
        self.assertGreater(saved, 0)
        self.window.tabs.setCurrentWidget(
            self.window._skipped_tab_widget)
        QTest.qWait(300)
        _pump()
        self.assertEqual(bar.value(), saved)
        # The guard releases: a scroll after the settle window
        # works.
        QTest.qWait(400)
        bar.setValue(0)
        _pump()
        self.assertEqual(bar.value(), 0)


class HeroLabelTests(GuiTestCase):
    """T04 (v0.4): the hero number names its basis, so it agrees
    with the sample tile next to it."""

    def test_hero_names_the_sample_size(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("1,500", self.window.hero_sub.text())
        self.assertIn("characters saved",
                      self.window.hero_sub.text())
        self.assertIn("before and after",
                      self.window.sample_caption.text())


class SampleTrimTests(GuiTestCase):
    """T08 (v0.4): the sample is never cut mid-code or mid-word."""

    def test_short_text_unchanged(self):
        self.assertEqual(_trim_sample("hello world", 100),
                         "hello world")

    def test_cut_at_word_boundary_with_ellipsis(self):
        text = "alpha beta gamma delta epsilon zeta eta theta"
        trimmed = _trim_sample(text, 20)
        self.assertTrue(trimmed.endswith("…"))
        self.assertNotIn("delt", trimmed)
        self.assertEqual(trimmed, "alpha beta gamma…")

    def test_code_cut_in_half_is_dropped(self):
        # The limit falls inside the code ~ab: the partial code
        # goes away entirely, not a lone "~".
        text = "the quick brown fox ~ab and more words here"
        trimmed = _trim_sample(text, 21)
        self.assertEqual(trimmed, "the quick brown fox…")
        self.assertNotIn("~", trimmed)

    def test_trailing_marker_stripped(self):
        text = "x" * 99 + "~ab and more words"
        trimmed = _trim_sample(text, 100)
        self.assertNotIn("~", trimmed)
        self.assertTrue(trimmed.endswith("…"))

    def test_no_space_keeps_the_slice(self):
        text = "x" * 150
        self.assertEqual(_trim_sample(text, 100), "x" * 100 + "…")

    def test_displayed_sample_never_ends_mid_code(self):
        self.window._set_sample(
            "the quick brown fox jumps over the lazy dog " * 5,
            "x" * 99 + "~ab and more words here")
        label = self.window.sample_label.text()
        self.assertIn("…", label)
        self.assertNotIn("~'", label)
        self.assertNotIn("~…", label)
        self.assertNotIn("100 characters",
                         self.window.sample_caption.text())

    def test_short_joined_slice_loses_its_lone_marker(self):
        # Found by eyeballing the drive's main screenshot: the
        # shipped samples join to 99 chars ending in " ~" — under
        # the limit, so the old code returned it untouched and the
        # tile showed a lone "~". A lone trailing marker is
        # always a cut code, at any length.
        self.assertEqual(_trim_sample("alpha beta ~", 100),
                         "alpha beta")
        self.assertEqual(_trim_sample("~", 100), "")

    def test_real_escape_survives_the_short_path(self):
        # A literal "~" is written as "~~": it ends in "~~",
        # not " ~", so the lone-marker strip must leave it.
        self.assertEqual(_trim_sample("alpha ~~", 100),
                         "alpha ~~")

    def test_shipped_samples_show_no_lone_marker(self):
        # The real corpus that caught this: rebuild from the
        # shipped samples and check the tile itself.
        self.window.folder_edit.setText(SAMPLE_DIR)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        label = self.window.sample_label.text()
        self.assertFalse(label.endswith("~'"), label)
        self.assertNotIn(" ~'", label)

    def test_whole_words_drops_a_cut_fragment(self):
        # V04-FIX (verify): the 100-char slice ends inside
        # "fragmented" — the "fragm" goes.
        joined = " ".join(["word"] * 19)
        before = joined + " fragmented words follow here"
        self.assertEqual(_whole_words(before[:100], before),
                         joined)

    def test_whole_words_keeps_a_clean_cut(self):
        # The slice ends on a space: the last word is whole.
        before = " ".join(["word"] * 20) + " more words follow"
        self.assertEqual(_whole_words(before[:100], before),
                         " ".join(["word"] * 20))

    def test_whole_words_keeps_short_text(self):
        self.assertEqual(_whole_words("short text", "short text"),
                         "short text")

    def test_whole_words_keeps_a_single_token(self):
        # One long word has nowhere better to break.
        self.assertEqual(_whole_words("x" * 100, "x" * 150),
                         "x" * 100)

    def test_set_sample_never_ends_mid_word(self):
        # End to end: the stored sample (and the tile, and the
        # Try-it sample button) ends on a whole word.
        before = " ".join(["word"] * 19) + " fragmented tail here"
        after = " ".join(["code"] * 19) + " fragmented tail here"
        self.window._set_sample(before, after)
        self.assertEqual(self.window._sample_before,
                         " ".join(["word"] * 19))
        self.assertEqual(self.window._sample_after,
                         " ".join(["code"] * 19))
        self.assertNotIn("fragm", self.window.sample_label.text())


class TableRoomTests(GuiTestCase):
    """T10 (v0.4): the table shows 8+ rows at default size."""

    def _rows_on_screen(self):
        """Full table rows actually visible in the window: the
        table viewport's height alone lies, because the table
        can run past the bottom of the results viewport."""
        table_view = self.window.table.viewport()
        results_view = self.window.results_area.viewport()
        rect = table_view.rect()
        top = table_view.mapTo(results_view,
                               rect.topLeft()).y()
        bottom = table_view.mapTo(results_view,
                                  rect.bottomRight()).y()
        visible = max(0, min(bottom, results_view.height())
                      - max(top, 0))
        return visible // self.window.table.rowHeight(0)

    def test_eight_rows_visible_at_default_size(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        # T18 (v0.4): the checklist is a transient onboarding
        # element — dismiss it for the steady-state measure,
        # the way a user past onboarding sees the table.
        self.window.checklist_dismiss.click()
        _pump()
        self.assertGreaterEqual(self._rows_on_screen(), 8)
        # The progress row is hidden when idle, which is what
        # paid for the room.
        self.assertFalse(self.window.progress_bar.isVisible())
        self.assertFalse(self.window.progress_label.isVisible())

    def test_scrolling_past_checklist_shows_eight_rows(self):
        # T18 (v0.4): with the checklist still visible it sits
        # above the bento inside the scroll area — scrolling
        # down past it recovers the full 8 rows, which a
        # checklist fixed above the scroll area could never do.
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window.checklist_frame.isVisible())
        # Let the post-rebuild layout settle before reading the
        # scrollbar maximum — it is 0 until the content has its
        # height, and setValue(0) scrolls nowhere.
        QTest.qWait(200)
        bar = self.window.results_area.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        QTest.qWait(200)
        self.assertGreaterEqual(self._rows_on_screen(), 8)

    def test_progress_row_shows_while_rebuilding(self):
        # Hiding the row when idle must not hide it while a
        # rebuild runs: the bar is the progress (U26).
        # _set_working(True) runs synchronously in rebuild(), so
        # the row is visible right after the click — no need to
        # wait for a progress signal (a small rebuild can finish
        # before the first poll).
        self._fill_source()
        self.window.rebuild_button.click()
        _pump()
        self.assertTrue(self.window.progress_bar.isVisible())
        self.assertTrue(self.window.progress_label.isVisible())
        self._wait_for_rebuild()
        self.assertFalse(self.window.progress_bar.isVisible())
        self.assertFalse(self.window.progress_label.isVisible())


class TableCopyTests(GuiTestCase):
    """T10 (v0.4): the right-click copy menu."""

    def _menu_for_row_0(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        index = self.window.table_model.index(0, 0)
        return self.window._table_menu_for(index)

    def _trigger(self, menu, text):
        for action in menu.actions():
            if action.text() == text:
                action.trigger()
                return
        self.fail("no action %r" % text)

    def test_menu_offers_copy_word_code_row(self):
        menu = self._menu_for_row_0()
        texts = [action.text() for action in menu.actions()]
        self.assertEqual(texts, ["Copy word", "Copy code", "Copy row"])

    def test_copy_code_lands_on_clipboard(self):
        menu = self._menu_for_row_0()
        _word, code, _count = self.window.table_model.entry_at(0)
        self._trigger(menu, "Copy code")
        self.assertEqual(QApplication.clipboard().text(),
                         "~" + code)

    def test_copy_word_and_row(self):
        menu = self._menu_for_row_0()
        word, code, _count = self.window.table_model.entry_at(0)
        self._trigger(menu, "Copy word")
        self.assertEqual(QApplication.clipboard().text(), word)
        self._trigger(menu, "Copy row")
        self.assertEqual(QApplication.clipboard().text(),
                         "%s: ~%s" % (word, code))

    def test_tooltip_names_right_click_and_ctrl_c(self):
        tip = self.window.table.toolTip()
        self.assertIn("Right-click", tip)
        self.assertIn("Ctrl+C", tip)


class ModelSortTests(unittest.TestCase):
    """T10 (v0.4): the table model's sorting, without a window."""

    def setUp(self):
        self.model = DictionaryTableModel()
        self.model.set_entries([("banana", "a", 5),
                                ("apple", "b", 9),
                                ("cherry", "c", 1)])

    def _words(self):
        return [self.model.data(self.model.index(row, 0))
                for row in range(self.model.rowCount())]

    def test_sort_by_word(self):
        self.model.sort(0, Qt.AscendingOrder)
        self.assertEqual(self._words(),
                         ["apple", "banana", "cherry"])
        self.model.sort(0, Qt.DescendingOrder)
        self.assertEqual(self._words(),
                         ["cherry", "banana", "apple"])

    def test_sort_by_count(self):
        self.model.sort(2, Qt.AscendingOrder)
        self.assertEqual(self._words(),
                         ["cherry", "banana", "apple"])
        self.model.sort(2, Qt.DescendingOrder)
        self.assertEqual(self._words(),
                         ["apple", "banana", "cherry"])

    def test_sort_survives_new_entries(self):
        self.model.sort(0, Qt.AscendingOrder)
        self.model.set_entries([("zebra", "d", 2),
                                ("mango", "e", 3)])
        self.assertEqual(self._words(), ["mango", "zebra"])
        self.assertEqual(self.model.sort_description(), "Word")

    def test_no_sort_by_default(self):
        self.assertIsNone(self.model.sort_description())
        self.assertEqual(self._words(),
                         ["banana", "apple", "cherry"])


class TableSortTests(GuiTestCase):
    """T10 (v0.4): header-click sorting in the window."""

    def _words_in_table(self):
        model = self.window.table_model
        return [model.data(model.index(row, 0))
                for row in range(model.rowCount())]

    def _click_header(self, section):
        header = self.window.table.horizontalHeader()
        x = header.sectionViewportPosition(section) \
            + header.sectionSize(section) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton,
                         pos=QPoint(x, header.height() // 2))
        _pump()

    def test_click_word_header_sorts_then_reverses(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self._click_header(0)
        words = self._words_in_table()
        self.assertEqual(words, sorted(words))
        self.assertIn("Sorted by Word",
                      self.window.table_count_label.text())
        self._click_header(0)
        words = self._words_in_table()
        self.assertEqual(words, sorted(words, reverse=True))

    def test_sort_keeps_the_selection_on_its_word(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        model = self.window.table_model
        word = model.data(model.index(0, 0))
        self.window.table.setCurrentIndex(model.index(0, 0))
        self._click_header(0)
        current = self.window.table.currentIndex()
        self.assertTrue(current.isValid())
        self.assertEqual(model.data(model.index(current.row(), 0)),
                         word)

    def test_sort_survives_a_search(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self._click_header(0)
        self.window.search_edit.setText("e")
        self._wait_for_search()
        words = self._words_in_table()
        self.assertEqual(words, sorted(words))
        self.assertIn("Sorted by Word",
                      self.window.table_count_label.text())


class ProgressStoryTests(GuiTestCase):
    """T05 (v0.4): one progress story — the label keeps the
    overall file count, and a small file never flashes 100%."""

    def test_file_progress_keeps_the_overall_label(self):
        # Drive the progress handlers directly: a file that read
        # in one chunk (fraction 1.0) must not touch the label.
        # The handlers ignore calls with no worker running, so a
        # stand-in stands in for one.
        self.window._worker = object()
        try:
            self.window._on_progress(5, 150, "story-04.txt")
            label = self.window.progress_label.text()
            self.assertIn("file 5 of 150", label)
            self.window._on_file_progress("story-04.txt", 1.0)
            self.assertEqual(self.window.progress_label.text(), label)
            self.assertNotIn("100%", label)
            # A big file mid-read reports in the status bar only.
            self.window._on_file_progress("big-book.txt", 0.5)
            self.assertEqual(self.window.progress_label.text(), label)
            self.assertIn("50%",
                          self.window.statusBar().currentMessage())
        finally:
            self.window._worker = None

    def test_rebuild_label_never_shows_100_percent(self):
        # A 150-file rebuild: sample the label while it runs; it
        # must always carry the overall story, never an in-file
        # percentage.
        folder = self._source_folder()
        for number in range(150):
            with open(os.path.join(folder, "story-%02d.txt" % number),
                      "w", encoding="utf-8") as fh:
                fh.write("the quick brown fox chapter %d " % number
                         * 20)
        self.window.rebuild_button.click()
        seen = set()
        deadline = time.monotonic() + 60
        while not self.window._rebuild_done:
            QTest.qWait(20)
            seen.add(self.window.progress_label.text())
            if time.monotonic() > deadline:
                self.fail("rebuild did not finish")
        for label in seen:
            self.assertNotIn("100%", label)
        self.assertTrue(
            any(re.search(r"file \d+ of \d+", label)
                for label in seen),
            "no overall progress label seen: %r" % (seen,))


class FolderValidationLiveTests(GuiTestCase):
    """T06 (v0.4): the folder warning updates on startup and on
    every change of the field, not only on focus loss."""

    def test_moved_folder_warns_on_startup(self):
        # Rebuild from a folder, close, move the folder away,
        # reopen with the same settings: the warning is there
        # immediately, with no focus dance. The folder must not
        # be the default one: the window recreates its default
        # Source Material folder on start.
        folder = os.path.join(self.tmp.name, "custom-source")
        os.makedirs(folder)
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("the quick brown fox " * 10)
        self.window.folder_edit.setText(folder)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.close()
        self.window.deleteLater()
        _pump()
        gone = os.path.join(self.tmp.name, "moved-away")
        os.rename(folder, gone)
        window = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        window.show()
        _pump()
        try:
            self.assertEqual(window.folder_warning.text(),
                             "That folder does not exist.")
        finally:
            window.close()
            window.deleteLater()
            _pump()

    def test_warning_clears_without_focus_change(self):
        path = os.path.join(self.tmp.name, "a.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("x")
        self.window.folder_edit.setText(path)
        _pump()
        self.assertIn("not a folder",
                      self.window.folder_warning.text())
        # No editingFinished, no click: setting the text to a real
        # folder clears the warning at once.
        self.window.folder_edit.setText(self._source_folder())
        _pump()
        self.assertEqual(self.window.folder_warning.text(), "")


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
        self.assertIn("empty",
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

    def test_empty_file_listed_as_skipped(self):
        # T09 (v0.4): an empty file is listed with its reason,
        # not silently counted as read.
        self._fill_source()
        with open(os.path.join(self._source_folder(), "empty.txt"),
                  "w", encoding="utf-8"):
            pass
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        index = self.window.tabs.indexOf(
            self.window._skipped_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Skipped files (2)")
        items = [self.window.skipped_list.item(row).text()
                 for row in range(self.window.skipped_list.count())]
        self.assertTrue(
            any("empty.txt" in item and "empty file" in item
                for item in items),
            items)


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
        # T21 (v0.4): the quick start names the Try it button,
        # not just the View menu.
        self.assertIn("Try it button", text)
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
        # T21 (v0.4): the "What it skips" section names
        # symlinks and the app's own files, and "How to use"
        # names the Try it button.
        self.assertIn("Symbolic links", text)
        self.assertIn("own dictionary and log files", text)
        self.assertIn(
            "Try it out in the Try it window (the Try it "
            "button, or the",
            text)
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
        # T14 (v0.4): the message names the new name.
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Added 1 file as same (2).txt (that name was "
            "taken). Press Rebuild to use it.")
        with open(numbered, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "second")
        with open(os.path.join(folder, "same.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "first")

    def test_drop_several_with_a_rename_counts_them(self):
        # T14 (v0.4): several files with one rename get a count
        # and an example of the new name.
        folder = self._source_folder()
        with open(os.path.join(folder, "dropped.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("already here")
        first = os.path.join(self.tmp.name, "dropped.txt")
        second = os.path.join(self.tmp.name, "fresh.txt")
        for path in (first, second):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("the quick brown fox")
        event = self._drop_event([first, second])
        self.window.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Added 2 files (1 saved under a new name, e.g. "
            "dropped (2).txt). Press Rebuild to use them.")

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
        # T15 (v0.4): the guidance names the cause and the fix.
        self.assertEqual(
            self.window.search_empty_label.text(),
            "No words match. It may not be in your Source "
            "Material. Try a shorter word, or rebuild with "
            "files that use it.")
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

    def test_search_field_explains_itself(self):
        # T14, T10 (v0.4): the hint line under the search box is
        # gone (its 18 px are a row of the table); the field
        # still explains itself through its placeholder and its
        # tooltip.
        self.assertEqual(self.window.search_edit.placeholderText(),
                         "Search the dictionary...")
        self.assertIn("Search the dictionary by word",
                      self.window.search_edit.toolTip())

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
        # T07 (v0.4): Decode reads the input box now, so the
        # round-trip goes through it: encode, put the shorthand
        # back into the input, decode, get the original text.
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
        tryit.try_input.setPlainText(encoded)
        tryit.decode_button.click()
        _pump()
        self.assertIn("Decoded", tryit.try_result.text())
        self.assertEqual(tryit.try_output.toPlainText(), text)
        tryit.close()

    def test_decode_pasted_shorthand(self):
        # T07 (v0.4): shorthand pasted into the input decodes —
        # the use the old code refused with "Encode something
        # first."
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        dictionary = self.window.dictionary
        words = sorted(dictionary.word_to_code)[:3]
        shorthand = " ".join("~" + dictionary.word_to_code[w]
                            for w in words)
        tryit.try_input.setPlainText(shorthand)
        tryit.decode_button.click()
        _pump()
        self.assertEqual(tryit.try_output.toPlainText(),
                         " ".join(words))
        self.assertIn("Decoded", tryit.try_result.text())
        tryit.close()

    def test_decode_plain_text_explains_nothing_changed(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        tryit.try_input.setPlainText("hello world")
        tryit.decode_button.click()
        _pump()
        self.assertIn("No shorthand codes",
                      tryit.try_result.text())
        self.assertEqual(tryit.try_output.toPlainText(),
                         "hello world")
        tryit.close()

    def test_decode_unknown_codes_explains(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        tryit.try_input.setPlainText("~zzz ~qqq")
        tryit.decode_button.click()
        _pump()
        self.assertIn("not in your dictionary",
                      tryit.try_result.text())
        self.assertEqual(tryit.try_output.toPlainText(),
                         "~zzz ~qqq")
        tryit.close()

    def test_decode_empty_input_says_type_something(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        tryit.decode_button.click()
        _pump()
        self.assertIn("Type something first",
                      tryit.try_result.text())
        tryit.close()

    def test_buttons_disabled_without_a_dictionary(self):
        # T11 (v0.4): without a dictionary the Try it button and
        # the View menu entry are both disabled — the window
        # cannot be opened at all — so the no-dictionary state
        # is asserted on the main window, and the buttons are
        # checked after a rebuild opens the window for real.
        self.assertFalse(self.window.tryit_button.isEnabled())
        self.assertFalse(self.window.tryit_action.isEnabled())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertTrue(self.window.tryit_button.isEnabled())
        self.assertTrue(self.window.tryit_action.isEnabled())
        tryit = self._open_tryit_via_menu()
        self.assertTrue(tryit.encode_button.isEnabled())
        self.assertTrue(tryit.decode_button.isEnabled())
        tryit.close()

    def test_tryit_geometry_remembered(self):
        # T11 (v0.4): the menu entry is disabled without a
        # dictionary, so the window needs a rebuild first.
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
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
        # T11 (v0.4): the Try it window cannot be opened from
        # the menu without a dictionary, so this constructs the
        # window directly to check its buttons still disable
        # themselves in the no-dictionary state.
        tryit = TryItWindow(self.window, self.window.settings)
        try:
            tryit.show()
            QTest.qWait(100)
            self.assertFalse(tryit.sample_button.isEnabled())
            self.assertFalse(tryit.encode_button.isEnabled())
            self.assertFalse(tryit.decode_button.isEnabled())
        finally:
            tryit.close()


class TryItMessagesTests(GuiTestCase):
    """T11 (v0.4): the Try it result line explains itself — a
    longer result names the tilde, and a tiny saving with words
    the dictionary never saw says what to do about it."""

    def _encode(self, text):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        tryit = self._open_tryit()
        tryit.try_input.setPlainText(text)
        tryit.encode_button.click()
        result = tryit.try_result.text()
        tryit.close()
        return result

    def test_negative_savings_names_the_tilde(self):
        # F12: "a ~ b" encodes to "a ~~ b" — one longer, not
        # "-1 saved (-20%)".
        result = self._encode("a ~ b")
        self.assertEqual(
            result,
            "5 characters in, 6 out. 1 longer. "
            "A ~ in your text is written as ~~.")

    def test_small_saving_with_uncovered_words_gets_context(self):
        # F13: "the" is the only word the dictionary knows here,
        # so the saving is 1 char in 27 — the line says why and
        # what fixes it.
        result = self._encode("the zqxwvjklmn pqrstuvwxyz")
        self.assertIn("1 saved (4%)", result)
        self.assertIn(
            "Words not in your dictionary stay as they are. "
            "Rebuild with files that use them to shrink them.",
            result)

    def test_small_saving_with_all_words_covered_shows_no_context(self):
        # The one-letter words cannot be shortened (too short),
        # and "the" is covered — a rebuild would change nothing,
        # so no context line appears.
        result = self._encode("a b c d the")
        self.assertIn("1 saved (9%)", result)
        self.assertNotIn("Words not in your dictionary", result)


class TryItFileTests(GuiTestCase):
    """T16 (v0.4): encode and decode whole files from the Try
    it window. The source is never touched; the result lands
    next to it with a generated name."""

    def _open_with_dictionary(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        return self._open_tryit()

    def _write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _pick(self, tryit, button, path):
        with mock.patch(
                "qwkhnd.app.QFileDialog.getOpenFileName",
                return_value=(path, "")):
            button.click()
        _pump()

    def test_encode_file_writes_shorthand_next_to_source(self):
        tryit = self._open_with_dictionary()
        source = self._write("story.txt",
                             "the quick brown fox jumps over "
                             "the lazy dog")
        self._pick(tryit, tryit.encode_file_button, source)
        out_path = os.path.join(self.tmp.name,
                                "story.qwkhnd.txt")
        self.assertTrue(os.path.exists(out_path))
        with open(out_path, encoding="utf-8") as fh:
            encoded = fh.read()
        self.assertEqual(
            encoded,
            self.window.dictionary.encode(
                "the quick brown fox jumps over the lazy dog"))
        self.assertIn("story.qwkhnd.txt written next to "
                      "story.txt", tryit.try_result.text())
        self.assertIn("saved", tryit.try_result.text())
        # The source is untouched.
        with open(source, encoding="utf-8") as fh:
            self.assertEqual(fh.read(),
                             "the quick brown fox jumps over "
                             "the lazy dog")

    def test_decode_file_strips_marker_and_round_trips(self):
        tryit = self._open_with_dictionary()
        text = "the quick brown fox " * 20
        source = self._write("story.txt", text)
        self._pick(tryit, tryit.encode_file_button, source)
        encoded_path = os.path.join(self.tmp.name,
                                    "story.qwkhnd.txt")
        self._pick(tryit, tryit.decode_file_button, encoded_path)
        decoded_path = os.path.join(self.tmp.name,
                                    "story.decoded.txt")
        self.assertTrue(os.path.exists(decoded_path))
        with open(decoded_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)
        self.assertIn("story.decoded.txt written next to "
                      "story.qwkhnd.txt", tryit.try_result.text())

    def test_decode_file_without_marker_gets_decoded_name(self):
        tryit = self._open_with_dictionary()
        source = self._write("plain.txt", "the quick brown fox")
        self._pick(tryit, tryit.decode_file_button, source)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "plain.decoded.txt")))

    def test_file_round_trip_byte_for_byte_at_100k(self):
        tryit = self._open_with_dictionary()
        text = ("the quick brown fox jumps over the lazy dog "
                "and runs through the dictionary of words "
                "to find the meaning of shorthand. ") * 900
        self.assertGreater(len(text), 100000)
        source = self._write("big.txt", text)
        self._pick(tryit, tryit.encode_file_button, source)
        encoded_path = os.path.join(self.tmp.name,
                                    "big.qwkhnd.txt")
        self._pick(tryit, tryit.decode_file_button, encoded_path)
        with open(os.path.join(self.tmp.name, "big.decoded.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)

    def test_file_buttons_disabled_without_dictionary(self):
        tryit = TryItWindow(self.window, self.window.settings)
        try:
            tryit.show()
            QTest.qWait(100)
            self.assertFalse(tryit.encode_file_button.isEnabled())
            self.assertFalse(tryit.decode_file_button.isEnabled())
        finally:
            tryit.close()

    def test_non_text_file_shows_a_plain_notice(self):
        tryit = self._open_with_dictionary()
        path = os.path.join(self.tmp.name, "binary.bin")
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)
        self._pick(tryit, tryit.encode_file_button, path)
        self.assertEqual(
            tryit.try_result.text(),
            "Could not read that file as plain text. "
            "Pick a .txt or .md file.")
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "binary.qwkhnd.bin")))


class ImportTests(GuiTestCase):
    """T17 (v0.4): import a dictionary from a JSON file. A bad
    file leaves everything alone; a good one replaces the
    dictionary and rotates the old one to previous."""

    def _export_json(self, name):
        path = os.path.join(self.tmp.name, name)
        with mock.patch(
                "qwkhnd.app.QFileDialog.getSaveFileName",
                return_value=(path, "")):
            self.window.export_json_button.click()
        _pump()
        return path

    def _import(self, window, path):
        with mock.patch(
                "qwkhnd.app.QFileDialog.getOpenFileName",
                return_value=(path, "")):
            window.import_action.trigger()
        _pump()

    def test_import_action_enabled_without_dictionary(self):
        self.assertTrue(self.window.import_action.isEnabled())

    def test_export_then_import_into_a_fresh_window(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        exported = self._export_json("exported.json")
        codes = len(self.window.dictionary)
        second_dir = os.path.join(self.tmp.name, "data2")
        second = MainWindow(
            data_dir=second_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings2.ini"))
        second.show()
        _pump()
        try:
            self._import(second, exported)
            self.assertEqual(len(second.dictionary), codes)
            self.assertIn("the", second.dictionary.word_to_code)
            self.assertEqual(second.codes_value.text(),
                             "%d" % codes)
            self.assertEqual(second.hero_value.text(), "-")
            self.assertIn("Imported dictionary",
                          second.hero_sub.text())
            self.assertIn("Dictionary imported",
                          second.statusBar().currentMessage())
            # The import is saved, so it loads on restart.
            self.assertTrue(os.path.exists(second.dict_path))
        finally:
            second.close()
            second.deleteLater()
            _pump()
        third = MainWindow(
            data_dir=second_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings2.ini"))
        third.show()
        _pump()
        try:
            self.assertEqual(len(third.dictionary), codes)
        finally:
            third.close()
            third.deleteLater()
            _pump()

    def test_corrupt_import_leaves_everything_alone(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        before = dict(self.window.dictionary.word_to_code)
        with open(self.window.dict_path, "rb") as fh:
            saved = fh.read()
        bad_json = os.path.join(self.tmp.name, "bad.json")
        with open(bad_json, "w", encoding="utf-8") as fh:
            fh.write("this is not json at all")
        self._import(self.window, bad_json)
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        self.assertIn("does not look like JSON",
                      self.window.notice_label.text())
        bad_shape = os.path.join(self.tmp.name, "shape.json")
        with open(bad_shape, "w", encoding="utf-8") as fh:
            fh.write('{"entries": "not a list"}')
        self._import(self.window, bad_shape)
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        self.assertIn("Could not import that file",
                      self.window.notice_label.text())
        with open(self.window.dict_path, "rb") as fh:
            self.assertEqual(fh.read(), saved)
        self.assertFalse(
            os.path.exists(self.window.previous_dict_path))

    def test_empty_import_refused(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        before = dict(self.window.dictionary.word_to_code)
        empty = os.path.join(self.tmp.name, "empty.json")
        with open(empty, "w", encoding="utf-8") as fh:
            fh.write('{"marker": "~", "version": "0.4", '
                     '"entries": []}')
        self._import(self.window, empty)
        self.assertEqual(self.window.dictionary.word_to_code,
                         before)
        self.assertIn("holds no codes",
                      self.window.notice_label.text())

    def test_import_rotates_previous_and_restore_works(self):
        folder = self._source_folder()
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("the quick brown fox " * 10)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        exported = self._export_json("first.json")
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("lazy dog sleeps soundly " * 10)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("lazy", self.window.dictionary.word_to_code)
        self._import(self.window, exported)
        self.assertIn("quick",
                      self.window.dictionary.word_to_code)
        self.assertNotIn("lazy",
                         self.window.dictionary.word_to_code)
        # The pre-import dictionary is now the previous one.
        self.window.restore_action.trigger()
        _pump()
        self.assertIn("lazy", self.window.dictionary.word_to_code)


class UncoveredTests(GuiTestCase):
    """T18 (v0.4): the words that got no code — a link under
    the Codes tile, a tab with the list, and the reason for
    each word."""

    def test_link_tab_and_list_after_rebuild(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        # T20 (v0.4): the rewritten samples have 47 words
        # without a code (184 codes, 695 words, 231 different).
        self.assertEqual(len(self.window._uncovered_words), 47)
        self.assertTrue(self.window.uncovered_link.isVisible())
        self.assertEqual(self.window.uncovered_link.text(),
                         "47 words have no code")
        index = self.window.tabs.indexOf(
            self.window._uncovered_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Words without codes (47)")
        self.assertEqual(self.window.uncovered_list.count(), 47)
        for row in range(self.window.uncovered_list.count()):
            text = self.window.uncovered_list.item(row).text()
            self.assertTrue(
                text.endswith("too short to shrink")
                or text.endswith(
                    "the next code would not make it shorter"),
                text)
        self.window.uncovered_link.click()
        _pump()
        self.assertEqual(self.window.tabs.currentWidget(),
                         self.window._uncovered_tab_widget)

    def test_uncovered_survives_restart(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertEqual(len(second._uncovered_words), 47)
            self.assertTrue(second.uncovered_link.isVisible())
            self.assertEqual(second.uncovered_list.count(), 47)
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_no_result_rebuild_keeps_the_list(self):
        # T01: a rebuild that finds nothing leaves the list
        # (and the dictionary) untouched.
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        self.window.folder_edit.setText(empty)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertEqual(len(self.window._uncovered_words), 47)
        self.assertTrue(self.window.uncovered_link.isVisible())
        self.assertEqual(self.window.uncovered_list.count(), 47)

    def test_all_covered_hides_the_link(self):
        folder = os.path.join(self.tmp.name, "oneword")
        os.makedirs(folder)
        with open(os.path.join(folder, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("dictionary " * 20)
        self.window.folder_edit.setText(folder)
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertEqual(self.window._uncovered_words, [])
        self.assertFalse(self.window.uncovered_link.isVisible())
        index = self.window.tabs.indexOf(
            self.window._uncovered_tab_widget)
        self.assertEqual(self.window.tabs.tabText(index),
                         "Words without codes")
        self.assertEqual(self.window.uncovered_list.count(), 0)


class StaleHintTests(GuiTestCase):
    """T19 (v0.4): the gold hint under the folder line when the
    dictionary came from a different folder than the one in the
    field."""

    def _other_folder(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(other, exist_ok=True)
        return other

    def test_hint_hidden_after_rebuild(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertFalse(self.window.stale_label.isVisible())

    def test_hint_shows_when_folder_changes(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        other = self._other_folder()
        self.window.folder_edit.setText(other)
        _pump()
        self.assertTrue(self.window.stale_label.isVisible())
        self.assertEqual(
            self.window.stale_label.text(),
            "Dictionary is from a different folder. Press "
            "Rebuild to refresh it.")
        self.window.folder_edit.setText(self.window.source_dir)
        _pump()
        self.assertFalse(self.window.stale_label.isVisible())

    def test_hint_clears_after_rebuild_from_new_folder(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        other = self._other_folder()
        with open(os.path.join(other, "a.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("the quick brown fox " * 10)
        self.window.folder_edit.setText(other)
        _pump()
        self.assertTrue(self.window.stale_label.isVisible())
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertFalse(self.window.stale_label.isVisible())

    def test_hint_hidden_after_restart(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.close()
        _pump()
        second = MainWindow(data_dir=self.data_dir,
                            settings_path=self.settings_path)
        second.show()
        _pump()
        try:
            self.assertFalse(second.stale_label.isVisible())
            other = self._other_folder()
            second.folder_edit.setText(other)
            _pump()
            self.assertTrue(second.stale_label.isVisible())
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_import_never_shows_hint(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        exported = os.path.join(self.tmp.name, "exported.json")
        with mock.patch(
                "qwkhnd.app.QFileDialog.getSaveFileName",
                return_value=(exported, "")):
            self.window.export_json_button.click()
        _pump()
        with mock.patch(
                "qwkhnd.app.QFileDialog.getOpenFileName",
                return_value=(exported, "")):
            self.window.import_action.trigger()
        _pump()
        self.assertIsNone(self.window._dict_source_folder)
        self.window.folder_edit.setText(self._other_folder())
        _pump()
        self.assertFalse(self.window.stale_label.isVisible())

    def test_old_save_without_source_assumes_current_folder(self):
        # A v0.3 save has no source_folder key: loading it
        # assumes the current folder, so no stale hint appears.
        data_dir = os.path.join(self.tmp.name, "data-old")
        os.makedirs(os.path.join(data_dir, "Source Material"))
        dictionary, _ = build_from_folder(
            self.window.source_dir)
        data = dictionary.to_json_dict()
        data["build"] = {"files_read": 1, "total_words": 10,
                         "unique_words": 5}
        with open(os.path.join(data_dir,
                               "qwkhnd-dictionary.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        window = MainWindow(
            data_dir=data_dir,
            settings_path=os.path.join(self.tmp.name,
                                       "settings-old.ini"))
        window.show()
        _pump()
        try:
            self.assertTrue(window.dictionary)
            self.assertFalse(window.stale_label.isVisible())
        finally:
            window.close()
            window.deleteLater()
            _pump()


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
        self.assertIn("start of your text",
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
