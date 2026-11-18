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
    QAbstractTableModel, QEvent, QObject, QPropertyAnimation,
    QEasingCurve, QRect, QSettings, QThread, QUrl, Qt, QTimer,
    Signal, QVariantAnimation,
)
from PySide6.QtGui import (
    QDesktopServices, QIcon, QKeySequence, QShortcut,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStatusBar, QTabWidget,
    QTableView, QTextEdit, QVBoxLayout, QWidget,
)

from . import APP_ID, APP_NAME, VERSION
from .debug_log import DebugLogger
from .engine import (MARKER, MIN_WORD_LEN, BuildReport,
                      QwkhndDictionary, SAMPLE_CHARS,
                      atomic_write_text, build_from_folder,
                      iter_tokens)

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
    /* T28: #d8d0b0 on #5c522f is 5.02:1 (the old #9a9178 was
       2.48:1, below the 4.5:1 floor). */
    color: #d8d0b0;
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
QTableView {
    background-color: #0f1a26;
    gridline-color: #22374d;
    selection-background-color: #f2c14e;
    selection-color: #14202e;
}
QTableView:focus {
    border: 2px solid #f2c14e;
}
QHeaderView::section {
    background-color: #1a2c3e;
    color: #b8c4d0;
    padding: 2px;
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
QLabel#warningLabel {
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


def help_sections():
    """The How to Use guide as (title, text) sections (T15). The
    window shows the titles as an index on the left and the
    section text on the right; help_text() joins them back into
    the full guide. The name and version come from
    qwkhnd/__init__.py, the one place they live, so a rename
    never leaves stale copy behind."""
    return [
        ("How to use",
         """How to use %(name)s

1. Drop files into your Source Material folder. The folder in the
   main window is the default. Use Browse to point at a different
   one, or Open folder to jump straight to it.
2. Press Rebuild dictionary. %(name)s reads every file it can
   and builds a new dictionary from scratch. The rebuild runs in
   the background, so the window stays usable, and you can press
   Cancel to stop it. The old dictionary stays in place until a
   rebuild finishes.
3. The words that save the most text get the shortest codes.
   Try it out in the Try it window (the Try it button, or the
   View menu), and export the dictionary as JSON or plain text.

One decoding rule: a code is the ~ sign plus all the letters
right after it, with no space. So ~brown is read as one code,
not as a short code plus the rest of a word. Put a space after
a code when you write shorthand by hand, so each code stands on
its own.
""" % {"name": APP_NAME}),
        ("What it reads",
         """What it reads: .txt, .md and other text files, .pdf files with a
text layer, .docx Word files, and .epub ebooks. HTML files are
read with the markup stripped. Other files are attempted as
plain text when they look like text.
"""),
        ("What it skips",
         """What it skips, and why (every skipped file is listed on the
Skipped files tab, with its reason):
- Images, audio and video: turning those into text needs OCR or
  speech recognition, which is not in v%(version)s.
- Archives, programs and other binary files: no readable text.
- Old .doc/.xls/.ppt files: save them as .docx to use them.
- Hidden files and folders, and scanned PDFs with no text layer.
- Symbolic links to files: Qwkhnd never follows them.
- Qwkhnd's own dictionary and log files: they are not source
  material, so they are skipped.
""" % {"version": VERSION}),
        ("Keyboard shortcuts",
         """Keyboard shortcuts: Ctrl+R rebuilds the dictionary, Ctrl+E opens
the Try it window, and / jumps to the dictionary search. Tab
moves to the next control, Shift+Tab to the previous one. The
full list is in Keyboard shortcuts on the Help menu. The / key
can be turned off in the View menu.
"""),
        ("Privacy",
         """%(name)s is fully offline. It never goes on the network, it
only reads files on this machine. Logs live in the logs folder
next to your dictionary, and the Debug report button writes a
scrubbed report you can send when something goes wrong.
""" % {"name": APP_NAME}),
    ]


def help_text():
    """The full Help text, with the app name + version filled in:
    the sections from help_sections() joined together. Shown in
    the How to Use window (U22). The Help tab holds the short
    quick-start instead (T8): the two never share sentences.
    """
    return "\n".join(text for _, text in help_sections())


def shortcuts_text():
    """The keyboard shortcuts list (T14): shown in the Help menu's
    Keyboard shortcuts window."""
    return ("Ctrl+R  Rebuild the dictionary\n"
            "Ctrl+E  Open the Try it window\n"
            "        (Encode inside the Try it window)\n"
            "/  Jump to the dictionary search\n"
            "   (turn it off in the View menu)\n"
            "Tab  Move to the next control\n"
            "Shift+Tab  Move to the previous control\n"
            "Ctrl+Q  Quit Qwkhnd")


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
3. Open the Try it window from the Try it button or the View
   menu and encode some text. Then export the dictionary as
   JSON or plain text.

For the full guide, open How to Use from the Help menu.
""" % {"name": APP_NAME}


class RebuildWorker(QObject):
    """Builds the dictionary off the UI thread (U30).

    Lives in a QThread. Progress, finished and failed are Qt
    signals, so the window hears about them on the main thread.
    request_cancel is checked before each file by the engine.
    """

    progress = Signal(int, int, str)  # done, total, file name
    file_progress = Signal(str, float)  # file name, fraction read
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
                cancelled=self._cancelled,
                file_progress=self.file_progress.emit)
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


class DictionaryTableModel(QAbstractTableModel):
    """The dictionary table, virtualized (T03).

    The view only builds the rows actually on screen, so Show all
    on a 200k-entry dictionary appears at once instead of freezing
    the window for a minute while 600,000 items are built by hand.
    The model holds the current entries (word, code, count);
    set_entries swaps them in one reset.
    """

    HEADERS = ("Word", "Code", "Times used")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._row_by_word = {}
        # T10 (v0.4): the user's sort, or -1 for the default
        # most-frequent-first order. A sort survives rebuilds
        # and searches: set_entries re-applies it (U28).
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder

    def set_entries(self, entries):
        self.beginResetModel()
        self._entries = list(entries)
        self._row_by_word = {word: row for row, (word, _, _)
                             in enumerate(self._entries)}
        self.endResetModel()
        self._apply_sort()

    def sort(self, column, order=Qt.AscendingOrder):
        """T10 (v0.4): header-click sorting. Called by the view
        when a header is clicked; the view toggles the order on
        a second click. The sort persists until the user picks
        another column — there is no click back to the default
        order, which is the standard table behaviour."""
        if column < 0 or column >= self.columnCount():
            return
        self._sort_column = column
        self._sort_order = order
        self._apply_sort()

    def _apply_sort(self):
        """Reorder the entries by the user's sort, keeping the
        selection on its row (the persistent indexes are remapped
        by entry, so the selected word stays selected)."""
        if self._sort_column < 0:
            return
        old = list(self._entries)
        self.layoutAboutToBeChanged.emit()
        reverse = self._sort_order == Qt.DescendingOrder
        self._entries.sort(key=lambda entry: entry[self._sort_column],
                           reverse=reverse)
        new_row = {id(entry): row
                   for row, entry in enumerate(self._entries)}
        for index in self.persistentIndexList():
            if index.isValid():
                entry = old[index.row()]
                self.changePersistentIndex(
                    index,
                    self.index(new_row[id(entry)], index.column()))
        self._row_by_word = {word: row for row, (word, _, _)
                             in enumerate(self._entries)}
        self.layoutChanged.emit()

    def sort_description(self):
        """The column the table is sorted by ("Word", "Code",
        "Times used"), or None for the default most-frequent-first
        order. The count label shows it (T10)."""
        if self._sort_column < 0:
            return None
        return self.HEADERS[self._sort_column]

    def entry_at(self, row):
        """The (word, code, count) tuple on one row, for the
        copy menu (T10)."""
        return self._entries[row]

    def rowCount(self, parent=None):
        if parent is not None and parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent=None):
        return 3

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        word, code, count = self._entries[index.row()]
        if index.column() == 0:
            return word
        if index.column() == 1:
            return "~" + code
        return str(count)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole \
                and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def row_for_word(self, word):
        """The row a word sits on, or -1. Used to restore the
        selection and the scroll position across rebuilds (T7)."""
        return self._row_by_word.get(word, -1)


class HowToUseWindow(QMainWindow):
    """The How to Use window, opened from the Help menu (U22).
    T15: a real index: the section list on the left, the section
    text on the right."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("How to Use %s" % APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(760, 520)
        geometry = self.settings.value("howto_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        split = QHBoxLayout()
        self.section_list = QListWidget()
        self.section_list.addItems(
            [title for title, _ in help_sections()])
        self.section_list.setMaximumWidth(180)
        self.section_list.currentRowChanged.connect(
            self._show_section)
        split.addWidget(self.section_list)
        self.section_view = QPlainTextEdit()
        self.section_view.setReadOnly(True)
        split.addWidget(self.section_view, stretch=1)
        layout.addLayout(split)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
        self.setCentralWidget(central)
        self.section_list.setCurrentRow(0)

    def _show_section(self, row):
        sections = help_sections()
        if 0 <= row < len(sections):
            self.section_view.setPlainText(sections[row][1])

    def closeEvent(self, event):
        self.settings.setValue("howto_geometry", self.saveGeometry())
        super().closeEvent(event)


class ShortcutsWindow(QMainWindow):
    """The Keyboard shortcuts window, opened from the Help menu
    (T14)."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Keyboard shortcuts")
        self.setWindowIcon(app_icon())
        self.resize(480, 320)
        geometry = self.settings.value("shortcuts_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(shortcuts_text())
        layout.addWidget(view)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)
        self.setCentralWidget(central)

    def closeEvent(self, event):
        self.settings.setValue("shortcuts_geometry",
                               self.saveGeometry())
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
        layout.addWidget(QLabel(
            "Type or paste text to encode, or shorthand to "
            "decode:"))
        self.try_input = QPlainTextEdit()
        self.try_input.setPlaceholderText(
            "Type something here after a rebuild...")
        layout.addWidget(self.try_input)
        layout.addWidget(QLabel(
            "This is the text you want to shorten."))
        # T17: a sample sentence to try, and a Clear that empties
        # the input, the output and the result line.
        helper_row = QHBoxLayout()
        self.sample_button = QPushButton("Try a sample sentence")
        self.sample_button.clicked.connect(self._try_sample)
        helper_row.addWidget(self.sample_button)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._try_clear)
        helper_row.addWidget(self.clear_button)
        helper_row.addStretch(1)
        layout.addLayout(helper_row)
        row = QHBoxLayout()
        self.encode_button = QPushButton("Encode")
        self.encode_button.clicked.connect(self._try_encode)
        row.addWidget(self.encode_button)
        self.decode_button = QPushButton("Decode")
        self.decode_button.clicked.connect(self._try_decode)
        row.addWidget(self.decode_button)
        self.copy_button = QPushButton("Copy result")
        self.copy_button.setToolTip(
            "Copy the result below to the clipboard so you can "
            "paste it somewhere else")
        self.copy_button.clicked.connect(self._try_copy)
        row.addWidget(self.copy_button)
        row.addStretch(1)
        layout.addLayout(row)
        # T16 (v0.4): whole files, not just pasted text. The
        # result is saved next to the file picked, never over it.
        file_row = QHBoxLayout()
        self.encode_file_button = QPushButton("Encode a file...")
        self.encode_file_button.setToolTip(
            "Encode a whole text file and save the shorthand "
            "next to it")
        self.encode_file_button.clicked.connect(
            lambda: self._try_file("encode"))
        file_row.addWidget(self.encode_file_button)
        self.decode_file_button = QPushButton("Decode a file...")
        self.decode_file_button.setToolTip(
            "Decode a whole shorthand file back to plain words "
            "and save it next to it")
        self.decode_file_button.clicked.connect(
            lambda: self._try_file("decode"))
        file_row.addWidget(self.decode_file_button)
        file_row.addStretch(1)
        layout.addLayout(file_row)
        layout.addWidget(QLabel(
            "The result is saved next to the file you pick."))
        self.try_output = QPlainTextEdit()
        self.try_output.setReadOnly(True)
        layout.addWidget(self.try_output)
        layout.addWidget(QLabel(
            "The result appears here. Encode turns the text above "
            "into shorthand. Decode turns shorthand above back "
            "into plain words."))
        self.try_result = QLabel("")
        self.try_result.setWordWrap(True)
        layout.addWidget(self.try_result)
        self.setCentralWidget(central)

        self.encode_shortcut = QShortcut(
            QKeySequence("Ctrl+E"), self)
        self.encode_shortcut.activated.connect(self._try_encode)
        self.refresh_buttons()

    def refresh_buttons(self):
        """Encode, Decode and the sample sentence need a
        dictionary (U6: nothing is selected or enabled before it
        can do real work). Copy needs a result to copy."""
        have_dict = bool(self.main_window.dictionary)
        self.encode_button.setEnabled(have_dict)
        self.decode_button.setEnabled(have_dict)
        self.encode_file_button.setEnabled(have_dict)
        self.decode_file_button.setEnabled(have_dict)
        self.sample_button.setEnabled(have_dict)
        self.copy_button.setEnabled(
            bool(self.try_output.toPlainText()))

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
        if saved < 0:
            # T11 (v0.4): encoding only lengthens text through
            # "~" escaping — say so plainly instead of "-1 saved
            # (-20%)", which reads like a bug.
            if "~" in text:
                reason = " A ~ in your text is written as ~~."
            else:
                reason = ""
            self.try_result.setText(
                "%d characters in, %d out. %d longer.%s"
                % (len(text), len(encoded), -saved, reason))
        else:
            message = ("%d characters in, %d out. %d saved (%.0f%%)"
                       % (len(text), len(encoded), saved, pct))
            if pct < 10 and self._has_uncovered_words(text):
                # T11 (v0.4): a tiny saving with words the
                # dictionary never saw gets one line of context.
                message += (" Words not in your dictionary stay "
                            "as they are. Rebuild with files that "
                            "use them to shrink them.")
            self.try_result.setText(message)
        self.main_window.log.action(
            "try-it encode: %d chars -> %d"
            % (len(text), len(encoded)))
        self.main_window._tried_it = True
        self.main_window.settings.setValue("tried_it", True)
        self.main_window._refresh_checklist()
        self.refresh_buttons()

    def _file_output_path(self, path, direction):
        """T16 (v0.4): encode writes name.qwkhnd.txt; decode
        strips a .qwkhnd marker if present, then writes
        name.decoded.txt. The source is never overwritten."""
        folder = os.path.dirname(path)
        base, ext = os.path.splitext(os.path.basename(path))
        ext = ext or ".txt"
        if direction == "encode":
            return os.path.join(folder, base + ".qwkhnd" + ext)
        if base.endswith(".qwkhnd"):
            base = base[:-len(".qwkhnd")]
        return os.path.join(folder, base + ".decoded" + ext)

    def _try_file(self, direction):
        """T16 (v0.4): encode or decode a whole file. The
        output is written next to the source with a generated
        name, so the source is never touched; a previous
        generated output is overwritten without asking — it is
        a generated file, not the user's work."""
        if direction == "encode":
            title = "Pick a text file to encode"
        else:
            title = "Pick a shorthand file to decode"
        path, _ = QFileDialog.getOpenFileName(
            self, title, "",
            "Text files (*.txt *.md);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            self.try_result.setText(
                "Could not read that file as plain text. "
                "Pick a .txt or .md file.")
            return
        dictionary = self.main_window.dictionary
        if direction == "encode":
            result = dictionary.encode(text)
        else:
            result = dictionary.decode(text)
        out_path = self._file_output_path(path, direction)
        try:
            atomic_write_text(out_path, result)
        except OSError:
            self.try_result.setText(
                "Could not write %s. Check the folder is "
                "writable and try again."
                % os.path.basename(out_path))
            return
        if direction == "encode":
            _, _, saved, pct = dictionary.savings(text)
            if saved < 0:
                detail = "%d longer" % -saved
            else:
                detail = "%d saved (%.0f%%)" % (saved, pct)
            self.try_result.setText(
                "%s written next to %s. %d characters in, "
                "%d out. %s."
                % (os.path.basename(out_path),
                   os.path.basename(path),
                   len(text), len(result), detail))
        else:
            self.try_result.setText(
                "%s written next to %s. %d characters in, "
                "%d out."
                % (os.path.basename(out_path),
                   os.path.basename(path),
                   len(text), len(result)))
        self.main_window.log.action(
            "try-it %s file: %s -> %s" % (direction, path, out_path))
        self.refresh_buttons()

    def _has_uncovered_words(self, text):
        """T11 (v0.4): True when the text holds a word long
        enough to shorten (3+ letters) that the dictionary has
        no code for — the words a rebuild could shrink."""
        dictionary = self.main_window.dictionary
        for is_word, token in iter_tokens(text):
            if is_word and len(token) >= MIN_WORD_LEN \
                    and token not in dictionary.word_to_code:
                return True
        return False

    def _try_sample(self):
        # T17: fill in a sentence that encodes shorter. The
        # sample from the last rebuild is real text from the
        # user's own files; without one, the most frequent coded
        # words do the same job.
        dictionary = self.main_window.dictionary
        sample = self.main_window._sample_before
        if sample:
            self.try_input.setPlainText(sample)
        else:
            words = sorted(
                dictionary.word_to_code,
                key=lambda w: (-dictionary.counts.get(w, 0), w))
            self.try_input.setPlainText(" ".join(words[:12]) + ".")
        self.try_output.setPlainText("")
        self.try_result.setText("")
        self.refresh_buttons()

    def _try_clear(self):
        # T17: empty the input, the output and the result line.
        self.try_input.setPlainText("")
        self.try_output.setPlainText("")
        self.try_result.setText("")
        self.refresh_buttons()

    def _try_copy(self):
        # T17: copy the result to the clipboard. The button says
        # so for a moment, then goes back to normal.
        text = self.try_output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.copy_button.setText("Copied!")
        QTimer.singleShot(
            1200, lambda: self.copy_button.setText("Copy result"))

    def _try_decode(self):
        # T07 (v0.4): Decode reads the input box, the only editable
        # one — Encode and Decode are mirrors now. The old code
        # decoded the output box, so shorthand pasted in could
        # never be decoded at all (F08). There is no round-trip
        # check here any more: with no expected text to compare
        # against, the engine suite is what guards the round-trip.
        text = self.try_input.toPlainText()
        if not text:
            self.try_result.setText("Type something first.")
            return
        dictionary = self.main_window.dictionary
        decoded = dictionary.decode(text)
        self.try_output.setPlainText(decoded)
        if MARKER not in text:
            self.try_result.setText(
                "No shorthand codes in that text, so nothing "
                "changed.")
        elif decoded == text:
            self.try_result.setText(
                "Those codes are not in your dictionary, so "
                "nothing changed.")
        else:
            self.try_result.setText(
                "Decoded: %d characters in, %d out."
                % (len(text), len(decoded)))
        self.main_window.log.action("try-it decode: %d chars"
                                    % len(text))
        self.refresh_buttons()


def _trim_sample(text, limit):
    """T08 (v0.4): trim a sample for display at a word boundary
    within limit characters, with an ellipsis when truncated.
    The old code sliced at exactly the limit, which could cut a
    code in half and show a lone "~" that means nothing. A cut
    that still ends on a "~" has it stripped, and a cut with no
    word boundary keeps the slice (a single long word has
    nowhere better to break). A string exactly at the limit
    is trimmed too: the stored sample is a 100-character slice
    of a longer text, so a string that fills the limit was
    almost certainly cut — and a cut that ends on a "~" is the
    bug this fixes."""
    if len(text) < limit:
        # A joined slice can come in under the limit yet still
        # end on a lone "~": _set_sample joins a 100-char slice
        # on whitespace, which can shrink it below the limit
        # while keeping a "~" whose code letter was cut off
        # (the shipped samples do exactly this: 99 chars ending
        # in " ~"). A complete encoding never ends on a lone
        # marker — a literal "~" is written as "~~" — so a "~"
        # that is its own last word is always a cut code, and
        # it goes. "~~" itself is kept: it ends in "~~", not
        # " ~", so the check below never matches a real escape.
        if text == "~":
            return ""
        if text.endswith(" ~"):
            return text[:-2]
        return text
    cut = text[:limit].rstrip("~")
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary > 0:
        cut = cut[:boundary]
    return cut + "…"


def _whole_words(slice_text, full_text):
    """Drop a trailing partial word from a cut slice.

    V04-FIX (verify): _set_sample takes the first 100 characters
    and the whitespace join kept a word the cut landed inside
    ("fox wa"). A slice ends mid-word when the text runs on past
    the cut with no space on either side of it; the last token
    then goes. A slice that ends at a word boundary, or is the
    whole text, is untouched — and a single token has nowhere
    better to break, so it stays (same rule as _trim_sample).
    No ellipsis here: the stored sample feeds the Try-it sample
    button, and a "…" baked in would be pasted as text."""
    joined = " ".join(slice_text.split())
    if len(full_text) <= len(slice_text):
        return joined
    if not slice_text or slice_text[-1].isspace():
        return joined
    if full_text[len(slice_text)].isspace():
        return joined
    if " " not in joined:
        return joined
    return joined.rsplit(" ", 1)[0]


class _GuardedTabWidget(QTabWidget):
    """T03 (v0.4): a QTabWidget that warns the main window before
    a programmatic page switch, so the scroll guard can arm in
    time. A programmatic switch moves focus into the new page,
    and the scroll area scrolls to show the focused widget —
    synchronously, inside the switch, before currentChanged
    fires, so no signal can arm a guard in time. Both
    setCurrentIndex and setCurrentWidget are overridden:
    setCurrentWidget does NOT route through setCurrentIndex
    (measured in PySide6 6.12), so overriding one alone leaves
    the other unguarded. A mouse click on a tab needs no guard
    (focus lands on the scroll area itself and the value never
    moves, measured) and does not go through these overrides:
    the tab bar drives the stacked widget directly."""

    def __init__(self, on_switch, parent=None):
        super().__init__(parent)
        self._on_switch = on_switch

    def setCurrentIndex(self, index):
        if index != self.currentIndex():
            self._on_switch()
        super().setCurrentIndex(index)

    def setCurrentWidget(self, widget):
        if widget is not self.currentWidget():
            self._on_switch()
        super().setCurrentWidget(widget)


class MainWindow(QMainWindow):
    """The Qwkhnd window, plus the Try it window it opens."""

    def __init__(self, data_dir=None, settings_path=None):
        super().__init__()
        self.data_dir = data_dir or default_data_dir()
        self.source_dir = os.path.join(self.data_dir, "Source Material")
        self.dict_path = os.path.join(
            self.data_dir, APP_ID + "-dictionary.json")
        # T11: the dictionary before the current one, for Restore.
        self.previous_dict_path = os.path.join(
            self.data_dir, APP_ID + "-dictionary.previous.json")
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
        self._sorted_entries = None  # T04: cached sort, rebuilt
        self._lower_words = None     # once per dictionary, not
        self._sample_before = ""     # once per keystroke.
        self._sample_after = ""
        # T18 (v0.4): [(word, count)] that got no code.
        self._uncovered_words = []
        # T19 (v0.4): the folder the current dictionary was
        # built from (None: imported, or none yet). Compared
        # against the folder field for the stale hint.
        self._dict_source_folder = None
        self._rebuild_folder = None
        self._thread = None
        self._worker = None
        self._rebuild_done = True
        self._ever_rebuilt = False
        # T13 (v0.4): whether the user tried Try it survives a
        # restart — the checklist stays until step 3 is done.
        self._tried_it = self.settings.value(
            "tried_it", False, type=bool)
        # T03 (v0.4): the tab-switch scroll guard (see
        # _GuardedTabWidget).
        self._tab_switch_guard = False
        self._tab_switch_scroll = 0
        self._howto_window = None
        self._tryit_window = None
        self._shortcuts_window = None
        self._single_instance = None
        self._big_text = self.settings.value(
            "big_text", False, type=bool)
        self._reduced_motion = self.settings.value(
            "reduced_motion", False, type=bool)
        self._slash_search = self.settings.value(
            "slash_search", True, type=bool)
        self._compact_table = self.settings.value(
            "compact_table", False, type=bool)
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
        """Show the getting-started checklist until all three
        steps are done (T1, entry 020; T13 v0.4: step 3 used to
        vanish with the first rebuild, so the checklist never
        showed it ticked). Dismissed means dismissed."""
        if self.settings.value("checklist_done", False, type=bool):
            self.checklist_frame.setVisible(False)
            return
        if self.dictionary and self._tried_it:
            self.checklist_frame.setVisible(False)
            return
        self.checklist_frame.setVisible(True)
        folder = self.folder_edit.text().strip() or self.source_dir
        has_files = os.path.isdir(folder) and bool(os.listdir(folder))
        self._set_check_step(
            self.check_step1,
            "Put files in the Source Material folder", has_files)
        # T13 (v0.4): a loaded dictionary counts as a rebuild —
        # _ever_rebuilt is False after a restart.
        self._set_check_step(self.check_step2,
                             "Press Rebuild dictionary",
                             self._ever_rebuilt or bool(self.dictionary))
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
        self.setAcceptDrops(True)  # T16: files and folders

        self._build_menu()

        central = QWidget(self)
        layout = QVBoxLayout(central)
        # T10 (v0.4): 6 px margins and 4 px gaps, not the 11/6
        # defaults — the table needs every pixel of the viewport
        # to show 8 rows at default size.
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Source Material folder:"))
        self.folder_edit = QLineEdit()
        # T16: drops fall through to the window, so a file dropped
        # on the field is copied in, not pasted as text.
        self.folder_edit.setAcceptDrops(False)
        self.folder_edit.setText(self.source_dir)
        # T18: check the folder when the field loses focus.
        self.folder_edit.editingFinished.connect(
            self._validate_folder)
        folder_row.addWidget(self.folder_edit, stretch=1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setToolTip(
            "Choose the folder Qwkhnd reads when it builds the "
            "dictionary")
        self.browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.browse_button)
        self.open_button = QPushButton("Open folder")
        self.open_button.setToolTip(
            "Open the Source Material folder in the file manager "
            "to add files")
        self.open_button.clicked.connect(self._open_folder)
        folder_row.addWidget(self.open_button)
        self.folder_warning = QLabel("")
        self.folder_warning.setObjectName("warningLabel")
        folder_row.addWidget(self.folder_warning)
        # T06 (v0.4): validate on every change of the field text,
        # not only on focus loss — a drop, a Browse pick, or a
        # restore updates the warning at once, so it can never go
        # stale (F07). Connected here, after the warning label
        # exists: the first setText above would otherwise call
        # _validate_folder before there is a label to write to.
        self.folder_edit.textChanged.connect(
            self._validate_folder)
        layout.addLayout(folder_row)

        hint = QLabel("Your books and documents go here. %s reads "
                      "them to build the dictionary." % APP_NAME)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        # T19 (v0.4): the stale hint — shown only when the
        # dictionary came from a different folder than the one
        # in the field above.
        self.stale_label = QLabel(
            "Dictionary is from a different folder. Press "
            "Rebuild to refresh it.")
        self.stale_label.setObjectName("warningLabel")
        self.stale_label.setWordWrap(True)
        self.stale_label.setVisible(False)
        layout.addWidget(self.stale_label)

        rebuild_row = QHBoxLayout()
        self.rebuild_button = QPushButton("Rebuild dictionary")
        self.rebuild_button.setObjectName("rebuildButton")
        self.rebuild_button.setToolTip(
            "Rebuild the dictionary from the Source Material "
            "folder (Ctrl+R)")
        self.rebuild_button.clicked.connect(self.rebuild)
        self.rebuild_button.pressed.connect(self._dip_rebuild_button)
        rebuild_row.addWidget(self.rebuild_button, stretch=1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip(
            "Stop the rebuild right now. The old dictionary "
            "stays in place.")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_rebuild)
        rebuild_row.addWidget(self.cancel_button)
        layout.addLayout(rebuild_row)

        # T10 (v0.4) + T13 (v0.4): the progress row is hidden
        # whenever no rebuild is running. The idle bar read as a
        # stalled "0%" (F19), and its 43 px belong to the table
        # (F15): at default size the table shows 8 rows with the
        # row hidden and 4 without it (measured). _set_working
        # shows the row when a rebuild starts.
        self.progress_label = QLabel(PROGRESS_IDLE)
        self.progress_label.setSizePolicy(QSizePolicy.Preferred,
                                          QSizePolicy.Fixed)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
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
        # T18 (v0.4): the checklist is NOT added to the main
        # layout — it goes at the top of the scroll area, above
        # the bento (see below). T13 keeps it visible until
        # step 3 is done, and at 169 px tall it left the table
        # 1 row tall when it sat above the scroll area; inside,
        # it scrolls away with the content.

        # Results area (T3): bento, tabs, exports. Hidden until a
        # dictionary exists, so the first screen is three choices.
        # T09: it lives in a scroll area, so the window minimum
        # stays small under Big text (the v0.2 minimum was 811 px
        # tall on a 768 px screen) and the bento is never squeezed
        # below its own height, which is what clipped the sample.
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        self.results_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff)
        self.results_area.setFrameShape(QFrame.NoFrame)
        # T03 (v0.4): the scroll guard. A programmatic tab switch
        # moves focus into the new page, and the scroll area
        # scrolls to show the focused widget — the jump happens
        # synchronously inside the switch, before currentChanged
        # fires, so the guard is armed by _GuardedTabWidget
        # before the switch runs, and holds the scroll value at
        # the moment it tries to move.
        self._tab_guard_timer = QTimer(self)
        self._tab_guard_timer.setSingleShot(True)
        self._tab_guard_timer.timeout.connect(
            self._clear_tab_switch_guard)
        self.results_area.verticalScrollBar().valueChanged.connect(
            self._on_results_scroll)
        results_inner = QWidget()
        results_layout = QVBoxLayout(results_inner)
        results_layout.setContentsMargins(0, 0, 0, 0)
        # T10 (v0.4): 2 px gaps, not 4 — the table needs every
        # pixel of the viewport to show 8 rows at default size.
        results_layout.setSpacing(2)
        # T18 (v0.4): the checklist is the scroll area's first
        # item, above the bento — the first screen still shows
        # folder, Rebuild and checklist, and after a rebuild the
        # checklist scrolls off instead of eating fixed viewport.
        results_layout.addWidget(self.checklist_frame)
        self._bento_widget = self._build_bento()
        results_layout.addWidget(self._bento_widget)

        self.tabs = _GuardedTabWidget(self._arm_tab_switch_guard)
        self._dictionary_tab_widget = self._dictionary_tab()
        self.tabs.addTab(self._dictionary_tab_widget, "Dictionary")
        self._skipped_tab_widget = self._skipped_tab()
        self.tabs.addTab(self._skipped_tab_widget, "Skipped files")
        self._help_tab_widget = self._help_tab()
        self.tabs.addTab(self._help_tab_widget, "Help")
        # T18 (v0.4): the uncovered-words tab goes AFTER Help,
        # so the existing tab indices 0-2 are unchanged.
        self._uncovered_tab_widget = self._uncovered_tab()
        self.tabs.addTab(self._uncovered_tab_widget,
                         "Words without codes")
        # T03 (v0.4): the tab widget is a _GuardedTabWidget, so
        # a programmatic switch arms the scroll guard first (U28:
        # an ordinary click must not move the user's place).
        results_layout.addWidget(self.tabs, stretch=1)

        bottom_row = QHBoxLayout()
        self.tryit_button = QPushButton("Try it")
        self.tryit_button.setToolTip(
            "Open a window to try the dictionary on your own "
            "text (Ctrl+E)")
        self.tryit_button.clicked.connect(self._show_try_it)
        bottom_row.addWidget(self.tryit_button)
        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.setToolTip(
            "Save the dictionary as a JSON file you can share, "
            "keep, or reuse")
        self.export_json_button.clicked.connect(self._export_json)
        bottom_row.addWidget(self.export_json_button)
        self.export_text_button = QPushButton("Export text file")
        self.export_text_button.setToolTip(
            "Save the dictionary as a plain text list of every "
            "word and code")
        self.export_text_button.clicked.connect(self._export_text)
        bottom_row.addWidget(self.export_text_button)
        self.debug_button = QPushButton("Debug report")
        self.debug_button.setToolTip(
            "Save a debug report with the details needed to fix "
            "a problem")
        self.debug_button.clicked.connect(self._debug_report)
        bottom_row.addWidget(self.debug_button)
        bottom_row.addStretch(1)
        results_layout.addLayout(bottom_row)
        # V04-FIX (verify): a stretch at the bottom of the scroll
        # area's content. On the first run the checklist is the
        # only visible item here, and with no stretchable widget
        # left (the tabs, stretch 1, are hidden) the layout
        # centres it — 220 px of dead space above it, measured.
        # The stretch absorbs the spare room only while the
        # results are hidden; once they show, the tabs take it
        # instead, so the table keeps its full height. The
        # stretch is set by _set_results_visible, like the
        # bottom spacer below.
        self._results_layout = results_layout
        self._results_spacer_index = results_layout.count()
        results_layout.addStretch(0)
        self.results_area.setWidget(results_inner)
        # T18 (v0.4): the scroll area is visible from the start
        # — it holds the checklist on the first screen. What
        # hides until a rebuild is the results inside it (bento,
        # tabs, bottom-row buttons); see _set_results_visible.
        layout.addWidget(self.results_area, stretch=1)
        # Bottom spacer: kept at stretch 0 (see
        # _set_results_visible) — the scroll area, stretch 1,
        # takes the spare space in both states now that it is
        # always visible.
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
        # T15: the File menu. Exports need a dictionary and Restore
        # needs a previous dictionary; _refresh_buttons keeps them
        # honest.
        file_menu = self.menuBar().addMenu("File")
        self.open_folder_action = file_menu.addAction("Open folder")
        self.open_folder_action.triggered.connect(self._open_folder)
        file_menu.addSeparator()
        self.export_json_action = file_menu.addAction("Export JSON")
        self.export_json_action.triggered.connect(self._export_json)
        self.export_text_action = file_menu.addAction(
            "Export text file")
        self.export_text_action.triggered.connect(self._export_text)
        # T17 (v0.4): importing is how you get a dictionary
        # without a rebuild, so it is always enabled.
        self.import_action = file_menu.addAction(
            "Import dictionary")
        self.import_action.triggered.connect(
            self._import_dictionary)
        self.debug_report_action = file_menu.addAction(
            "Debug report")
        self.debug_report_action.triggered.connect(
            self._debug_report)
        file_menu.addSeparator()
        self.restore_action = file_menu.addAction(
            "Restore previous dictionary")
        self.restore_action.triggered.connect(
            self._restore_previous_dictionary)
        file_menu.addSeparator()
        self.quit_action = file_menu.addAction("Quit")
        self.quit_action.setShortcut("Ctrl+Q")
        self.quit_action.triggered.connect(self.close)

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
        # T29: Compact rows fit more of the dictionary on screen;
        # Comfortable is the default.
        self.density_action = view_menu.addAction(
            "Compact table rows")
        self.density_action.setCheckable(True)
        self.density_action.setChecked(self._compact_table)
        self.density_action.triggered.connect(
            self._toggle_table_density)
        view_menu.addSeparator()
        # T14: the "/" search key can be turned off here.
        self.slash_search_action = view_menu.addAction(
            "Search with / key")
        self.slash_search_action.setCheckable(True)
        self.slash_search_action.setChecked(self._slash_search)
        self.slash_search_action.triggered.connect(
            self._toggle_slash_search)

        help_menu = self.menuBar().addMenu("Help")
        howto_action = help_menu.addAction("How to Use")
        howto_action.triggered.connect(self._show_how_to_use)
        shortcuts_action = help_menu.addAction(
            "Keyboard shortcuts")
        shortcuts_action.triggered.connect(self._show_shortcuts)
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
        if (self._slash_search
                and event.type() == QEvent.KeyPress
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

    # -- drag and drop (T16) ------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            # Highlight the folder field while a drop hovers.
            self.folder_edit.setStyleSheet(
                "border: 2px solid #c9a227;")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.folder_edit.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.folder_edit.setStyleSheet("")
        paths = [url.toLocalFile()
                 for url in event.mimeData().urls()]
        paths = [path for path in paths if path]
        if not paths:
            event.ignore()
            return
        self._handle_dropped_paths(paths)
        event.acceptProposedAction()

    def _handle_dropped_paths(self, paths):
        folders = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]
        if folders:
            # A dropped folder becomes the source folder (the last
            # one wins when several are dropped at once).
            folder = folders[-1]
            self.folder_edit.setText(folder)
            self.log.set_setting("source_folder", folder)
            self.log.action("source folder dropped: %s" % folder)
            self._refresh_checklist()
            self.statusBar().showMessage(
                "Source folder set to %s" % folder)
        if files:
            target = self.folder_edit.text().strip() \
                or self.source_dir
            os.makedirs(target, exist_ok=True)
            added = 0
            renamed = []
            for path in files:
                name = os.path.basename(path)
                dest = os.path.join(target, name)
                if os.path.abspath(path) == os.path.abspath(dest):
                    continue  # already in the folder
                new_name = None
                if os.path.exists(dest):
                    base, ext = os.path.splitext(name)
                    number = 2
                    while os.path.exists(dest):
                        dest = os.path.join(
                            target,
                            "%s (%d)%s" % (base, number, ext))
                        number += 1
                    new_name = os.path.basename(dest)
                try:
                    shutil.copy2(path, dest)
                    added += 1
                    # T14 (v0.4): only a copy that landed counts
                    # as a rename — a failed copy used no name.
                    if new_name is not None:
                        renamed.append(new_name)
                except OSError:
                    self.log.exception(
                        "could not copy dropped file %s", path)
            if added:
                # T14 (v0.4): a renamed file is named in the
                # message — the old "Added 1 file" never said
                # the file landed under a different name (F22).
                if len(renamed) == 1 and added == 1:
                    message = (
                        "Added 1 file as %s (that name was "
                        "taken). Press Rebuild to use it."
                        % renamed[0])
                elif renamed:
                    message = (
                        "Added %d files (%d saved under a new "
                        "name, e.g. %s). Press Rebuild to use "
                        "them." % (added, len(renamed),
                                   renamed[0]))
                else:
                    message = (
                        "Added %d file%s to the Source Material "
                        "folder. Press Rebuild to use them."
                        % (added, "" if added == 1 else "s"))
                self.statusBar().showMessage(message)
                self.log.action("dropped %d file(s) into %s"
                                % (added, target))
                self._refresh_checklist()

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
        self.hero_tile.setToolTip(
            "Saved: how much shorter a %s-char sample became "
            "with this dictionary" % "{:,}".format(SAMPLE_CHARS))
        grid.addWidget(self.hero_tile, 0, 0, 1, 2)

        self.files_tile, self.files_value, self.files_label = \
            self._make_tile()
        self.files_value.setText("0")
        self.files_label.setText("Files read")
        self.files_tile.setToolTip(
            "Files read: how many files Qwkhnd read to build this "
            "dictionary")
        self.skipped_link = QPushButton("0 skipped")
        self.skipped_link.setObjectName("linkButton")
        self.skipped_link.setToolTip(
            "Show the files that were skipped, with the reason "
            "for each one")
        self.skipped_link.clicked.connect(self._show_skipped_tab)
        self.skipped_link.setVisible(False)
        self.files_tile.layout().insertWidget(2, self.skipped_link)
        grid.addWidget(self.files_tile, 0, 2)

        self.words_tile, self.words_value, self.words_label = \
            self._make_tile()
        self.words_value.setText("0")
        self.words_label.setText("Words found")
        self.words_tile.setToolTip(
            "Words found: every word Qwkhnd counted, and how many "
            "were different")
        grid.addWidget(self.words_tile, 0, 3)

        self.codes_tile, self.codes_value, self.codes_label = \
            self._make_tile()
        self.codes_value.setText("0")
        self.codes_label.setText("Codes assigned")
        self.codes_tile.setToolTip(
            "Codes made: how many words got a shorthand code in "
            "this dictionary")
        # T18 (v0.4): the words-without-codes link, inside the
        # Codes tile like the skipped link inside the Files
        # tile. Hidden when every word has a code.
        self.uncovered_link = QPushButton("0 words have no code")
        self.uncovered_link.setObjectName("linkButton")
        self.uncovered_link.setToolTip(
            "Show the words that got no code, with the reason "
            "for each one")
        self.uncovered_link.clicked.connect(
            self._show_uncovered_tab)
        self.uncovered_link.setVisible(False)
        self.codes_tile.layout().insertWidget(2,
                                             self.uncovered_link)
        grid.addWidget(self.codes_tile, 1, 0, 1, 2)

        self.sample_tile = QFrame()
        self.sample_tile.setObjectName("tile")
        sample_layout = QVBoxLayout(self.sample_tile)
        sample_layout.setContentsMargins(16, 6, 16, 6)
        self.sample_caption = QLabel(
            "Sample: the start of your text, before and after")
        self.sample_caption.setObjectName("tileCaption")
        self.sample_caption.setWordWrap(True)
        self.sample_label = QLabel("Rebuild to see a sample.")
        self.sample_label.setWordWrap(True)
        self.sample_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse)
        sample_layout.addWidget(self.sample_caption)
        sample_layout.addWidget(self.sample_label)
        self.sample_tile.setToolTip(
            "Sample: the first characters of your text, before "
            "and after coding")
        grid.addWidget(self.sample_tile, 1, 2, 1, 2)
        self._sample_layout = sample_layout
        self._refresh_sample_minimum()
        return bento

    def _set_sample(self, before, after):
        # Collapse runs of whitespace for display: a blank line
        # in the source (title, blank, body) otherwise shows as
        # a doubled space mid-sample. Stored whole; the label
        # shows a shorter slice under Big text (see below).
        # V04-FIX (verify): the 100-char cut can land inside a
        # word — _whole_words drops the fragment, so the tile
        # never ends on half a word ("fox wa").
        self._sample_before = _whole_words(before[:100], before)
        self._sample_after = _whole_words(after[:100], after)
        self._update_sample_label()

    def _update_sample_label(self):
        # The sample slice is shorter under Big text: the 100-char
        # sample is ~207 characters on screen, 3 lines at 11 pt
        # but 4 lines at 14 pt in the half-width tile — and the
        # bento's minimum at 14 pt already exceeds the window, so
        # the 4th line was clipped off (proven by probe). 60
        # characters is ~2 lines at 14 pt and still shows the
        # before/after. T08 (v0.4): both slices are cut at a word
        # boundary (see _trim_sample), so the length varies — the
        # caption no longer names a character count.
        if not self._sample_before:
            self.sample_label.setText("Rebuild to see a sample.")
            return
        chars = 60 if self._big_text else 100
        self.sample_caption.setText(
            "Sample: the start of your text, before and after")
        self.sample_label.setText(
            "'%s'  ->  '%s'" % (
                _trim_sample(self._sample_before, chars),
                _trim_sample(self._sample_after, chars)))

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

    def _show_shortcuts(self):
        if self._shortcuts_window is None:
            self._shortcuts_window = ShortcutsWindow(
                self.settings, self)
        self._shortcuts_window.show()
        self._shortcuts_window.raise_()
        self._shortcuts_window.activateWindow()

    def _toggle_slash_search(self):
        self._slash_search = self.slash_search_action.isChecked()
        self.settings.setValue("slash_search", self._slash_search)

    def _apply_table_density(self):
        # T29: the row height follows the font, so Compact never
        # clips the text under Big text. T10 (v0.4): the padding
        # dropped from +12/+4 to +6/+2 — the old Comfortable rows
        # (32 px at 11 pt) left the table showing 4 rows at
        # default size; 26 px rows show 8 (measured), and the
        # text still has room to breathe.
        spacing = self.table.fontMetrics().lineSpacing()
        if self._compact_table:
            height = spacing + 2
        else:
            height = spacing + 6
        self.table.verticalHeader().setDefaultSectionSize(height)

    def _toggle_table_density(self):
        self._compact_table = self.density_action.isChecked()
        self.settings.setValue("compact_table",
                               self._compact_table)
        self._apply_table_density()

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
        # T10 (v0.4): 2 px gaps, not the default 6 — the table
        # needs every pixel of the viewport to show 8 rows at
        # default size.
        layout.setSpacing(2)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        # T16: drops fall through to the window.
        self.search_edit.setAcceptDrops(False)
        self.search_edit.setPlaceholderText(
            "Search the dictionary...")
        self.search_edit.setToolTip(
            "Search the dictionary by word. Press / to jump here "
            "from anywhere")
        self.search_edit.textChanged.connect(
            self._on_search_changed)
        search_row.addWidget(self.search_edit, stretch=1)
        self.show_all_button = QPushButton("Show all")
        self.show_all_button.setCheckable(True)
        self.show_all_button.setToolTip(
            "Show every code in the dictionary instead of only "
            "the top 100")
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
        # T10 (v0.4): the T14 hint line under the search box is
        # gone — it restated the placeholder ("Search the
        # dictionary...") and the tooltip, and its 18 px are a
        # row of the table. The field still explains itself
        # (U20) through the placeholder and the tooltip.
        # T18: shown only when a search finds nothing.
        # T15 (v0.4): a dead-end search says why it might have
        # failed and what fixes it — not just "try shorter".
        self.search_empty_label = QLabel(
            "No words match. It may not be in your Source "
            "Material. Try a shorter word, or rebuild with "
            "files that use it.")
        self.search_empty_label.setObjectName("warningLabel")
        self.search_empty_label.setVisible(False)
        layout.addWidget(self.search_empty_label)
        self.table_model = DictionaryTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.table_model)
        # T10 (v0.4): the table takes the room the hidden
        # progress row freed — 250 px shows 8 rows at the new
        # 26 px row height, and the scroll area still takes the
        # overflow under Big text.
        self.table.setMinimumHeight(250)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        # T10 (v0.4): header-click sorting (most-frequent-first
        # stays the default) and a right-click copy menu. The
        # count label refreshes on layoutChanged, which the model
        # emits after every sort — so the label always names the
        # order the table is actually in. (The lambda swallows
        # the signal's overload arguments.) The sort indicator
        # is cleared BEFORE sorting is enabled: a fresh header
        # points at column 0, and setSortingEnabled sorts by it
        # at once (column 0, descending — measured), which would
        # silently reorder the table before the user ever clicks
        # a header.
        self.table.horizontalHeader().setSortIndicator(
            -1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table_model.layoutChanged.connect(
            lambda *args: self._refresh_count_label())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            self._show_table_menu)
        self.table.setToolTip(
            "Right-click a row to copy its word, code, or the "
            "whole row. Ctrl+C copies the selected cell.")
        # NOTE: QTableView has no setUniformRowHeights (that is a
        # QTableWidget method); the view already asks the model
        # per row, which is the whole point of the virtual table.
        self._apply_table_density()
        layout.addWidget(self.table)
        # Search debounce (T04): the refill runs 200 ms after the
        # last keystroke, so typing never waits on a sort.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._fill_table)
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

    def _uncovered_tab(self):
        # T18 (v0.4): the words that got no code, most-used
        # first, with the reason for each one.
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(
            "Words in your files that got no code, and why:"))
        self.uncovered_list = QListWidget()
        layout.addWidget(self.uncovered_list)
        return tab

    # -- state --------------------------------------------------------
    def _restore_state(self):
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        folder = self.settings.value("source_folder")
        if folder:
            self.folder_edit.setText(folder)
        # T06 (v0.4): a moved folder warns on startup, as the
        # README promises — validate the restored path instead of
        # waiting for the user to tab through the field (F07).
        self._validate_folder()
        self.log.set_setting("source_folder",
                             self.folder_edit.text())
        tab = self.settings.value("active_tab", 0, type=int)
        if 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)

    def showEvent(self, event):
        super().showEvent(event)
        # T29: the table's font is still the 9pt default while the
        # window is being built, so the row height measured in
        # _dictionary_tab is 3px short; re-apply it now that the
        # 11pt stylesheet font has resolved. Idempotent and cheap.
        self._apply_table_density()

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        # T28: release the single-instance lock, so a fresh start
        # right after closing does not trip over a stale server.
        if self._single_instance is not None:
            self._single_instance.release()
            self._single_instance = None
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
        # T11 (v0.4): the View menu's Try it is disabled without
        # a dictionary too, like the button — opening the window
        # before the first rebuild showed a dead window (F21).
        # Disabling the action disables its Ctrl+E shortcut too.
        self.tryit_action.setEnabled(have_dict)
        self.export_json_button.setEnabled(have_dict)
        self.export_text_button.setEnabled(have_dict)
        self.export_json_action.setEnabled(have_dict)
        self.export_text_action.setEnabled(have_dict)
        # T11/T15: Restore is only possible once a previous
        # dictionary exists (after the second rebuild).
        self.restore_action.setEnabled(
            os.path.exists(self.previous_dict_path))
        if self._tryit_window is not None:
            self._tryit_window.refresh_buttons()

    def _set_working(self, working):
        """Activity light + buttons for the rebuilding state (U16).
        T10/T13 (v0.4): the progress row shows only while a
        rebuild runs; idle, it hides, so the table keeps its
        43 px and the first screen shows no stalled "0%" bar."""
        self.rebuild_button.setEnabled(not working)
        self.cancel_button.setEnabled(working)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(working)
        self.progress_bar.setVisible(working)
        if working:
            self.activity_light.setStyleSheet(LIGHT_WORKING)
            self.activity_text.setText("Working...")
        else:
            self.activity_light.setStyleSheet(LIGHT_IDLE)
            self.activity_text.setText("Ready")
            self.progress_label.setText(PROGRESS_IDLE)

    def _set_results_visible(self, visible):
        """Show or hide the results widgets — the bento, the
        tabs and the bottom-row buttons. The scroll area itself
        stays visible in both states: it holds the checklist
        (T18 v0.4), which is the first screen's third choice
        and must scroll away with the content instead of eating
        fixed viewport above it. The bottom spacer stays at
        stretch 0: the scroll area (stretch 1) takes the spare
        space in both states."""
        self._bento_widget.setVisible(visible)
        self.tabs.setVisible(visible)
        for button in (self.tryit_button, self.export_json_button,
                       self.export_text_button, self.debug_button):
            button.setVisible(visible)
        index = getattr(self, "_bottom_spacer_index", None)
        if index is not None:
            self._central_layout.setStretch(index, 0)
        # V04-FIX (verify): while the results are hidden, the
        # checklist is the only visible item in the scroll area
        # — the bottom stretch there takes the spare room so the
        # checklist sits at the top instead of floating mid-window.
        # Once the results show, the stretch goes back to 0 and
        # the tabs (stretch 1) take the room, as before.
        layout = getattr(self, "_results_layout", None)
        index = getattr(self, "_results_spacer_index", None)
        if layout is not None and index is not None:
            layout.setStretch(index, 0 if visible else 1)

    # -- notice (T5) --------------------------------------------------
    def _show_notice(self, text):
        # T28: the warning glyph marks the notice as a warning
        # even before the words are read.
        self.notice_label.setText("\u26a0  %s" % text)
        self.notice_frame.setVisible(True)

    def _hide_notice(self):
        self.notice_frame.setVisible(False)

    def _arm_tab_switch_guard(self):
        """T03: arm the scroll guard before a programmatic tab
        switch (called by _GuardedTabWidget). The guard holds
        the scroll value at the moment it tries to move, for
        300 ms, then releases: a deliberate scroll position is
        preserved, and a later scroll by the user is never
        blocked."""
        self._tab_switch_scroll = \
            self.results_area.verticalScrollBar().value()
        self._tab_switch_guard = True
        self._tab_guard_timer.start(300)

    def _disarm_tab_switch_guard(self):
        """T03: release the scroll guard at once. _focus_search
        uses this: it WANTS the scroll, because its job is to
        bring the search box into view."""
        self._tab_switch_guard = False
        self._tab_guard_timer.stop()

    def _on_results_scroll(self, value):
        """T03: while the tab-switch guard is armed, refuse any
        scroll move that is not the saved position. The setValue
        inside re-enters this handler once with the saved value,
        which passes the check and stops."""
        if self._tab_switch_guard \
                and value != self._tab_switch_scroll:
            self.results_area.verticalScrollBar().setValue(
                self._tab_switch_scroll)

    def _clear_tab_switch_guard(self):
        """T03: release the tab-switch scroll guard."""
        self._tab_switch_guard = False

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

    def _refresh_uncovered(self):
        """T18 (v0.4): the Codes-tile link, the tab badge and
        the list all follow self._uncovered_words."""
        count = len(self._uncovered_words)
        index = self.tabs.indexOf(self._uncovered_tab_widget)
        if count > 0:
            self.tabs.setTabText(
                index, "Words without codes (%d)" % count)
            if count == 1:
                self.uncovered_link.setText("1 word has no code")
            else:
                self.uncovered_link.setText(
                    "%d words have no code" % count)
            self.uncovered_link.setVisible(True)
        else:
            self.tabs.setTabText(index, "Words without codes")
            self.uncovered_link.setVisible(False)
        self.uncovered_list.clear()
        for word, _count in self._uncovered_words:
            if len(word) < MIN_WORD_LEN:
                reason = "too short to shrink"
            else:
                reason = ("the next code would not make it "
                          "shorter")
            self.uncovered_list.addItem("%s: %s" % (word, reason))

    def _show_uncovered_tab(self):
        self.tabs.setCurrentWidget(self._uncovered_tab_widget)

    # -- search (T4) + presets (T11) ----------------------------------
    def _focus_search(self):
        # T18 (v0.4): the tabs are the "has results" signal now
        # — the scroll area itself stays visible (it holds the
        # checklist), so it can no longer tell a first run from
        # a rebuild.
        if not self.tabs.isVisible():
            return
        self.tabs.setCurrentWidget(self._dictionary_tab_widget)
        # T03 (v0.4): the guarded switch armed the scroll guard;
        # release it before focusing the search box, because
        # this action WANTS the scroll — its job is to bring the
        # search box into view.
        self._disarm_tab_switch_guard()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _on_search_changed(self):
        # T04: restart the debounce timer; the previous results
        # stay visible until the new ones land.
        self._search_timer.start()

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
        self._apply_table_density()
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
    def _validate_folder(self):
        # T18: check the folder when the field loses focus, so a
        # typo is caught before Rebuild is pressed. An empty field
        # means the default folder, so it is not a warning.
        folder = self.folder_edit.text().strip()
        if not folder or os.path.isdir(folder):
            self.folder_warning.setText("")
        elif os.path.exists(folder):
            self.folder_warning.setText(
                "That is a file, not a folder.")
        else:
            self.folder_warning.setText(
                "That folder does not exist.")
        # T19 (v0.4): the folder field is also the stale hint's
        # input — _validate_folder runs on every change of the
        # field (textChanged), so the hint can never go stale.
        self._refresh_stale_hint()

    def _refresh_stale_hint(self):
        """T19 (v0.4): show the gold hint under the folder line
        when the dictionary came from a different folder than
        the one in the field — the folder changed since the last
        rebuild. An imported dictionary has no source folder,
        so it never shows the hint."""
        show = (bool(self.dictionary)
                and self._dict_source_folder is not None
                and os.path.normpath(
                    self.folder_edit.text().strip()
                    or self.source_dir)
                != os.path.normpath(self._dict_source_folder))
        self.stale_label.setVisible(show)

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
        # T06 (v0.4): refresh the warning before building, so it
        # can never be stale at the moment it matters (F07).
        self._validate_folder()
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
        # T19 (v0.4): remember which folder this rebuild read,
        # so the finished handler can record the dictionary's
        # source.
        self._rebuild_folder = folder
        self._rebuild_done = False
        self._set_working(True)
        self.statusBar().showMessage("Rebuilding the dictionary...")
        self._thread = QThread(self)
        self._worker = RebuildWorker(folder, self.log)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
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

    def _on_file_progress(self, name, fraction):
        # T08: progress inside one big file. T05 (v0.4): the label
        # keeps the overall story ("Reading file 5 of 150") and
        # the in-file percentage lives in the status bar only,
        # while the file is still being read — a file that read
        # in one chunk never flashes "100%" next to the overall
        # bar (F05).
        if self._worker is None:
            return  # cleaned up already (window closing)
        if fraction < 1.0:
            self.statusBar().showMessage(
                "Reading %s: %.0f%%" % (name, fraction * 100))

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
        if report.codes_assigned == 0:
            # T01 (v0.4): a rebuild that produced no dictionary
            # must not replace the current one. The old behaviour
            # saved the empty result over the good dictionary and
            # rotated the good one out of the previous slot, so
            # two empty rebuilds lost it for good (F01). Now the
            # dictionary, the saved file and the previous file all
            # stay exactly as they were, and the notice says so.
            self._on_rebuild_no_result(report)
            return
        self._set_dictionary(dictionary)
        # T19 (v0.4): the dictionary's source is the folder
        # this rebuild read — recorded before the save, so the
        # build record carries it.
        self._dict_source_folder = self._rebuild_folder
        self._show_report(report)
        saved = self._save_dictionary(report)
        self._refresh_buttons()
        self._set_results_visible(bool(self.dictionary))
        self._refresh_stale_hint()
        if not saved:
            self.statusBar().showMessage(
                "Rebuilt, but the dictionary could not be saved")
        else:
            self._ever_rebuilt = True
            # T13 (v0.4): a rebuild no longer marks the
            # checklist done — it stays until step 3 (Try it)
            # is done too.
            self._refresh_checklist()
            self._finish_moment(report)
            # T28: the status bar confirms the dictionary was
            # saved, not just rebuilt.
            self.statusBar().showMessage(
                "Rebuilt: %d files, %d words, %d codes. "
                "Dictionary saved."
                % (report.files_read, report.total_words,
                   report.codes_assigned))

    def _on_rebuild_no_result(self, report):
        """A finished rebuild that produced zero codes (T01/T02).

        Nothing is replaced: the dictionary on screen, the saved
        file and the previous file all stay as they were. The
        skipped list still updates, so the Skipped tab explains a
        folder full of unreadable files. The notice names the
        real case: an empty folder, files none of which could be
        read, or files read but no word long enough to shorten.
        """
        self._show_skipped_list(report.files_skipped)
        if report.files_read == 0 and not report.files_skipped:
            message = ("That folder is empty, so there was nothing "
                       "to read. Drop some files into the folder "
                       "and press Rebuild again.")
            short = "That folder is empty."
        elif report.files_read == 0:
            count = len(report.files_skipped)
            message = ("None of the files in that folder could be "
                       "read (%d skipped). See the Skipped files "
                       "tab for why. Drop some readable files "
                       "into the folder and press Rebuild again."
                       % count)
            short = ("None of the files in that folder could be "
                     "read.")
        else:
            message = ("Your files were read, but no word in them "
                       "was long enough to shorten. Words need at "
                       "least 3 letters to get a code.")
            short = ("Your files were read, but no word was long "
                     "enough to shorten.")
        if self.dictionary:
            message += " Your dictionary is unchanged."
            short += " Your dictionary is unchanged."
        self._show_notice(message)
        self.statusBar().showMessage(short)
        self.log.action("rebuild found nothing; dictionary unchanged")

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
            # T04 (v0.4): the hero is measured on the
            # SAMPLE_CHARS sample while the tile shows only its
            # first 100 characters — label the basis, so the two
            # numbers no longer look like they contradict each
            # other (F04).
            self.hero_sub.setText(
                "%d characters saved, on a %s-character sample"
                % (report.sample_saved,
                   "{:,}".format(SAMPLE_CHARS)))
        else:
            self.hero_value.setText("0%")
            self.hero_sub.setText("No text to sample yet.")
        self.files_value.setText("%d" % report.files_read)
        self.words_value.setText("%d" % report.total_words)
        self.words_label.setText(
            "Words found (%d different)" % report.unique_words)
        self.codes_value.setText("%d" % report.codes_assigned)
        if report.sample_text:
            self._set_sample(report.sample_text,
                             report.sample_encoded)
        else:
            self._sample_before = ""
            self._sample_after = ""
            self.sample_label.setText("No text to sample yet.")
        self._fill_table()
        self._show_skipped_list(report.files_skipped)
        # T18 (v0.4): the words that got no code, from the
        # report — a no-result rebuild never reaches here, so
        # the list stays untouched on one (T01).
        self._uncovered_words = list(report.uncovered_words)
        self._refresh_uncovered()
        if self._tryit_window is not None:
            self._tryit_window.try_result.setText("")

    def _show_skipped_list(self, files_skipped):
        """Fill the Skipped tab and its badge from one rebuild's
        skipped list. Shared by the report and the no-result path
        (T02): a failed rebuild still explains itself there."""
        self.skipped_list.clear()
        for name, reason in files_skipped:
            self.skipped_list.addItem("%s: %s" % (name, reason))
        self._update_skipped_badge(len(files_skipped))

    def _set_dictionary(self, dictionary):
        """Swap in a new dictionary and drop the cached sort (T04):
        every production path that replaces the dictionary goes
        through here, so the cache can never go stale."""
        self.dictionary = dictionary
        self._sorted_entries = None
        self._lower_words = None

    def _table_entries(self):
        """Sorted (word, code) entries, cached (T04): the sort runs
        once per dictionary, not once per keystroke. The lowercase
        words are precomputed alongside, so the search filter
        never calls .lower() per entry per keystroke."""
        if self._sorted_entries is None:
            self._sorted_entries = sorted(
                self.dictionary.word_to_code.items(),
                key=lambda kv: (-self.dictionary.counts.get(kv[0], 0),
                                kv[0]))
            self._lower_words = [word.lower() for word, _
                                 in self._sorted_entries]
        return self._sorted_entries

    def _fill_table(self):
        """Fill the table, keeping the selection (by word) and the
        scroll position across rebuilds (T7, U28). The default view
        is the top 100; a search or Show all covers the whole
        dictionary (T4). The model is virtual (T03): handing it
        the entry list is one reset, not one widget per cell."""
        selected_word = None
        current = self.table.currentIndex()
        if current.isValid():
            selected_word = self.table_model.data(
                self.table_model.index(current.row(), 0))
        # The scroll position is restored by word, not by number:
        # the scrollbar range is stale right after a refill (the
        # view lays out lazily), so a bare setValue() clamps to 0.
        # scrollTo forces the layout first, so it lands right.
        top_word = None
        top_row = self.table.rowAt(0)
        if top_row >= 0:
            top_word = self.table_model.data(
                self.table_model.index(top_row, 0))
        scroll = self.table.verticalScrollBar().value()

        entries = self._table_entries()
        query = self.search_edit.text().strip().lower()
        self.search_empty_label.setVisible(False)
        if query:
            entries = [entry for entry, lower in
                       zip(entries, self._lower_words)
                       if query in lower]
            self.search_empty_label.setVisible(len(entries) == 0)
        self._refresh_count_label(entries, query)
        if not query and not self.show_all_button.isChecked() \
                and len(entries) > TOP_SHOWN:
            entries = entries[:TOP_SHOWN]
        rows = [(word, code, self.dictionary.counts.get(word, 0))
                for word, code in entries]
        self.table.setUpdatesEnabled(False)
        try:
            self.table_model.set_entries(rows)
        finally:
            self.table.setUpdatesEnabled(True)
        if selected_word is not None:
            row = self.table_model.row_for_word(selected_word)
            if row >= 0:
                self.table.setCurrentIndex(
                    self.table_model.index(row, 0))
        if top_word is not None:
            row = self.table_model.row_for_word(top_word)
            if row >= 0:
                self.table.scrollTo(
                    self.table_model.index(row, 0),
                    QTableView.PositionAtTop)
        else:
            bar = self.table.verticalScrollBar()
            QTimer.singleShot(
                0, lambda: bar.setValue(
                    min(scroll, bar.maximum())))

    def _refresh_count_label(self, entries=None, query=None):
        """Set the count label from the table state (T10): the
        label always names the order the table is actually in —
        "Most frequent first" by default, "Sorted by Word" (or
        Code, or Times used) once the user has clicked a header.
        Called by _fill_table with the filtered entries, and by
        the model's layoutChanged after a sort (when the entries
        are recomputed from the current state)."""
        if entries is None:
            entries = self._table_entries()
            if query is None:
                query = self.search_edit.text().strip().lower()
            if query:
                entries = [entry for entry, lower in
                           zip(entries, self._lower_words)
                           if query in lower]
        sort = self.table_model.sort_description()
        if sort is not None:
            order_cap = "Sorted by %s" % sort
            order_low = "sorted by %s" % sort
        else:
            order_cap = "Most frequent first"
            order_low = "most frequent first"
        if query:
            count = len(entries)
            word = "match" if count == 1 else "matches"
            if sort is not None:
                text = "%s: %d %s for '%s'" % (
                    order_cap, count, word, query)
            else:
                text = "%d %s for '%s'" % (count, word, query)
        elif self.show_all_button.isChecked():
            text = "All %d codes, %s" % (len(entries), order_low)
        elif len(entries) > TOP_SHOWN:
            text = "%s: top %d codes" % (order_cap, TOP_SHOWN)
        else:
            text = "%s: all %d codes" % (order_cap, len(entries))
        self.table_count_label.setText(text)

    def _table_menu_for(self, index):
        """T10 (v0.4): the right-click menu for one table row.
        Split from _show_table_menu so tests can build the menu
        and trigger its actions without a modal loop."""
        word, code, _count = self.table_model.entry_at(index.row())
        menu = QMenu(self)
        copy_word = menu.addAction("Copy word")
        copy_word.triggered.connect(
            lambda: QApplication.clipboard().setText(word))
        copy_code = menu.addAction("Copy code")
        copy_code.triggered.connect(
            lambda: QApplication.clipboard().setText("~" + code))
        copy_row = menu.addAction("Copy row")
        copy_row.triggered.connect(
            lambda: QApplication.clipboard().setText(
                "%s: ~%s" % (word, code)))
        return menu

    def _show_table_menu(self, pos):
        """T10 (v0.4): show the copy menu for the row under the
        cursor (nothing happens on empty space)."""
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        self.table.setCurrentIndex(index)
        self._table_menu_for(index).exec(
            self.table.mapToGlobal(pos))

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
            # T10: the skipped list and the sample survive a
            # restart, so the Skipped tab and the sample tile are
            # full on load, not only after a rebuild.
            "files_skipped_list": [[name, reason] for name, reason
                                   in report.files_skipped],
            "sample_before": report.sample_text,
            "sample_after": report.sample_encoded,
            # T18 (v0.4): the words that got no code survive a
            # restart, like the skipped list and the sample.
            # The overhead is ~1-2% of the save file even on a
            # huge corpus: uncovered words are bounded by the
            # short words plus the long tail whose code would be
            # too long.
            "uncovered_words": [[word, count] for word, count
                                in report.uncovered_words],
            # T19 (v0.4): the folder this dictionary was built
            # from (null when imported — an imported dictionary
            # has no source folder).
            "source_folder": self._dict_source_folder,
        }
        # T11: keep the old dictionary as the previous one, so a
        # rebuild gone wrong can be undone from the File menu.
        if os.path.exists(self.dict_path):
            try:
                shutil.copyfile(self.dict_path,
                                self.previous_dict_path)
            except OSError:
                self.log.exception("could not keep the previous "
                                   "dictionary")
        try:
            atomic_write_text(
                self.dict_path,
                json.dumps(data, ensure_ascii=False, indent=2)
                + "\n")
        except OSError:
            self.log.exception("could not save the dictionary")
            return False
        return True

    def _restore_previous_dictionary(self):
        # T11: bring back the dictionary from before the last
        # rebuild. The previous file is kept, so Restore can be
        # pressed again (it just restores the same dictionary);
        # the next rebuild rotates it out as usual.
        if not os.path.exists(self.previous_dict_path):
            return
        try:
            with open(self.previous_dict_path,
                      encoding="utf-8") as fh:
                data = json.load(fh)
            dictionary = QwkhndDictionary.from_json_dict(data)
        except (OSError, ValueError, TypeError, KeyError,
                AttributeError):
            self.log.exception("previous dictionary would not load")
            self._show_notice(
                "The previous dictionary was damaged, so it could "
                "not be restored.")
            return
        if len(dictionary) == 0:
            # T01 (v0.4): an empty previous file is not a restore.
            # The old code claimed success while restoring nothing
            # (F02); say so instead, and leave everything alone.
            self._show_notice(
                "The previous dictionary was empty, so there was "
                "nothing to restore.")
            self.statusBar().showMessage(
                "The previous dictionary was empty.")
            return
        try:
            atomic_write_text(
                self.dict_path,
                json.dumps(data, ensure_ascii=False, indent=2)
                + "\n")
        except OSError:
            self.log.exception("could not save the restored "
                               "dictionary")
            self._show_notice(
                "The previous dictionary could not be saved. "
                "Check the folder is writable and try again.")
            return
        self._set_dictionary(dictionary)
        # T19 (v0.4): Restore uses the restored build record's
        # source when it has one; an older record without the
        # key leaves the current source alone (the startup-load
        # fallback to the folder field would be wrong here —
        # the restored dictionary did not come from it).
        build = data.get("build")
        keep_source = (not isinstance(build, dict)
                       or "source_folder" not in build)
        previous_source = self._dict_source_folder
        self._show_loaded_build(build)
        if keep_source:
            self._dict_source_folder = previous_source
            self._refresh_stale_hint()
        self._refresh_buttons()
        self._set_results_visible(bool(self.dictionary))
        self.statusBar().showMessage(
            "Restored the previous dictionary.")
        self.log.action("previous dictionary restored")

    def _load_saved_dictionary(self):
        if not os.path.exists(self.dict_path):
            return
        try:
            with open(self.dict_path, encoding="utf-8") as fh:
                data = json.load(fh)
            self._set_dictionary(
                QwkhndDictionary.from_json_dict(data))
        except (OSError, ValueError, TypeError, KeyError,
                AttributeError):
            # T01: a damaged dictionary must never kill the start.
            # from_json_dict raises ValueError on every malformed
            # shape; the wider catch is belt and braces, so the
            # window always opens and says what happened.
            self.log.exception("saved dictionary would not load")
            self._set_dictionary(QwkhndDictionary())
            # T02: name Restore, the faster recovery, when a
            # previous dictionary exists (F23, as the README
            # already promises).
            message = ("The saved dictionary was damaged, so "
                       "Qwkhnd started empty. Press Rebuild to "
                       "make a new one.")
            if os.path.exists(self.previous_dict_path):
                message += (" Or use File \u2192 Restore previous "
                            "dictionary to bring back the one from "
                            "before the last rebuild.")
            self._show_notice(message)
            return
        self._show_loaded_build(data.get("build"))
        self.hero_sub.setText(
            "Loaded the saved dictionary. Press Rebuild to refresh "
            "it from the folder.")

    def _show_loaded_build(self, build):
        """Fill the bento, sample, table and skipped list from a
        saved dictionary's build record. Shared by the start-up
        load and by Restore (T11)."""
        if not isinstance(build, dict):
            build = {}
        self.hero_value.setText(
            "%.0f%%" % build.get("sample_saved_pct", 0.0))
        if build.get("sample_saved"):
            self.hero_sub.setText(
                "%d characters saved, on a %s-character sample"
                % (build["sample_saved"],
                   "{:,}".format(SAMPLE_CHARS)))
        self.files_value.setText("%d" % build.get("files_read", 0))
        self.words_value.setText(
            "%d" % build.get("total_words", 0))
        self.words_label.setText(
            "Words found (%d different)"
            % build.get("unique_words", 0))
        self.codes_value.setText("%d" % len(self.dictionary))
        # T10: restore the sample and the skipped list. A v0.2 file
        # has neither key: it still loads, with an empty skipped
        # list and the "Rebuild to see a sample" label.
        before = build.get("sample_before")
        after = build.get("sample_after")
        if isinstance(before, str) and before:
            self._set_sample(
                before, after if isinstance(after, str) else "")
        else:
            self._update_sample_label()
        self._fill_table()
        # T19 (v0.4): restore the dictionary's source folder. A
        # present key with a null value means imported (no
        # source, never stale). An older save has no key at all:
        # assume the current folder — no stale hint on load, the
        # folder field is the best guess for where the
        # dictionary came from.
        if "source_folder" in build:
            source = build["source_folder"]
            self._dict_source_folder = (source if isinstance(
                source, str) else None)
        else:
            self._dict_source_folder = (
                self.folder_edit.text().strip() or self.source_dir)
        self._refresh_stale_hint()
        # T18 (v0.4): restore the words that got no code. An
        # older save has no such key: the list is empty, and the
        # tab honestly shows nothing until the next rebuild.
        uncovered = build.get("uncovered_words")
        if isinstance(uncovered, list):
            self._uncovered_words = [
                (entry[0], entry[1]) for entry in uncovered
                if isinstance(entry, (list, tuple))
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], int)]
        else:
            self._uncovered_words = []
        self._refresh_uncovered()
        skipped = build.get("files_skipped_list")
        if isinstance(skipped, list):
            self.skipped_list.clear()
            for entry in skipped:
                if isinstance(entry, (list, tuple)) \
                        and len(entry) == 2:
                    self.skipped_list.addItem(
                        "%s: %s" % (entry[0], entry[1]))
            self._update_skipped_badge(len(skipped))
        else:
            self._update_skipped_badge(
                build.get("files_skipped", 0))
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
        self._show_saved("Dictionary exported to",
                         "Last JSON export", path)
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
        self._show_saved("Dictionary exported to",
                         "Last text export", path)
        self.log.action("dictionary exported as text to %s" % path)

    def _import_dictionary(self):
        """T17 (v0.4): bring in a dictionary exported from
        another Qwkhnd (or another machine). The file is
        validated before anything is touched — a bad file leaves
        the current dictionary, the saved file and the previous
        file exactly as they were (the T01 no-wipe rule)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a dictionary",
            self.data_dir, "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            dictionary = QwkhndDictionary.from_json_dict(data)
        except OSError:
            self.log.exception("dictionary import failed")
            self._show_notice(
                "Could not read that file. Check it exists and "
                "try again.")
            return
        except json.JSONDecodeError:
            self.log.exception("dictionary import failed")
            self._show_notice(
                "That file is not a Qwkhnd dictionary. It does "
                "not look like JSON.")
            return
        except (ValueError, TypeError, KeyError,
                AttributeError) as exc:
            self.log.exception("dictionary import failed")
            self._show_notice(
                "Could not import that file: %s." % exc)
            return
        if len(dictionary) == 0:
            self._show_notice(
                "That file holds no codes, so there was nothing "
                "to import.")
            return
        self._set_dictionary(dictionary)
        # A synthetic build record: the import has no source
        # files, so the bento shows what the dictionary itself
        # knows — its word counts and its size. The sample is
        # cleared: the old dictionary's sample is not this
        # dictionary's. T19 (v0.4): an imported dictionary has
        # no source folder, so it never shows the stale hint.
        self._dict_source_folder = None
        self._sample_before = ""
        self._sample_after = ""
        report = BuildReport()
        report.files_read = 0
        report.total_words = sum(dictionary.counts.values())
        report.unique_words = len(dictionary)
        report.codes_assigned = len(dictionary)
        if not self._save_dictionary(report):
            self._show_notice(
                "The dictionary was imported, but it could not "
                "be saved. Check the data folder is writable.")
        self._show_loaded_build({
            "files_read": 0,
            "total_words": report.total_words,
            "unique_words": report.unique_words,
            "sample_saved": 0,
            "sample_saved_pct": 0.0,
            # An empty skipped list, not a missing one: without
            # this key _show_loaded_build leaves the old
            # dictionary's skipped entries on screen.
            "files_skipped_list": [],
            # T19 (v0.4): a present null source, not a missing
            # key — a missing key would fall back to the folder
            # field, and an imported dictionary has no source.
            "source_folder": None,
        })
        # An imported dictionary has no measured sample, so the
        # hero shows a dash, not a 0% that was never measured.
        self.hero_value.setText("-")
        self.hero_sub.setText(
            "Imported dictionary. No sample yet.")
        self._set_results_visible(True)
        self._refresh_buttons()
        self._refresh_checklist()
        self.statusBar().showMessage(
            "Dictionary imported: %d codes from %s"
            % (len(dictionary), os.path.basename(path)))
        self.log.action("dictionary imported from %s" % path)

    def _debug_report(self):
        # T28: a failed report shows a notice instead of crashing
        # out of the button.
        try:
            path = self.log.generate_report()
        except OSError:
            self.log.exception("debug report failed")
            self._show_notice(
                "Could not write the debug report. Check the logs "
                "folder is writable and try again.")
            self.statusBar().showMessage(
                "Could not write the debug report")
            return
        self._show_saved("Debug report saved:",
                         "Last debug report", path)

    def _show_saved(self, message, history_label, path):
        """T12 (v0.4): the status bar names the file, not the
        whole path — a long path overflows the bar and reads as
        gibberish (F18). The full path is the status bar's
        tooltip, labeled as history, so it is never wrong when
        shown later."""
        self.statusBar().showMessage(
            "%s %s" % (message, os.path.basename(path)))
        self.statusBar().setToolTip(
            "%s: %s" % (history_label, path))


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
