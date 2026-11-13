"""GUI tests (offscreen): the window drives a real rebuild.

The rebuild runs on a worker thread, so rebuild tests wait for
the window's _rebuild_done flag instead of assuming the click
finished the work. New in this pass: worker-thread proof, cancel,
the How to Use window, the no-em-dash scan (U33), geometry memory
(U5), and the single-instance guard (U27).
"""

import glob
import logging
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QPlainTextEdit, QPushButton, QWidget)

from fixtures import write_minimal_docx, write_minimal_pdf  # noqa: E402
from qwkhnd import APP_NAME, VERSION  # noqa: E402
from qwkhnd.app import MainWindow, SingleInstance, help_text  # noqa: E402
from qwkhnd.engine import (  # noqa: E402
    BuildReport, QwkhndDictionary, build_from_folder)

_app = None


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])


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

    def _wait_for_rebuild(self, timeout_ms=15000):
        """Pump until the worker reports done. Returns the finish time."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while not self.window._rebuild_done:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("rebuild did not finish in %d ms"
                          % timeout_ms)
        return time.monotonic()

    def _wait_for_progress(self, timeout_ms=5000):
        """Pump until the progress bar has moved (rebuild under way)."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while self.window.progress_bar.value() == 0:
            QTest.qWait(20)
            if time.monotonic() > deadline:
                self.fail("no rebuild progress seen in %d ms"
                          % timeout_ms)

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


class WindowTests(GuiTestCase):
    def test_title_has_name_and_version(self):
        self.assertIn(APP_NAME, self.window.windowTitle())
        self.assertIn(VERSION, self.window.windowTitle())

    def test_default_source_folder_created(self):
        self.assertTrue(os.path.isdir(self._source_folder()))
        self.assertEqual(self.window.folder_edit.text(),
                         self._source_folder())

    def test_no_ampersand_in_visible_text(self):
        # Qt eats a bare "&" in button/tab text (mnemonic marker), so
        # no visible label may contain one.
        for button in self.window.findChildren(QPushButton):
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

    def test_no_em_dash_in_visible_text(self):
        # U33: no em-dash in any visible string, including strings
        # that only appear after a rebuild (sample, skipped list).
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        texts = []
        for widget in self.window.findChildren(QWidget):
            getter = getattr(widget, "text", None)
            if callable(getter):
                try:
                    texts.append((repr(widget), getter()))
                except Exception:
                    pass
            placeholder = getattr(widget, "placeholderText", None)
            if callable(placeholder):
                texts.append((repr(widget), placeholder()))
        for index in range(self.window.tabs.count()):
            texts.append(("tab %d" % index,
                          self.window.tabs.tabText(index)))
        for index in range(self.window.table.columnCount()):
            item = self.window.table.horizontalHeaderItem(index)
            texts.append(("header %d" % index, item.text()))
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
        texts.append(("status",
                      self.window.statusBar().currentMessage()))
        texts.append(("sample", self.window.sample_label.text()))
        for where, text in texts:
            self.assertNotIn("\u2014", text, where)

    def test_rebuild_populates_stats_table_and_skipped(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("4 read", self.window.files_label.text())
        self.assertIn("1 skipped", self.window.files_label.text())
        self.assertNotIn("None yet", self.window.codes_label.text())
        self.assertGreater(self.window.table.rowCount(), 0)
        self.assertEqual(self.window.table.item(0, 0).text(), "the")
        self.assertEqual(self.window.table.item(0, 1).text(), "~a")
        skipped = [self.window.skipped_list.item(i).text()
                   for i in range(self.window.skipped_list.count())]
        self.assertEqual(len(skipped), 1)
        self.assertIn("photo.png", skipped[0])
        self.assertIn("OCR", skipped[0])
        self.assertIn("saved", self.window.sample_label.text())

    def test_rebuild_empty_folder_is_not_a_crash(self):
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.assertIn("0 read", self.window.files_label.text())
        self.assertEqual(self.window.table.rowCount(), 0)
        self.assertIn("No readable text",
                      self.window.statusBar().currentMessage())

    def test_rebuild_missing_folder_is_not_a_crash(self):
        self.window.folder_edit.setText(
            os.path.join(self.tmp.name, "does-not-exist"))
        self.window.rebuild_button.click()
        _pump()
        self.assertIn("does not exist",
                      self.window.statusBar().currentMessage())

    def test_rebuild_runs_off_the_ui_thread(self):
        # U30: the build runs in a worker thread, and the UI event
        # loop keeps running while it does (a timer scheduled before
        # the click fires before the rebuild finishes).
        import qwkhnd.app as app_module
        main_ident = threading.get_ident()
        real_build = app_module.build_from_folder
        seen = {}

        def slow_build(folder, log=None, progress=None,
                       cancelled=None):
            seen["ident"] = threading.get_ident()
            for step in range(5):
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
            finished_at = self._wait_for_rebuild()
        self.assertIn("ident", seen)
        self.assertNotEqual(seen["ident"], main_ident)
        self.assertIn("timer", marks)
        self.assertLess(marks["timer"], finished_at)
        self.assertIn("4 read", self.window.files_label.text())
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

        def slow_cancel(folder, log=None, progress=None,
                        cancelled=None):
            for step in range(100):
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

    def test_tryit_round_trip_exact(self):
        self._fill_source()
        self.window.rebuild_button.click()
        self._wait_for_rebuild()
        self.window.tabs.setCurrentIndex(2)
        text = "the quick brown fox jumps over the lazy dog"
        self.window.try_input.setPlainText(text)
        self.window.encode_button.click()
        _pump()
        encoded = self.window.try_output.toPlainText()
        self.assertIn("~", encoded)
        self.assertLess(len(encoded), len(text))
        self.assertIn("saved", self.window.try_result.text())
        self.window.decode_button.click()
        _pump()
        self.assertIn("exact", self.window.try_result.text())
        self.assertEqual(self.window.try_output.toPlainText(), text)

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
            self.assertIn("the -> ~a", fh.read())

    def test_debug_report_button_writes_a_report(self):
        self.window.debug_button.click()
        _pump()
        reports = glob.glob(os.path.join(
            self.data_dir, "logs", "debug-report-*.txt"))
        self.assertEqual(len(reports), 1)
        with open(reports[0], encoding="utf-8") as fh:
            self.assertIn("Qwkhnd 0.1", fh.read())
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
            self.assertGreater(second.table.rowCount(), 0)
            self.assertEqual(second.table.item(0, 0).text(), "the")
            self.assertNotIn("None yet", second.codes_label.text())
        finally:
            second.close()
            second.deleteLater()
            _pump()

    def test_help_tab_names_the_limits(self):
        help_tab = self.window.tabs.widget(3)
        view = help_tab.findChildren(QPlainTextEdit)[0]
        text = view.toPlainText()
        self.assertIn("OCR", text)
        self.assertIn("offline", text)
        self.assertIn(".docx", text)


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
            QTest.qWait(100)
            self.assertEqual(got, [True])
        finally:
            first.release()
            second.release()


if __name__ == "__main__":
    unittest.main()
