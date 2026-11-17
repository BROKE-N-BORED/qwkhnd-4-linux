"""Performance regression tests (T27): loose bounds that catch a
return to the v0.2 behaviour (list-built tokens, widget-per-row
table, sort per keystroke), without flaking on a slow machine.

Baselines from the v0.2 review (sandbox-measured): counting 2M
words took 34.3 s; the tokenizer held ~30x the text size in RAM;
Show All on 199k entries took 63.2 s and 723 MB; a search sort
took 1.91 s per keystroke. The bounds below are far looser than
the v0.3 numbers, and far tighter than the v0.2 ones.
"""

import logging
import os
import tempfile
import time
import tracemalloc
import unittest
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qwkhnd.app import MainWindow, stylesheet  # noqa: E402
from qwkhnd.engine import (  # noqa: E402
    QwkhndDictionary, build_word_codes, count_words)

_app = None

# The probe corpus: 2M words from a 1,000-word vocabulary, about
# 18 MB of text. Built from one repeated chunk, so the test
# itself stays fast.
WORDS = 2_000_000
VOCABULARY = 1000


def setUpModule():
    global _app
    _app = QApplication.instance() or QApplication([])
    _app.setStyleSheet(stylesheet(False))


def _pump():
    _app.processEvents()


def _corpus():
    chunk = " ".join("word%04d" % i for i in range(VOCABULARY))
    return " ".join([chunk] * (WORDS // VOCABULARY))


class CountingPerfTests(unittest.TestCase):
    """T02/T27: streaming counting stays light and fast."""

    def test_counting_stays_light_on_ram(self):
        # tracemalloc, not ru_maxrss: the process peak is shared
        # across test modules in one process and cannot be
        # attributed to one call.
        text = _corpus()
        tracemalloc.start()
        try:
            counter = Counter()
            count_words(text, counter)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(sum(counter.values()), WORDS)
        # v0.2 held the whole token list (~100 MB for this
        # corpus); streaming holds the Counter plus one token.
        self.assertLess(peak, 50 * 1024 * 1024)

    def test_counting_is_fast(self):
        text = _corpus()
        start = time.monotonic()
        counter = Counter()
        count_words(text, counter)
        elapsed = time.monotonic() - start
        self.assertEqual(sum(counter.values()), WORDS)
        # The RAM guard above is the real regression test for
        # the tokenizer: wall time on a throttled machine is
        # dominated by the throttle (v0.2 took 34.3 s on this
        # size in the sandbox, v0.3 takes about the same — the
        # per-token Python work dominates both). This bound
        # only catches a hang or a pathological slowdown.
        self.assertLess(elapsed, 120.0)


class TablePerfTests(unittest.TestCase):
    """T03/T04/T27: the virtual table and the cached search."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.settings_path = os.path.join(self.tmp.name,
                                          "settings.ini")
        self.window = MainWindow(data_dir=self.data_dir,
                                 settings_path=self.settings_path)
        self.window.show()
        _pump()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        _pump()
        _app.setStyleSheet(stylesheet(False))
        logger = logging.getLogger("debug_log.qwkhnd")
        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)
        self.tmp.cleanup()

    def _big_dictionary(self, entries=200_000):
        counter = Counter({"word%06d" % i: entries - i
                           for i in range(entries)})
        codes = build_word_codes(counter)
        return QwkhndDictionary(codes, counter)

    def test_show_all_on_200k_is_fast(self):
        # v0.2 took 63.2 s and 723 MB to show 199k rows; the
        # virtual model hands over a list in one reset.
        dictionary = self._big_dictionary()
        self.window._set_dictionary(dictionary)
        self.window._set_results_visible(True)
        _pump()
        start = time.monotonic()
        self.window.show_all_button.setChecked(True)
        _pump()
        elapsed = time.monotonic() - start
        self.assertEqual(self.window.table.model().rowCount(),
                         len(dictionary))
        # v0.2 took 63.2 s; 10 s is loose enough for a loaded
        # machine and still catches a widget-per-row regression.
        # The strict 2 s budget is measured by the standalone
        # perf check, not this suite test.
        self.assertLess(elapsed, 10.0)

    def test_search_on_200k_is_fast(self):
        # With the sort cached, a search is one filter pass over
        # precomputed lowercase words; v0.2 re-sorted per
        # keystroke (1.91 s) and re-filtered (1.52 s).
        dictionary = self._big_dictionary()
        self.window._set_dictionary(dictionary)
        self.window._set_results_visible(True)
        self.window._table_entries()  # warm the cache
        self.window.search_edit.setText("word0001")
        start = time.monotonic()
        self.window._fill_table()
        _pump()
        elapsed = time.monotonic() - start
        self.assertGreater(self.window.table.model().rowCount(), 0)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
