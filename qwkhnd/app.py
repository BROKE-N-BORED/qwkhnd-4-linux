"""Qwkhnd main window (PySide6, native, never a web UI).

Plain and easy on purpose: pick the Source Material folder, press
Rebuild, see the dictionary. The window remembers its folder and
its size between runs. Everything is offline, the program only
reads files on this machine.

The rebuild runs on a worker thread (U30), so the window stays
usable while a big folder is read. Progress and Cancel live under
the Rebuild button (U26), an activity light sits in the status
bar (U16), and the Help menu opens a How to Use window (U22).
Only one copy runs at a time (U27): starting it again raises the
window that is already open.
"""

import json
import os
import sys

from PySide6.QtCore import QObject, QSettings, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QStatusBar,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME, VERSION
from .debug_log import DebugLogger
from .engine import QwkhndDictionary, build_from_folder

TOP_SHOWN = 100
ORGANISATION = "BrokeNBored"
LIGHT_IDLE = "color: #2e9e4f; font-size: 14px;"
LIGHT_WORKING = "color: #d98a1f; font-size: 14px;"
PROGRESS_IDLE = ("Press Rebuild dictionary to build the dictionary "
                 "from the folder above.")


def default_data_dir():
    """Where Qwkhnd keeps its dictionary, logs and source folder."""
    return os.path.join(os.path.expanduser("~"), APP_NAME)


def help_text():
    """The Help text, with the app name + version filled in.

    The name and version come from qwkhnd/__init__.py, the one
    place they live, so a rename never leaves stale copy behind.
    Shown in the Help tab and in the How to Use window.
    """
    return """How to use %(name)s

1. Drop files into your Source Material folder. The folder above
   is the default. Use Browse to point at a different one, or
   Open folder to jump straight to it.
2. Press Rebuild dictionary. %(name)s reads every file it can
   and builds a new dictionary from scratch. The rebuild runs in
   the background, so the window stays usable, and you can press
   Cancel to stop it. The old dictionary stays in place until a
   rebuild finishes.
3. The most frequent words get the shortest codes. Try it out on
   the Try it tab, and export the dictionary as JSON or plain text.

What it reads: .txt, .md and other text files, .pdf files with a
text layer, and .docx Word files. Other files are attempted as
plain text when they look like text.

What it skips, and why (every skipped file is listed on the
Skipped files tab, with its reason):
- Images, audio and video: turning those into text needs OCR or
  speech recognition, which is not in v%(version)s.
- Archives, programs and other binary files: no readable text.
- Old .doc/.xls/.ppt files: save them as .docx to use them.
- Hidden files and folders, and scanned PDFs with no text layer.

%(name)s is fully offline. It never goes on the network, it
only reads files on this machine. Logs live in the logs folder
next to your dictionary, and the Debug report button writes a
scrubbed report you can send when something goes wrong.
""" % {"name": APP_NAME, "version": VERSION}


class RebuildWorker(QObject):
    """Builds the dictionary off the UI thread (U30).

    Lives in a QThread. Progress, finished and failed are Qt
    signals, so the window hears about them on the main thread.
    request_cancel is checked before each file by the engine.
    """

    progress = Signal(int, int, str)  # done, total, file name
    finished = Signal(object, object)  # dictionary, report
    failed = Signal(str)  # error message

    def __init__(self, folder, log, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.log = log
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    def _cancelled(self):
        return self._cancel

    def run(self):
        try:
            dictionary, report = build_from_folder(
                self.folder, log=self.log,
                progress=self.progress.emit,
                cancelled=self._cancelled)
        except Exception as exc:
            self.log.exception("rebuild failed")
            self.failed.emit(str(exc))
            return
        self.finished.emit(dictionary, report)


class SingleInstance(QObject):
    """One running copy only (U27).

    The first start owns a local server under the app id. A later
    start connects to it, the first copy raises its window, and
    the later start exits. Any connection counts as an activation
    request, so no message format is needed.
    """

    activate_requested = Signal()

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.server = None

    def acquire(self):
        """True when this copy owns the instance.

        False when another copy is already running: it has been
        asked to raise its window, and this copy should exit.
        """
        socket = QLocalSocket(self)
        socket.connectToServer(self.key)
        if socket.waitForConnected(500):
            socket.disconnectFromServer()
            return False
        # No live server: clear a stale socket left by a crash.
        QLocalServer.removeServer(self.key)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        if self.server.listen(self.key):
            return True
        # Lost a race: another copy is listening now. Ask it to raise.
        socket.connectToServer(self.key)
        if socket.waitForConnected(500):
            socket.disconnectFromServer()
        return False

    def release(self):
        if self.server is not None:
            self.server.close()
            self.server = None
        QLocalServer.removeServer(self.key)

    def _on_connection(self):
        socket = self.server.nextPendingConnection()
        while socket is not None:
            socket.disconnectFromServer()
            socket.deleteLater()
            socket = self.server.nextPendingConnection()
        self.activate_requested.emit()


class HowToUseWindow(QMainWindow):
    """The How to Use window, opened from the Help menu (U22)."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("How to Use %s" % APP_NAME)
        self.resize(700, 520)
        geometry = self.settings.value("howto_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(help_text())
        layout.addWidget(view)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
        self.setCentralWidget(central)

    def closeEvent(self, event):
        self.settings.setValue("howto_geometry", self.saveGeometry())
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """The one Qwkhnd window."""

    def __init__(self, data_dir=None, settings_path=None):
        super().__init__()
        self.data_dir = data_dir or default_data_dir()
        self.source_dir = os.path.join(self.data_dir, "Source Material")
        self.dict_path = os.path.join(
            self.data_dir, APP_ID + "-dictionary.json")
        os.makedirs(self.source_dir, exist_ok=True)

        self.log = DebugLogger(APP_ID, VERSION,
                               log_dir=os.path.join(self.data_dir,
                                                    "logs"))
        # The installed distribution is PySide6-Essentials (the full
        # PySide6 wheel depends on it too, so this name is right in
        # both cases. "PySide6" would report "not installed" on a
        # machine with Essentials only, even though it works).
        self.log.register_dependency("PySide6-Essentials")
        self.log.register_dependency("pypdf")
        self.log.install_crash_handler()
        self.log.info("%s %s started", APP_NAME, VERSION)

        if settings_path:
            self.settings = QSettings(settings_path,
                                      QSettings.IniFormat)
        else:
            self.settings = QSettings(ORGANISATION, APP_NAME)

        self.dictionary = QwkhndDictionary()
        self._thread = None
        self._worker = None
        self._rebuild_done = True
        self._howto_window = None
        self._single_instance = None
        self._build_ui()
        self._restore_state()
        self._load_saved_dictionary()

    # -- user interface ---------------------------------------------
    def _build_ui(self):
        self.setWindowTitle("%s %s" % (APP_NAME, VERSION))
        self.resize(1100, 700)
        self.setMinimumSize(820, 560)

        self._build_menu()

        central = QWidget(self)
        layout = QVBoxLayout(central)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Source Material folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setText(self.source_dir)
        folder_row.addWidget(self.folder_edit, stretch=1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_button)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(self._open_folder)
        folder_row.addWidget(self.open_button)
        layout.addLayout(folder_row)

        hint = QLabel("Drop PDFs and other files into that folder, "
                      "then press Rebuild.")
        layout.addWidget(hint)

        rebuild_row = QHBoxLayout()
        self.rebuild_button = QPushButton("Rebuild dictionary")
        self.rebuild_button.clicked.connect(self.rebuild)
        rebuild_row.addWidget(self.rebuild_button, stretch=1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_rebuild)
        rebuild_row.addWidget(self.cancel_button)
        layout.addLayout(rebuild_row)

        self.progress_label = QLabel(PROGRESS_IDLE)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        stats_box = QGroupBox("Dictionary stats")
        stats_form = QFormLayout(stats_box)
        self.files_label = QLabel("None yet")
        self.words_label = QLabel("None yet")
        self.codes_label = QLabel("None yet")
        self.sample_label = QLabel("Rebuild to see a sample.")
        self.sample_label.setWordWrap(True)
        stats_form.addRow("Files read:", self.files_label)
        stats_form.addRow("Words found:", self.words_label)
        stats_form.addRow("Codes assigned:", self.codes_label)
        stats_form.addRow("Sample:", self.sample_label)
        layout.addWidget(stats_box)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._dictionary_tab(), "Dictionary")
        self.tabs.addTab(self._skipped_tab(), "Skipped files")
        self.tabs.addTab(self._tryit_tab(), "Try it")
        self.tabs.addTab(self._help_tab(), "Help")
        layout.addWidget(self.tabs, stretch=1)

        bottom_row = QHBoxLayout()
        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.clicked.connect(self._export_json)
        bottom_row.addWidget(self.export_json_button)
        self.export_text_button = QPushButton("Export text file")
        self.export_text_button.clicked.connect(self._export_text)
        bottom_row.addWidget(self.export_text_button)
        self.debug_button = QPushButton("Debug report")
        self.debug_button.clicked.connect(self._debug_report)
        bottom_row.addWidget(self.debug_button)
        bottom_row.addStretch(1)
        layout.addLayout(bottom_row)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")
        self.activity_light = QLabel("\u25cf")
        self.activity_light.setStyleSheet(LIGHT_IDLE)
        self.activity_text = QLabel("Ready")
        self.statusBar().addPermanentWidget(self.activity_light)
        self.statusBar().addPermanentWidget(self.activity_text)
        self._refresh_buttons()

    def _build_menu(self):
        help_menu = self.menuBar().addMenu("Help")
        howto_action = help_menu.addAction("How to Use")
        howto_action.triggered.connect(self._show_how_to_use)
        about_action = help_menu.addAction("About %s" % APP_NAME)
        about_action.triggered.connect(self._show_about)

    def _show_how_to_use(self):
        if self._howto_window is None:
            self._howto_window = HowToUseWindow(self.settings, self)
        self._howto_window.show()
        self._howto_window.raise_()
        self._howto_window.activateWindow()

    def _show_about(self):
        QMessageBox.about(
            self, "About %s" % APP_NAME,
            "%s %s\n\nFull meaning in fewer tokens.\n\n"
            "Reads your own files and builds a shorthand "
            "dictionary from them. Fully offline."
            % (APP_NAME, VERSION))

    def _raise_window(self):
        """Single instance (U27): a second start raises this window."""
        self.show()
        self.raise_()
        self.activateWindow()

    def _dictionary_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Most frequent words first. The top %d codes:"
            % TOP_SHOWN))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Word", "Code", "Times used"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)
        return tab

    def _skipped_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Files %s could not use, and why:" % APP_NAME))
        self.skipped_list = QListWidget()
        layout.addWidget(self.skipped_list)
        return tab

    def _tryit_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Type or paste some text, then "
                                "encode it:"))
        self.try_input = QPlainTextEdit()
        self.try_input.setPlaceholderText(
            "Type something here after a rebuild...")
        layout.addWidget(self.try_input)
        layout.addWidget(QLabel(
            "This is the text you want to shorten."))
        row = QHBoxLayout()
        self.encode_button = QPushButton("Encode")
        self.encode_button.clicked.connect(self._try_encode)
        row.addWidget(self.encode_button)
        self.decode_button = QPushButton("Decode it back")
        self.decode_button.clicked.connect(self._try_decode)
        row.addWidget(self.decode_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.try_output = QPlainTextEdit()
        self.try_output.setReadOnly(True)
        layout.addWidget(self.try_output)
        layout.addWidget(QLabel(
            "The result appears here. Encode turns text into "
            "shorthand. Decode turns it back."))
        self.try_result = QLabel("")
        self.try_result.setWordWrap(True)
        layout.addWidget(self.try_result)
        return tab

    def _help_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        help_view = QPlainTextEdit()
        help_view.setReadOnly(True)
        help_view.setPlainText(help_text())
        layout.addWidget(help_view)
        return tab

    # -- state --------------------------------------------------------
    def _restore_state(self):
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        folder = self.settings.value("source_folder")
        if folder:
            self.folder_edit.setText(folder)
        self.log.set_setting("source_folder",
                             self.folder_edit.text())

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.request_cancel()
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(15000):
                self.log.warning("rebuild thread did not stop "
                                 "on close")
            self._thread = None
            self._worker = None
        if self._howto_window is not None:
            self._howto_window.close()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("source_folder",
                               self.folder_edit.text())
        super().closeEvent(event)

    def _refresh_buttons(self):
        have_dict = bool(self.dictionary)
        self.export_json_button.setEnabled(have_dict)
        self.export_text_button.setEnabled(have_dict)
        self.encode_button.setEnabled(have_dict)
        self.decode_button.setEnabled(have_dict)

    def _set_working(self, working):
        """Activity light + buttons for the rebuilding state (U16)."""
        self.rebuild_button.setEnabled(not working)
        self.cancel_button.setEnabled(working)
        self.progress_bar.setValue(0)
        if working:
            self.activity_light.setStyleSheet(LIGHT_WORKING)
            self.activity_text.setText("Working...")
        else:
            self.activity_light.setStyleSheet(LIGHT_IDLE)
            self.activity_text.setText("Ready")
            self.progress_label.setText(PROGRESS_IDLE)

    # -- folder -------------------------------------------------------
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the Source Material folder",
            self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self.log.set_setting("source_folder", folder)
            self.log.action("source folder picked: %s" % folder)

    def _open_folder(self):
        folder = self.folder_edit.text().strip() or self.source_dir
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(folder))

    # -- rebuild ------------------------------------------------------
    def rebuild(self):
        folder = self.folder_edit.text().strip() or self.source_dir
        if not os.path.isdir(folder):
            self.statusBar().showMessage(
                "That folder does not exist: %s" % folder)
            self.log.warning("rebuild: folder missing: %s", folder)
            return
        if self._thread is not None:
            return  # a rebuild is already running
        self.log.action("rebuild from %s" % folder)
        self.log.set_setting("source_folder", folder)
        self.settings.setValue("source_folder", folder)
        self._rebuild_done = False
        self._set_working(True)
        self.statusBar().showMessage("Rebuilding the dictionary...")
        self._thread = QThread(self)
        self._worker = RebuildWorker(folder, self.log)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_rebuild_finished)
        self._worker.failed.connect(self._on_rebuild_failed)
        self._thread.start()

    def cancel_rebuild(self):
        """Ask the worker to stop at the next file (U26)."""
        if self._worker is not None:
            self._worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling the rebuild...")
            self.log.action("rebuild cancel requested")

    def _cleanup_worker(self):
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            thread.quit()
            thread.wait(3000)
            thread.deleteLater()

    def _on_progress(self, done, total, name):
        if self._worker is None:
            return  # cleaned up already (window closing)
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)
        message = "Reading file %d of %d: %s" % (done, total, name)
        self.progress_label.setText(message)
        self.statusBar().showMessage(message)

    def _on_rebuild_finished(self, dictionary, report):
        if self._worker is None:
            return  # cleaned up already (window closing)
        self._cleanup_worker()
        self._set_working(False)
        self._rebuild_done = True
        if report.cancelled:
            self.statusBar().showMessage(
                "Rebuild cancelled. The old dictionary is still "
                "in place.")
            self.log.action("rebuild cancelled by the user")
            return
        self.dictionary = dictionary
        self._show_report(report)
        self._save_dictionary(report)
        self._refresh_buttons()
        if report.files_read == 0:
            self.statusBar().showMessage(
                "No readable text found. Drop some files into the "
                "folder and press Rebuild again.")
        else:
            self.statusBar().showMessage(
                "Rebuilt: %d files, %d words, %d codes"
                % (report.files_read, report.total_words,
                   report.codes_assigned))

    def _on_rebuild_failed(self, message):
        if self._worker is None:
            return  # cleaned up already (window closing)
        self._cleanup_worker()
        self._set_working(False)
        self._rebuild_done = True
        self.statusBar().showMessage(
            "Rebuild failed. Press Debug report for details.")

    def _show_report(self, report):
        self.files_label.setText(
            "%d read, %d skipped" % (report.files_read,
                                     len(report.files_skipped)))
        self.words_label.setText(
            "%d words (%d different)" % (report.total_words,
                                         report.unique_words))
        self.codes_label.setText("%d" % report.codes_assigned)
        if report.sample_text:
            before = report.sample_text[:160].replace("\n", " ")
            after = report.sample_encoded[:160].replace("\n", " ")
            self.sample_label.setText(
                "'%s'  ->  '%s'. %d characters saved (%.0f%%)"
                % (before, after, report.sample_saved,
                   report.sample_saved_pct))
        else:
            self.sample_label.setText("No text to sample yet.")
        self._fill_table()
        self.skipped_list.clear()
        for name, reason in report.files_skipped:
            self.skipped_list.addItem("%s: %s" % (name, reason))
        self.try_result.setText("")

    def _fill_table(self):
        entries = sorted(
            self.dictionary.word_to_code.items(),
            key=lambda kv: (-self.dictionary.counts.get(kv[0], 0),
                            kv[0]))[:TOP_SHOWN]
        self.table.setRowCount(len(entries))
        for row, (word, code) in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(word))
            self.table.setItem(row, 1,
                               QTableWidgetItem("~" + code))
            self.table.setItem(
                row, 2,
                QTableWidgetItem(
                    str(self.dictionary.counts.get(word, 0))))

    # -- dictionary file ----------------------------------------------
    def _save_dictionary(self, report):
        data = self.dictionary.to_json_dict()
        data["build"] = {
            "files_read": report.files_read,
            "files_skipped": len(report.files_skipped),
            "total_words": report.total_words,
            "unique_words": report.unique_words,
        }
        try:
            with open(self.dict_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        except OSError:
            self.log.exception("could not save the dictionary")
            self.statusBar().showMessage(
                "Rebuilt, but the dictionary could not be saved")

    def _load_saved_dictionary(self):
        if not os.path.exists(self.dict_path):
            return
        try:
            with open(self.dict_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.dictionary = QwkhndDictionary.from_json_dict(data)
        except (OSError, ValueError):
            self.log.exception("saved dictionary would not load")
            return
        build = data.get("build") or {}
        self.files_label.setText(
            "%d read, %d skipped (last rebuild)"
            % (build.get("files_read", 0),
               build.get("files_skipped", 0)))
        self.words_label.setText(
            "%d words (%d different)"
            % (build.get("total_words", 0),
               build.get("unique_words", 0)))
        self.codes_label.setText("%d" % len(self.dictionary))
        self.sample_label.setText(
            "Loaded the saved dictionary. Press Rebuild to refresh "
            "it from the folder.")
        self._fill_table()
        self._refresh_buttons()

    # -- try it ---------------------------------------------------------
    def _try_encode(self):
        text = self.try_input.toPlainText()
        if not text:
            self.try_result.setText("Type something first.")
            return
        encoded = self.dictionary.encode(text)
        self.try_output.setPlainText(encoded)
        _, _, saved, pct = self.dictionary.savings(text)
        self.try_result.setText(
            "%d characters in, %d out. %d saved (%.0f%%)"
            % (len(text), len(encoded), saved, pct))
        self.log.action("try-it encode: %d chars -> %d"
                        % (len(text), len(encoded)))

    def _try_decode(self):
        text = self.try_output.toPlainText()
        if not text:
            self.try_result.setText("Encode something first.")
            return
        decoded = self.dictionary.decode(text)
        self.try_output.setPlainText(decoded)
        if decoded == self.try_input.toPlainText():
            self.try_result.setText(
                "Round-trip: exact. Decoded text matches what "
                "you typed, character for character.")
        else:
            self.try_result.setText(
                "Round-trip MISMATCH. That should never happen. "
                "Press Debug report and send it to Arlo.")
            self.log.error("try-it round-trip mismatch")
        self.log.action("try-it decode: %d chars" % len(text))

    # -- export + debug -------------------------------------------------
    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export the dictionary as JSON",
            os.path.join(self.data_dir, APP_ID + "-dictionary.json"),
            "JSON files (*.json)")
        if not path:
            return
        try:
            self.dictionary.export_json(path)
        except OSError:
            self.log.exception("JSON export failed")
            self.statusBar().showMessage(
                "Could not write that file")
            return
        self.statusBar().showMessage("Dictionary exported to %s" % path)
        self.log.action("dictionary exported as JSON to %s" % path)

    def _export_text(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export the dictionary as a text file",
            os.path.join(self.data_dir, APP_ID + "-dictionary.txt"),
            "Text files (*.txt)")
        if not path:
            return
        try:
            self.dictionary.export_text(path)
        except OSError:
            self.log.exception("text export failed")
            self.statusBar().showMessage(
                "Could not write that file")
            return
        self.statusBar().showMessage("Dictionary exported to %s" % path)
        self.log.action("dictionary exported as text to %s" % path)

    def _debug_report(self):
        path = self.log.generate_report()
        self.statusBar().showMessage(
            "Debug report saved: %s" % path)


def main(argv=None):
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    instance = SingleInstance(APP_ID)
    if not instance.acquire():
        return 0  # another copy is running; it raised its window
    window = MainWindow()
    window._single_instance = instance
    instance.activate_requested.connect(window._raise_window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
