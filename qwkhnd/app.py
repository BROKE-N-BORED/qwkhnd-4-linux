"""Qwkhnd main window (PySide6, native, never a web UI).

Plain and easy on purpose: pick the Source Material folder, press
Rebuild, see the dictionary. The window remembers its folder and
its size between runs. Everything is offline, the program only
reads files on this machine.

v0.2 redesign (BNB UI Design Source File Library):
- The first screen shows only the folder picker, Rebuild, and a
  getting-started checklist (entries 012, 020). Sample files ship
  in the folder, so the first Rebuild always does something real
  (entry 014). The results appear after the first rebuild.
- Try it lives in its own window (entry 004), opened from a button
  or the View menu.
- The results are a bento grid (entry 005): one hero tile for the
  characters saved, smaller tiles for files, words, codes, and a
  sample that explains itself.
- Errors get a visible inline notice (U29), not just a status line.
- The look comes from the icon: deep navy, gold, light blue (U15).
- Big text and Reduced motion presets live in the View menu
  (entry 015). Keyboard: Ctrl+R rebuild, Ctrl+E encode, / searches
  the dictionary (entry 023).

The rebuild runs on a worker thread (U30), so the window stays
usable while a big folder is read. Progress and Cancel live under
the Rebuild button (U26), an activity light sits in the status
bar (U16), and the Help menu opens a How to Use window (U22).
Only one copy runs at a time (U27): starting it again raises the
window that is already open.
"""

import json
import os
import shutil
import sys

from PySide6.QtCore import (
    QEvent, QObject, QPropertyAnimation, QEasingCurve, QRect,
    QSettings, QThread, QUrl, Qt, QTimer, Signal, QVariantAnimation,
)
from PySide6.QtGui import (
    QDesktopServices, QIcon, QKeySequence, QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSizePolicy, QStatusBar, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME, VERSION
from .debug_log import DebugLogger
from .engine import QwkhndDictionary, build_from_folder

TOP_SHOWN = 100
ORGANISATION = "BrokeNBored"
LIGHT_IDLE = "color: #2e9e4f; font-size: 14px;"
LIGHT_WORKING = "color: #f2c14e; font-size: 14px;"
PROGRESS_IDLE = ("Press Rebuild dictionary to build the dictionary "
                 "from the folder above.")

# The icon palette (U15): deep navy surfaces, gold primary accent,
# light blue secondary, white text.
NAVY = "#14202e"
GOLD = "#f2c14e"
BLUE = "#7fd4ff"

# Sample files (T1): short real prose about what Qwkhnd does. They
# ship in the package and are copied into an empty Source Material
# folder on first run only, so the first Rebuild always builds a
# real dictionary.
SAMPLE_FILES = (
    "sample-what-qwkhnd-does.txt",
    "sample-how-shorthand-works.txt",
    "sample-why-fewer-tokens.txt",
)
SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "samples")


def default_data_dir():
    """Where Qwkhnd keeps its dictionary, logs and source folder."""
    return os.path.join(os.path.expanduser("~"), APP_NAME)


def app_icon():
    """The window icon, from the PNG next to the package.

    Falls back to the SVG (when the Qt SVG plugin is present) and
    then to an empty icon, so a fresh clone without rendered PNGs
    still starts.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("icons/qwkhnd-48.png", "icons/qwkhnd.svg"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return QIcon()


def stylesheet(big_text=False):
    """The dark stylesheet, drawn from the icon palette (T2).

    Transform and opacity motion only; no glass anywhere (the
    filter's Q3: glass costs frames on his PC). Big text scales
    every font size by 1.3 (T11). The focus ring is a 2 px gold
    border on every focusable control (T12, entry 023).
    """
    scale = 1.3 if big_text else 1.0
    sizes = {
        "base": round(11 * scale),
        "tile": round(18 * scale),
        "hero": round(26 * scale),
        "caption": round(10 * scale),
    }
    return """
QWidget {
    background-color: #14202e;
    color: #eef2f5;
    font-size: %(base)dpt;
}
QMainWindow {
    background-color: #14202e;
}
QLabel {
    background-color: transparent;
}
QPushButton {
    background-color: #22374d;
    border: 1px solid #35506b;
    border-radius: 6px;
    padding: 6px 14px;
    color: #eef2f5;
}
QPushButton:hover {
    background-color: #2c4763;
}
QPushButton:pressed {
    background-color: #1a2c3e;
}
QPushButton:disabled {
    color: #7a8a99;
    background-color: #1a2c3e;
    border-color: #24384e;
}
QPushButton:focus {
    border: 2px solid #f2c14e;
}
QPushButton#rebuildButton {
    background-color: #f2c14e;
    border: 1px solid #f2c14e;
    color: #14202e;
    font-weight: bold;
}
QPushButton#rebuildButton:hover {
    background-color: #ffcf5e;
}
QPushButton#rebuildButton:pressed {
    background-color: #d9a93a;
}
QPushButton#rebuildButton:disabled {
    background-color: #5c522f;
    border-color: #5c522f;
    color: #9a9178;
}
QPushButton#linkButton {
    background-color: transparent;
    border: none;
    color: #7fd4ff;
    text-decoration: underline;
    padding: 0px;
    text-align: left;
}
QPushButton#linkButton:hover {
    color: #ffffff;
}
QLineEdit, QPlainTextEdit {
    background-color: #0f1a26;
    border: 1px solid #35506b;
    border-radius: 6px;
    padding: 4px 6px;
    color: #eef2f5;
    selection-background-color: #f2c14e;
    selection-color: #14202e;
}
QLineEdit:focus, QPlainTextEdit:focus {
    border: 2px solid #f2c14e;
}
QTabWidget::pane {
    border: 1px solid #35506b;
    background-color: #14202e;
}
QTabBar::tab {
    background-color: #1a2c3e;
    color: #b8c4d0;
    padding: 6px 14px;
    border: 1px solid #35506b;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #22374d;
    color: #ffffff;
    border-bottom: 2px solid #f2c14e;
}
QTabBar::tab:focus {
    color: #f2c14e;
}
QTableWidget {
    background-color: #0f1a26;
    gridline-color: #22374d;
    selection-background-color: #f2c14e;
    selection-color: #14202e;
}
QTableWidget:focus {
    border: 2px solid #f2c14e;
}
QHeaderView::section {
    background-color: #1a2c3e;
    color: #b8c4d0;
    padding: 4px;
    border: none;
    border-bottom: 1px solid #35506b;
}
QListWidget {
    background-color: #0f1a26;
    selection-background-color: #f2c14e;
    selection-color: #14202e;
}
QListWidget:focus {
    border: 2px solid #f2c14e;
}
QProgressBar {
    background-color: #0f1a26;
    border: 1px solid #35506b;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #eef2f5;
}
QProgressBar::chunk {
    background-color: #f2c14e;
    border-radius: 6px;
}
QMenuBar {
    background-color: #14202e;
    color: #eef2f5;
}
QMenuBar::item:selected {
    background-color: #22374d;
}
QMenu {
    background-color: #1a2c3e;
    color: #eef2f5;
    border: 1px solid #35506b;
}
QMenu::item:selected {
    background-color: #22374d;
    color: #ffffff;
}
QStatusBar {
    background-color: #0f1a26;
    color: #b8c4d0;
}
QFrame#tile {
    background-color: #1e3044;
    border: 1px solid #2c4258;
    border-radius: 16px;
}
QFrame#heroTile {
    background-color: #22374d;
    border: 1px solid #f2c14e;
    border-radius: 16px;
}
QLabel#tileValue {
    font-size: %(tile)dpt;
    font-weight: bold;
    color: #ffffff;
}
QLabel#heroValue {
    font-size: %(hero)dpt;
    font-weight: bold;
    color: #f2c14e;
}
QLabel#tileCaption {
    font-size: %(caption)dpt;
    color: #b8c4d0;
}
QFrame#noticeFrame {
    background-color: #3a2f10;
    border: 1px solid #f2c14e;
    border-radius: 8px;
}
QLabel#noticeLabel {
    color: #ffe9a8;
}
QFrame#checklistFrame {
    background-color: #1a2c3e;
    border: 1px solid #35506b;
    border-radius: 8px;
}
QToolTip {
    background-color: #22374d;
    color: #eef2f5;
    border: 1px solid #35506b;
}
QScrollBar:vertical {
    background-color: #0f1a26;
    width: 12px;
}
QScrollBar::handle:vertical {
    background-color: #35506b;
    border-radius: 6px;
    min-height: 20px;
}
QScrollBar:horizontal {
    background-color: #0f1a26;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background-color: #35506b;
    border-radius: 6px;
    min-width: 20px;
}
""" % sizes


def help_text():
    """The full Help text, with the app name + version filled in.

    The name and version come from qwkhnd/__init__.py, the one
    place they live, so a rename never leaves stale copy behind.
    Shown in the How to Use window (U22). The Help tab holds the
    short quick-start instead (T8): the two never share sentences.
    """
    return """How to use %(name)s

1. Drop files into your Source Material folder. The folder in the
   main window is the default. Use Browse to point at a different
   one, or Open folder to jump straight to it.
2. Press Rebuild dictionary. %(name)s reads every file it can
   and builds a new dictionary from scratch. The rebuild runs in
   the background, so the window stays usable, and you can press
   Cancel to stop it. The old dictionary stays in place until a
   rebuild finishes.
3. The most frequent words get the shortest codes. Try it out in
   the Try it window (View menu), and export the dictionary as
   JSON or plain text.

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


def quick_start_text():
    """The short quick-start for the Help tab (T8).

    Three steps in plain words, written fresh: no sentence here
    appears in help_text(), so the tab and the How to Use window
    each have their own words.
    """
    return """Quick start

1. Put files in the Source Material folder. The sample files are
   already there, so you can press Rebuild right away. Use Open
   folder to see what is inside.
2. Press the Rebuild dictionary button. %(name)s reads your files
   and builds the dictionary. The old dictionary stays until the
   new one is ready.
3. Open the Try it window from the View menu and encode some
   text. Then export the dictionary as JSON or plain text.

For the full guide, open How to Use from the Help menu.
""" % {"name": APP_NAME}


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
        self.setWindowIcon(app_icon())
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


class TryItWindow(QMainWindow):
    """The Try it window: encode text, decode it back (T3).

    Its own workspace, opened from the Try it button or the View
    menu (entry 004). It reads the main window's dictionary at
    encode time, so it always uses the latest rebuild. Geometry
    is remembered like the How to Use window. Ctrl+E encodes
    (T12).
    """

    def __init__(self, main_window, settings, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.settings = settings
        self.setWindowTitle("Try it - %s" % APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(700, 520)
        geometry = self.settings.value("tryit_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        central = QWidget(self)
        layout = QVBoxLayout(central)
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
        self.setCentralWidget(central)

        self.encode_shortcut = QShortcut(
            QKeySequence("Ctrl+E"), self)
        self.encode_shortcut.activated.connect(self._try_encode)
        self.refresh_buttons()

    def refresh_buttons(self):
        """Encode and Decode need a dictionary (U6: nothing is
        selected or enabled before it can do real work)."""
        have_dict = bool(self.main_window.dictionary)
        self.encode_button.setEnabled(have_dict)
        self.decode_button.setEnabled(have_dict)

    def showEvent(self, event):
        self.refresh_buttons()
        super().showEvent(event)

    def closeEvent(self, event):
        self.settings.setValue("tryit_geometry", self.saveGeometry())
        super().closeEvent(event)

    def _try_encode(self):
        text = self.try_input.toPlainText()
        if not text:
            self.try_result.setText("Type something first.")
            return
        dictionary = self.main_window.dictionary
        encoded = dictionary.encode(text)
        self.try_output.setPlainText(encoded)
        _, _, saved, pct = dictionary.savings(text)
        self.try_result.setText(
            "%d characters in, %d out. %d saved (%.0f%%)"
            % (len(text), len(encoded), saved, pct))
        self.main_window.log.action(
            "try-it encode: %d chars -> %d"
            % (len(text), len(encoded)))
        self.main_window._tried_it = True
        self.main_window._refresh_checklist()

    def _try_decode(self):
        text = self.try_output.toPlainText()
        if not text:
            self.try_result.setText("Encode something first.")
            return
        dictionary = self.main_window.dictionary
        decoded = dictionary.decode(text)
        self.try_output.setPlainText(decoded)
        if decoded == self.try_input.toPlainText():
            self.try_result.setText(
                "Round-trip: exact. Decoded text matches what "
                "you typed, character for character.")
        else:
            # T13: there is no send mechanism, so the report is
            # generated here and the message names where it is.
            path = self.main_window.log.generate_report()
            self.try_result.setText(
                "Round-trip MISMATCH. That should never happen. "
                "A debug report was saved at %s." % path)
            self.main_window.log.error("try-it round-trip mismatch")
        self.main_window.log.action("try-it decode: %d chars"
                                    % len(text))


class MainWindow(QMainWindow):
    """The Qwkhnd window, plus the Try it window it opens."""

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
        self._sample_before = ""
        self._sample_after = ""
        self._thread = None
        self._worker = None
        self._rebuild_done = True
        self._ever_rebuilt = False
        self._tried_it = False
        self._howto_window = None
        self._tryit_window = None
        self._single_instance = None
        self._big_text = self.settings.value(
            "big_text", False, type=bool)
        self._reduced_motion = self.settings.value(
            "reduced_motion", False, type=bool)
        self._dip_anim = None
        self._tick_anim = None
        self._hero_anim = None
        self._hero_effect = None
        self._maybe_add_samples()
        self._build_ui()
        self._restore_state()
        self._load_saved_dictionary()
        self._set_results_visible(bool(self.dictionary))
        self._refresh_checklist()

    # -- first run ----------------------------------------------------
    def _maybe_add_samples(self):
        """Copy the sample files into an empty Source Material
        folder, on first run only (T1). The settings flag records
        that the decision was made, so deleted samples never
        come back."""
        if self.settings.value("samples_added", False, type=bool):
            return
        folder_empty = not os.listdir(self.source_dir)
        no_dictionary = not os.path.exists(self.dict_path)
        if folder_empty and no_dictionary:
            for name in SAMPLE_FILES:
                source = os.path.join(SAMPLE_DIR, name)
                if os.path.exists(source):
                    shutil.copy(source,
                                os.path.join(self.source_dir, name))
            self.log.action(
                "sample files added to the Source Material folder")
        self.settings.setValue("samples_added", True)

    def _refresh_checklist(self):
        """Show the getting-started checklist only until the first
        rebuild (T1, entry 020). Dismissed means dismissed."""
        if self.settings.value("checklist_done", False, type=bool):
            self.checklist_frame.setVisible(False)
            return
        if self.dictionary:
            self.checklist_frame.setVisible(False)
            return
        self.checklist_frame.setVisible(True)
        folder = self.folder_edit.text().strip() or self.source_dir
        has_files = os.path.isdir(folder) and bool(os.listdir(folder))
        self._set_check_step(
            self.check_step1,
            "Put files in the Source Material folder", has_files)
        self._set_check_step(self.check_step2,
                             "Press Rebuild dictionary",
                             self._ever_rebuilt)
        self._set_check_step(
            self.check_step3,
            "Try it: encode some text in the Try it window",
            self._tried_it)

    def _set_check_step(self, label, text, done):
        mark = "\u2713 " if done else "\u25cb "
        label.setText(mark + text)
        if done:
            label.setStyleSheet("color: %s;" % BLUE)
        else:
            label.setStyleSheet("")

    def _dismiss_checklist(self):
        self.settings.setValue("checklist_done", True)
        self.checklist_frame.setVisible(False)
        self.log.action("checklist dismissed")

    # -- user interface ---------------------------------------------
    def _build_ui(self):
        self.setWindowTitle("%s %s" % (APP_NAME, VERSION))
        self.setWindowIcon(app_icon())
        self.resize(1100, 720)
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

        hint = QLabel("Your books and documents go here. %s reads "
                      "them to build the dictionary." % APP_NAME)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        rebuild_row = QHBoxLayout()
        self.rebuild_button = QPushButton("Rebuild dictionary")
        self.rebuild_button.setObjectName("rebuildButton")
        self.rebuild_button.clicked.connect(self.rebuild)
        self.rebuild_button.pressed.connect(self._dip_rebuild_button)
        rebuild_row.addWidget(self.rebuild_button, stretch=1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_rebuild)
        rebuild_row.addWidget(self.cancel_button)
        layout.addLayout(rebuild_row)

        self.progress_label = QLabel(PROGRESS_IDLE)
        self.progress_label.setSizePolicy(QSizePolicy.Preferred,
                                          QSizePolicy.Fixed)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Inline notice (T5): problems get a visible home that
        # stays until dismissed, not just a status-bar line.
        self.notice_frame = QFrame()
        self.notice_frame.setObjectName("noticeFrame")
        self.notice_frame.setSizePolicy(QSizePolicy.Preferred,
                                        QSizePolicy.Fixed)
        notice_layout = QHBoxLayout(self.notice_frame)
        notice_layout.setContentsMargins(12, 8, 12, 8)
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("noticeLabel")
        self.notice_label.setWordWrap(True)
        notice_layout.addWidget(self.notice_label, stretch=1)
        self.notice_dismiss = QPushButton("Dismiss")
        self.notice_dismiss.clicked.connect(self._hide_notice)
        notice_layout.addWidget(self.notice_dismiss)
        self.notice_frame.setVisible(False)
        layout.addWidget(self.notice_frame)

        # Getting-started checklist (T1).
        self.checklist_frame = QFrame()
        self.checklist_frame.setObjectName("checklistFrame")
        self.checklist_frame.setSizePolicy(QSizePolicy.Preferred,
                                           QSizePolicy.Fixed)
        check_layout = QVBoxLayout(self.checklist_frame)
        check_layout.setContentsMargins(16, 12, 16, 12)
        check_title = QLabel("Getting started")
        check_title.setStyleSheet("font-weight: bold;")
        check_layout.addWidget(check_title)
        self.check_step1 = QLabel("")
        self.check_step2 = QLabel("")
        self.check_step3 = QLabel("")
        check_layout.addWidget(self.check_step1)
        check_layout.addWidget(self.check_step2)
        check_layout.addWidget(self.check_step3)
        dismiss_row = QHBoxLayout()
        dismiss_row.addStretch(1)
        self.checklist_dismiss = QPushButton("Dismiss")
        self.checklist_dismiss.clicked.connect(
            self._dismiss_checklist)
        dismiss_row.addWidget(self.checklist_dismiss)
        check_layout.addLayout(dismiss_row)
        self.checklist_frame.setVisible(False)
        layout.addWidget(self.checklist_frame)

        # Results area (T3): bento, tabs, exports. Hidden until a
        # dictionary exists, so the first screen is three choices.
        self.results_area = QWidget()
        results_layout = QVBoxLayout(self.results_area)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(4)
        results_layout.addWidget(self._build_bento())

        self.tabs = QTabWidget()
        self._dictionary_tab_widget = self._dictionary_tab()
        self.tabs.addTab(self._dictionary_tab_widget, "Dictionary")
        self._skipped_tab_widget = self._skipped_tab()
        self.tabs.addTab(self._skipped_tab_widget, "Skipped files")
        self._help_tab_widget = self._help_tab()
        self.tabs.addTab(self._help_tab_widget, "Help")
        results_layout.addWidget(self.tabs, stretch=1)

        bottom_row = QHBoxLayout()
        self.tryit_button = QPushButton("Try it")
        self.tryit_button.clicked.connect(self._show_try_it)
        bottom_row.addWidget(self.tryit_button)
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
        results_layout.addLayout(bottom_row)
        self.results_area.setVisible(False)
        layout.addWidget(self.results_area, stretch=1)
        # Bottom spacer: with the results area hidden (first run),
        # a hidden widget's stretch is ignored and QBoxLayout
        # spreads the spare space evenly between the visible
        # widgets instead of pooling it at the bottom (proven by
        # probe: ~45 px gaps everywhere). The spacer takes it
        # instead; _set_results_visible switches its stretch off
        # once the results area is shown.
        self._central_layout = layout
        self._bottom_spacer_index = layout.count()
        layout.addStretch(1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")
        self.activity_light = QLabel("\u25cf")
        self.activity_light.setStyleSheet(LIGHT_IDLE)
        self.activity_text = QLabel("Ready")
        self.statusBar().addPermanentWidget(self.activity_light)
        self.statusBar().addPermanentWidget(self.activity_text)
        self._build_shortcuts()
        self._set_tab_order()
        self._refresh_buttons()

    def _build_menu(self):
        view_menu = self.menuBar().addMenu("View")
        self.tryit_action = view_menu.addAction("Try it")
        self.tryit_action.setShortcut("Ctrl+E")
        self.tryit_action.triggered.connect(self._show_try_it)
        view_menu.addSeparator()
        self.big_text_action = view_menu.addAction("Big text")
        self.big_text_action.setCheckable(True)
        self.big_text_action.setChecked(self._big_text)
        self.big_text_action.triggered.connect(self._toggle_big_text)
        self.reduced_motion_action = view_menu.addAction(
            "Reduced motion")
        self.reduced_motion_action.setCheckable(True)
        self.reduced_motion_action.setChecked(self._reduced_motion)
        self.reduced_motion_action.triggered.connect(
            self._toggle_reduced_motion)

        help_menu = self.menuBar().addMenu("Help")
        howto_action = help_menu.addAction("How to Use")
        howto_action.triggered.connect(self._show_how_to_use)
        about_action = help_menu.addAction("About %s" % APP_NAME)
        about_action.triggered.connect(self._show_about)

    def _build_shortcuts(self):
        """Ctrl+R rebuilds (T12). Ctrl+E is on the View menu's Try
        it action, so it opens the Try it window from here and
        encodes inside that window. The "/" key is caught by the
        event filter below, not a shortcut: a QShortcut would steal
        the slash from the folder field while typing a path."""
        self._rebuild_shortcut = QShortcut(
            QKeySequence("Ctrl+R"), self)
        self._rebuild_shortcut.activated.connect(self.rebuild)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        """"/" focuses the dictionary search (T12), except while
        typing in a text field, where the slash belongs to the
        text."""
        if (event.type() == QEvent.KeyPress
                and isinstance(watched, QWidget)
                and watched.window() is self
                and event.key() == Qt.Key_Slash
                and not event.modifiers() & (
                    Qt.ControlModifier | Qt.AltModifier
                    | Qt.MetaModifier)
                and not isinstance(watched, (QLineEdit,
                                             QPlainTextEdit,
                                             QTextEdit))):
            self._focus_search()
            return True
        return super().eventFilter(watched, event)

    def _set_tab_order(self):
        chain = [
            self.folder_edit, self.browse_button, self.open_button,
            self.rebuild_button, self.cancel_button,
            self.checklist_dismiss, self.notice_dismiss,
            self.search_edit, self.show_all_button, self.table,
            self.skipped_list, self.tryit_button,
            self.export_json_button, self.export_text_button,
            self.debug_button,
        ]
        for first, second in zip(chain, chain[1:]):
            self.setTabOrder(first, second)

    # -- bento (T6) ---------------------------------------------------
    def _make_tile(self, hero=False):
        """One bento tile: a big value over a small caption."""
        frame = QFrame()
        frame.setObjectName("heroTile" if hero else "tile")
        tile_layout = QVBoxLayout(frame)
        tile_layout.setContentsMargins(16, 6, 16, 6)
        value = QLabel("")
        value.setObjectName("heroValue" if hero else "tileValue")
        caption = QLabel("")
        caption.setObjectName("tileCaption")
        caption.setWordWrap(True)
        tile_layout.addWidget(value)
        tile_layout.addWidget(caption)
        tile_layout.addStretch(1)
        return frame, value, caption

    def _build_bento(self):
        """The results bento (entry 005): 4 columns, one hero tile
        2 wide, uniform 16 px gaps, 16 px rounded corners, 5 cells.
        Two rows, not three: a 2x2 hero plus a full-width sample
        row made the bento's minimum height 275 px, and the bento
        plus the table plus the bottom row did not fit the default
        window at all (580 px of minimums in 466 px of space) —
        the sample tile and the table both clipped (proven by
        probe)."""
        bento = QWidget()
        grid = QGridLayout(bento)
        grid.setSpacing(16)
        grid.setContentsMargins(0, 0, 0, 0)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        self.hero_tile, self.hero_value, self.hero_sub = \
            self._make_tile(hero=True)
        self.hero_value.setText("0%")
        self.hero_sub.setText(
            "Rebuild to see how much shorter your text gets.")
        grid.addWidget(self.hero_tile, 0, 0, 1, 2)

        self.files_tile, self.files_value, self.files_label = \
            self._make_tile()
        self.files_value.setText("0")
        self.files_label.setText("Files read")
        self.skipped_link = QPushButton("0 skipped")
        self.skipped_link.setObjectName("linkButton")
        self.skipped_link.clicked.connect(self._show_skipped_tab)
        self.skipped_link.setVisible(False)
        self.files_tile.layout().insertWidget(2, self.skipped_link)
        grid.addWidget(self.files_tile, 0, 2)

        self.words_tile, self.words_value, self.words_label = \
            self._make_tile()
        self.words_value.setText("0")
        self.words_label.setText("Words found")
        grid.addWidget(self.words_tile, 0, 3)

        self.codes_tile, self.codes_value, self.codes_label = \
            self._make_tile()
        self.codes_value.setText("0")
        self.codes_label.setText("Codes assigned")
        grid.addWidget(self.codes_tile, 1, 0, 1, 2)

        self.sample_tile = QFrame()
        self.sample_tile.setObjectName("tile")
        sample_layout = QVBoxLayout(self.sample_tile)
        sample_layout.setContentsMargins(16, 6, 16, 6)
        self.sample_caption = QLabel(
            "Sample: the first 100 characters, before and after")
        self.sample_caption.setObjectName("tileCaption")
        self.sample_caption.setWordWrap(True)
        self.sample_label = QLabel("Rebuild to see a sample.")
        self.sample_label.setWordWrap(True)
        self.sample_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse)
        sample_layout.addWidget(self.sample_caption)
        sample_layout.addWidget(self.sample_label)
        grid.addWidget(self.sample_tile, 1, 2, 1, 2)
        self._sample_layout = sample_layout
        self._refresh_sample_minimum()
        return bento

    def _update_sample_label(self):
        # The sample slice is shorter under Big text: the 100-char
        # sample is ~207 characters on screen, 3 lines at 11 pt
        # but 4 lines at 14 pt in the half-width tile — and the
        # bento's minimum at 14 pt already exceeds the window, so
        # the 4th line was clipped off (proven by probe). 60
        # characters is ~2 lines at 14 pt and still shows the
        # before/after. The caption always says which it is.
        if not self._sample_before:
            self.sample_label.setText("Rebuild to see a sample.")
            return
        chars = 60 if self._big_text else 100
        self.sample_caption.setText(
            "Sample: the first %d characters, before and after"
            % chars)
        self.sample_label.setText(
            "'%s'  ->  '%s'" % (self._sample_before[:chars],
                                self._sample_after[:chars]))

    def _refresh_sample_minimum(self):
        # Hard floor from the layout's own minimum, recomputed
        # from the CURRENT font: the grid squeezes the bento at the
        # default size, and without it the tile is crushed below
        # its wrapped text and the coded "after" line is clipped
        # off (proven by probe). Three lines covers the 100-char
        # sample at 11 pt and the 60-char sample at 14 pt.
        self.sample_label.setMinimumHeight(
            self.sample_label.fontMetrics().lineSpacing() * 3)
        self.sample_tile.setMinimumHeight(
            self._sample_layout.totalMinimumSize().height())

    # -- windows ------------------------------------------------------
    def _show_how_to_use(self):
        if self._howto_window is None:
            self._howto_window = HowToUseWindow(self.settings, self)
        self._howto_window.show()
        self._howto_window.raise_()
        self._howto_window.activateWindow()

    def _show_try_it(self):
        if self._tryit_window is None:
            self._tryit_window = TryItWindow(self, self.settings)
        self._tryit_window.refresh_buttons()
        self._tryit_window.show()
        self._tryit_window.raise_()
        self._tryit_window.activateWindow()

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

    # -- tabs ---------------------------------------------------------
    def _dictionary_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search the dictionary...")
        self.search_edit.textChanged.connect(
            self._on_search_changed)
        search_row.addWidget(self.search_edit, stretch=1)
        self.show_all_button = QPushButton("Show all")
        self.show_all_button.setCheckable(True)
        self.show_all_button.toggled.connect(
            self._on_show_all_toggled)
        search_row.addWidget(self.show_all_button)
        # The count sits in the search row, not on its own line:
        # the table needs the vertical room (at 1100x700 the old
        # separate label left the table one row tall).
        self.table_count_label = QLabel(
            "Most frequent first: top %d codes" % TOP_SHOWN)
        search_row.addWidget(self.table_count_label)
        layout.addLayout(search_row)
        self.table = QTableWidget(0, 3)
        self.table.setMinimumHeight(140)
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

    def _help_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        help_view = QPlainTextEdit()
        help_view.setReadOnly(True)
        help_view.setPlainText(quick_start_text())
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
        tab = self.settings.value("active_tab", 0, type=int)
        if 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
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
        if self._tryit_window is not None:
            self._tryit_window.close()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("source_folder",
                               self.folder_edit.text())
        self.settings.setValue("active_tab",
                               self.tabs.currentIndex())
        super().closeEvent(event)

    def _refresh_buttons(self):
        have_dict = bool(self.dictionary)
        self.tryit_button.setEnabled(have_dict)
        self.export_json_button.setEnabled(have_dict)
        self.export_text_button.setEnabled(have_dict)
        if self._tryit_window is not None:
            self._tryit_window.refresh_buttons()

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

    def _set_results_visible(self, visible):
        self.results_area.setVisible(visible)
        index = getattr(self, "_bottom_spacer_index", None)
        if index is not None:
            self._central_layout.setStretch(
                index, 0 if visible else 1)

    # -- notice (T5) --------------------------------------------------
    def _show_notice(self, text):
        self.notice_label.setText(text)
        self.notice_frame.setVisible(True)

    def _hide_notice(self):
        self.notice_frame.setVisible(False)

    # -- skipped surfacing (T9) ---------------------------------------
    def _update_skipped_badge(self, count):
        index = self.tabs.indexOf(self._skipped_tab_widget)
        if count > 0:
            self.tabs.setTabText(
                index, "Skipped files (%d)" % count)
            self.skipped_link.setText("%d skipped" % count)
            self.skipped_link.setVisible(True)
        else:
            self.tabs.setTabText(index, "Skipped files")
            self.skipped_link.setVisible(False)

    def _show_skipped_tab(self):
        self.tabs.setCurrentWidget(self._skipped_tab_widget)

    # -- search (T4) + presets (T11) ----------------------------------
    def _focus_search(self):
        if not self.results_area.isVisible():
            return
        self.tabs.setCurrentWidget(self._dictionary_tab_widget)
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _on_search_changed(self):
        self._fill_table()

    def _on_show_all_toggled(self, checked):
        self.show_all_button.setText(
            "Top 100" if checked else "Show all")
        self._fill_table()

    def _toggle_big_text(self):
        self._big_text = self.big_text_action.isChecked()
        self.settings.setValue("big_text", self._big_text)
        QApplication.instance().setStyleSheet(
            stylesheet(self._big_text))
        # Refit what the font change moves: the sample tile's floor
        # is measured in lines, the sample slice is shorter under
        # Big text, and the table columns were sized for the old
        # font (the "Times used" header clipped).
        self._refresh_sample_minimum()
        self._update_sample_label()
        self.table.resizeColumnsToContents()
        self.log.action("big text %s"
                        % ("on" if self._big_text else "off"))

    def _toggle_reduced_motion(self):
        self._reduced_motion = self.reduced_motion_action.isChecked()
        self.settings.setValue("reduced_motion",
                               self._reduced_motion)
        self.log.action("reduced motion %s"
                        % ("on" if self._reduced_motion else "off"))

    # -- motion (T10) ---------------------------------------------------
    def _dip_rebuild_button(self):
        """Button dip: 0.97 over 150 ms (entry 001). Skipped under
        Reduced motion; nothing runs at rest."""
        if self._reduced_motion:
            return
        button = self.rebuild_button
        if self._dip_anim is not None:
            self._dip_anim.stop()
            self._dip_anim = None
        # A previous dip interrupted mid-flight leaves the button
        # off its layout geometry; let the layout put it back
        # before measuring the start.
        row_layout = button.parentWidget().layout()
        if row_layout is not None:
            row_layout.activate()
        start = button.geometry()
        center = start.center()
        width = max(1, int(start.width() * 0.97))
        height = max(1, int(start.height() * 0.97))
        dipped = QRect(center.x() - width // 2,
                       center.y() - height // 2, width, height)
        self._dip_anim = QPropertyAnimation(button, b"geometry", self)
        self._dip_anim.setDuration(150)
        self._dip_anim.setKeyValueAt(0.0, start)
        self._dip_anim.setKeyValueAt(0.5, dipped)
        self._dip_anim.setKeyValueAt(1.0, start)
        # The layout owns this button's geometry and can fight the
        # animation mid-flight; pin the exact start on finish.
        self._dip_anim.finished.connect(
            lambda: button.setGeometry(start))
        self._dip_anim.start()

    def _finish_moment(self, report):
        """The rebuild payoff (entries 001, 008): the codes count
        ticks up and the hero tile fades in, both under 300 ms.
        Reduced motion keeps the final values and drops the motion.
        """
        if self._reduced_motion:
            return
        target = report.codes_assigned
        if self._tick_anim is not None:
            self._tick_anim.stop()
        self._tick_anim = QVariantAnimation(self)
        self._tick_anim.setStartValue(0)
        self._tick_anim.setEndValue(target)
        self._tick_anim.setDuration(250)
        self._tick_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._tick_anim.valueChanged.connect(
            lambda value: self.codes_value.setText("%d" % int(value)))
        self._tick_anim.finished.connect(
            lambda: self.codes_value.setText("%d" % target))
        self._tick_anim.start()
        if self._hero_anim is not None:
            self._hero_anim.stop()
        self.hero_tile.setGraphicsEffect(None)
        self._hero_effect = QGraphicsOpacityEffect(self.hero_tile)
        self._hero_effect.setOpacity(0.4)
        self.hero_tile.setGraphicsEffect(self._hero_effect)
        self._hero_anim = QPropertyAnimation(
            self._hero_effect, b"opacity", self)
        self._hero_anim.setStartValue(0.4)
        self._hero_anim.setEndValue(1.0)
        self._hero_anim.setDuration(250)
        self._hero_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hero_anim.finished.connect(
            lambda: self.hero_tile.setGraphicsEffect(None))
        self._hero_anim.start()

    # -- folder -------------------------------------------------------
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the Source Material folder",
            self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self.log.set_setting("source_folder", folder)
            self.log.action("source folder picked: %s" % folder)
            self._refresh_checklist()

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
            self._show_notice(
                "That folder does not exist: %s. Check the folder "
                "above, or press Browse to pick one that exists."
                % folder)
            self.log.warning("rebuild: folder missing: %s", folder)
            return
        if self._thread is not None:
            return  # a rebuild is already running
        self._hide_notice()
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
        self._set_results_visible(bool(self.dictionary))
        if report.files_read == 0:
            self._show_notice(
                "No readable text found in that folder. Drop some "
                "files into the folder and press Rebuild again.")
            self.statusBar().showMessage(
                "No readable text found. Drop some files into the "
                "folder and press Rebuild again.")
        else:
            self._ever_rebuilt = True
            self.settings.setValue("checklist_done", True)
            self._refresh_checklist()
            self._finish_moment(report)
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
        self._show_notice(
            "Rebuild failed. Press Debug report for details.")
        self.statusBar().showMessage(
            "Rebuild failed. Press Debug report for details.")

    def _show_report(self, report):
        if report.sample_text:
            self.hero_value.setText(
                "%.0f%%" % report.sample_saved_pct)
            self.hero_sub.setText(
                "%d characters saved" % report.sample_saved)
        else:
            self.hero_value.setText("0%")
            self.hero_sub.setText("No text to sample yet.")
        self.files_value.setText("%d" % report.files_read)
        self.words_value.setText("%d" % report.total_words)
        self.words_label.setText(
            "Words found (%d different)" % report.unique_words)
        self.codes_value.setText("%d" % report.codes_assigned)
        if report.sample_text:
            # Collapse runs of whitespace for display: a blank line
            # in the source (title, blank, body) otherwise shows as
            # a doubled space mid-sample. Stored whole; the label
            # shows a shorter slice under Big text (see below).
            self._sample_before = " ".join(
                report.sample_text[:100].split())
            self._sample_after = " ".join(
                report.sample_encoded[:100].split())
            self._update_sample_label()
        else:
            self._sample_before = ""
            self._sample_after = ""
            self.sample_label.setText("No text to sample yet.")
        self._fill_table()
        self.skipped_list.clear()
        for name, reason in report.files_skipped:
            self.skipped_list.addItem("%s: %s" % (name, reason))
        self._update_skipped_badge(len(report.files_skipped))
        if self._tryit_window is not None:
            self._tryit_window.try_result.setText("")

    def _table_entries(self):
        return sorted(
            self.dictionary.word_to_code.items(),
            key=lambda kv: (-self.dictionary.counts.get(kv[0], 0),
                            kv[0]))

    def _fill_table(self):
        """Fill the table, keeping the selection (by word) and the
        scroll position across rebuilds (T7, U28). The default view
        is the top 100; a search or Show all covers the whole
        dictionary (T4)."""
        selected_word = None
        current = self.table.currentRow()
        if current >= 0:
            item = self.table.item(current, 0)
            if item is not None:
                selected_word = item.text()
        # The scroll position is restored by word, not by number:
        # the scrollbar range is stale right after a refill (the
        # view lays out lazily), so a bare setValue() clamps to 0.
        # scrollToItem forces the layout first, so it lands right.
        top_word = None
        top_row = self.table.rowAt(0)
        if top_row >= 0:
            item = self.table.item(top_row, 0)
            if item is not None:
                top_word = item.text()
        scroll = self.table.verticalScrollBar().value()

        entries = self._table_entries()
        query = self.search_edit.text().strip().lower()
        if query:
            entries = [entry for entry in entries
                       if query in entry[0].lower()]
            count = len(entries)
            word = "match" if count == 1 else "matches"
            self.table_count_label.setText(
                "%d %s for '%s'" % (count, word, query))
        elif self.show_all_button.isChecked():
            self.table_count_label.setText(
                "All %d codes, most frequent first" % len(entries))
        elif len(entries) > TOP_SHOWN:
            entries = entries[:TOP_SHOWN]
            self.table_count_label.setText(
                "Most frequent first: top %d codes" % TOP_SHOWN)
        else:
            self.table_count_label.setText(
                "Most frequent first: all %d codes" % len(entries))
        self.table.setRowCount(len(entries))
        for row, (word, code) in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(word))
            self.table.setItem(row, 1,
                               QTableWidgetItem("~" + code))
            self.table.setItem(
                row, 2,
                QTableWidgetItem(
                    str(self.dictionary.counts.get(word, 0))))
        if selected_word is not None:
            for row, (word, _code) in enumerate(entries):
                if word == selected_word:
                    self.table.setCurrentCell(row, 0)
                    break
        if top_word is not None:
            for row, (word, _code) in enumerate(entries):
                if word == top_word:
                    item = self.table.item(row, 0)
                    if item is not None:
                        self.table.scrollToItem(
                            item,
                            QTableWidget.PositionAtTop)
                    break
        else:
            bar = self.table.verticalScrollBar()
            QTimer.singleShot(
                0, lambda: bar.setValue(
                    min(scroll, bar.maximum())))

    # -- dictionary file ----------------------------------------------
    def _save_dictionary(self, report):
        data = self.dictionary.to_json_dict()
        data["build"] = {
            "files_read": report.files_read,
            "files_skipped": len(report.files_skipped),
            "total_words": report.total_words,
            "unique_words": report.unique_words,
            "sample_saved": report.sample_saved,
            "sample_saved_pct": report.sample_saved_pct,
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
        self.hero_value.setText(
            "%.0f%%" % build.get("sample_saved_pct", 0.0))
        self.hero_sub.setText(
            "Loaded the saved dictionary. Press Rebuild to refresh "
            "it from the folder.")
        self.files_value.setText("%d" % build.get("files_read", 0))
        self.words_value.setText(
            "%d" % build.get("total_words", 0))
        self.words_label.setText(
            "Words found (%d different)"
            % build.get("unique_words", 0))
        self.codes_value.setText("%d" % len(self.dictionary))
        self._update_sample_label()
        self._fill_table()
        self._update_skipped_badge(build.get("files_skipped", 0))
        self._refresh_buttons()

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
            self._show_notice(
                "Could not write that file. Check the folder is "
                "writable and try again.")
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
            self._show_notice(
                "Could not write that file. Check the folder is "
                "writable and try again.")
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
    settings = QSettings(ORGANISATION, APP_NAME)
    big_text = settings.value("big_text", False, type=bool)
    app.setStyleSheet(stylesheet(big_text))
    app.setWindowIcon(app_icon())
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
