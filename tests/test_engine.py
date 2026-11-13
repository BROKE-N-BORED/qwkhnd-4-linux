"""Engine tests: codes, encode/decode, round-trips, export, build.

The round-trip property (decode(encode(text)) == text) is the one
that must never break, so it gets the biggest battery: punctuation,
tildes, case, unicode, numbers, newlines, words the dictionary has
never seen, and long repetitive text.
"""

import json
import os
import tempfile
import unittest
from collections import Counter

from qwkhnd.engine import (
    CODE_ALPHABET, MIN_WORD_LEN, QwkhndDictionary,
    build_from_folder, build_word_codes, count_words,
    generate_codes, split_tokens,
)

SAMPLE_TEXTS = [
    "",
    " ",
    "!!! ??? ...",
    "the quick brown fox jumps over the lazy dog",
    "The Quick Brown Fox Jumps Over The Lazy Dog",
    "THE QUICK BROWN FOX",
    "don't can't won't it's o'clock",
    "well-known state-of-the-art twenty-one",
    "hello, world! How are you? I'm fine — thanks.",
    "line one\nline two\n\nline four\ttabbed",
    "a b c d e f g",
    "to of in on at by we he it is am an as be do go if no so up",
    "100 200 300 2026 3.14 1,000,000",
    "email me at test@example.com or visit https://example.com/x",
    "tilde ~ here, double ~~ there, and ~a ~zz at the end ~",
    "~",
    "~~",
    "~~~a~~~",
    "café résumé naïve über señor mañana",
    "word " * 50,
    "The the THE tHe thE the.",
    "under_score dash-ed hyphen--double",
    "'quoted' \"double-quoted\" (parentheses) [brackets] {braces}",
    "emoji \U0001F600 and symbols \u00a9\u00ae\u2122",
    "mixed123 abc123 123abc a1b2c3",
]


def _dictionary_for(texts):
    counter = Counter()
    for text in texts:
        count_words(text, counter)
    return QwkhndDictionary(build_word_codes(counter), counter)


class TokeniserTests(unittest.TestCase):
    def test_tokens_rejoin_exactly(self):
        for text in SAMPLE_TEXTS:
            joined = "".join(tok for _, tok in split_tokens(text))
            self.assertEqual(joined, text, repr(text))

    def test_apostrophe_inside_word(self):
        words = [tok for is_word, tok in split_tokens("don't stop")
                 if is_word]
        self.assertEqual(words, ["don't", "stop"])

    def test_quotes_are_separators(self):
        words = [tok for is_word, tok in split_tokens("'tis the season")
                 if is_word]
        self.assertEqual(words, ["tis", "the", "season"])

    def test_hyphen_splits(self):
        words = [tok for is_word, tok in
                 split_tokens("well-known") if is_word]
        self.assertEqual(words, ["well", "known"])


class CodeAssignmentTests(unittest.TestCase):
    def test_code_sequence(self):
        codes = list(generate_codes(40))
        self.assertEqual(codes[:36], list(CODE_ALPHABET))
        self.assertEqual(codes[36], "aa")
        self.assertEqual(codes[37], "ab")
        self.assertEqual(codes[39], "ad")

    def test_most_frequent_gets_shortest(self):
        counter = Counter({"apple": 50, "banana": 30, "cherry": 10,
                           "date": 5})
        codes = build_word_codes(counter)
        self.assertEqual(codes["apple"], "a")
        self.assertEqual(codes["banana"], "b")
        self.assertEqual(codes["cherry"], "c")
        self.assertEqual(codes["date"], "d")

    def test_ties_broken_alphabetically(self):
        counter = Counter({"zebra": 5, "apple": 5, "mango": 5})
        codes = build_word_codes(counter)
        self.assertEqual(codes["apple"], "a")
        self.assertEqual(codes["mango"], "b")
        self.assertEqual(codes["zebra"], "c")

    def test_short_words_get_no_code(self):
        counter = Counter({"a": 100, "to": 90, "the": 80})
        codes = build_word_codes(counter)
        self.assertNotIn("a", codes)
        self.assertNotIn("to", codes)
        self.assertEqual(codes["the"], "a")

    def test_min_word_length_constant(self):
        self.assertEqual(MIN_WORD_LEN, 3)

    def test_deterministic(self):
        counter = Counter({"one": 9, "two": 8, "three": 7,
                           "four": 6, "five": 5})
        self.assertEqual(build_word_codes(counter),
                         build_word_codes(Counter(counter)))

    def test_long_codes_after_exhaustion(self):
        counter = Counter({"word%04d" % i: 100 - i
                           for i in range(50)})
        codes = build_word_codes(counter)
        self.assertEqual(len(codes), 50)
        self.assertEqual(len(set(codes.values())), 50)
        self.assertTrue(all(len(c) <= 2 for c in codes.values()))


class EncodeDecodeTests(unittest.TestCase):
    def setUp(self):
        corpus = [
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox is quick and the dog is lazy",
            "hello world, hello shorthand, hello everyone",
        ]
        self.dictionary = _dictionary_for(corpus)

    def test_round_trip_battery(self):
        for text in SAMPLE_TEXTS:
            with self.subTest(text=text[:40]):
                encoded = self.dictionary.encode(text)
                self.assertEqual(self.dictionary.decode(encoded), text)

    def test_round_trip_on_corpus_itself(self):
        corpus = ("the quick brown fox jumps over the lazy dog. "
                  "Hello world, hello shorthand!")
        self.assertEqual(
            self.dictionary.decode(self.dictionary.encode(corpus)),
            corpus)

    def test_encode_never_lengthens(self):
        for text in SAMPLE_TEXTS:
            if "~" in text:
                continue  # "~" escaping is the one honest exception
            self.assertLessEqual(len(self.dictionary.encode(text)),
                                 len(text), repr(text))

    def test_encode_shortens_frequent_words(self):
        encoded = self.dictionary.encode("the quick brown fox")
        self.assertLess(len(encoded), len("the quick brown fox"))
        self.assertIn("~", encoded)

    def test_encode_leaves_unknown_words(self):
        text = "flibberty gibbet wozzeck"
        self.assertEqual(self.dictionary.encode(text), text)

    def test_encode_leaves_short_words(self):
        text = "a to of in on"
        self.assertEqual(self.dictionary.encode(text), text)

    def test_decode_plain_text_unchanged(self):
        text = "nothing coded here at all"
        self.assertEqual(self.dictionary.decode(text), text)

    def test_decode_unknown_code_left_literal(self):
        text = "~zzz ~qqq ~1"
        self.assertEqual(self.dictionary.decode(text), text)

    def test_decode_trailing_tilde(self):
        self.assertEqual(self.dictionary.decode("ends with ~"),
                         "ends with ~")

    def test_empty_dictionary_is_identity(self):
        empty = QwkhndDictionary()
        for text in SAMPLE_TEXTS:
            # Round-trip still holds with no codes at all.
            self.assertEqual(empty.decode(empty.encode(text)), text)
            # Without a "~" in the input, encode changes nothing.
            if "~" not in text:
                self.assertEqual(empty.encode(text), text)

    def test_case_sensitive_entries(self):
        counter = Counter({"The": 10, "the": 20})
        dictionary = QwkhndDictionary(build_word_codes(counter),
                                         counter)
        self.assertNotEqual(dictionary.word_to_code["The"],
                            dictionary.word_to_code["the"])
        self.assertEqual(
            dictionary.decode(dictionary.encode("The the THE")),
            "The the THE")

    def test_savings_math(self):
        before, after, saved, pct = self.dictionary.savings(
            "the quick brown fox jumps over the lazy dog")
        self.assertEqual(before, 43)
        self.assertLess(after, before)
        self.assertEqual(saved, before - after)
        self.assertAlmostEqual(pct, 100.0 * saved / before)

    def test_savings_empty_text(self):
        self.assertEqual(self.dictionary.savings(""), (0, 0, 0, 0.0))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dictionary = _dictionary_for([
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox is quick",
            "the the the",
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_round_trip(self):
        path = os.path.join(self.tmp.name, "dict.json")
        self.dictionary.export_json(path)
        with open(path, encoding="utf-8") as fh:
            loaded = QwkhndDictionary.from_json_dict(json.load(fh))
        self.assertEqual(loaded.word_to_code,
                         self.dictionary.word_to_code)
        text = "the quick brown fox jumps"
        self.assertEqual(loaded.encode(text),
                         self.dictionary.encode(text))

    def test_json_has_metadata(self):
        path = os.path.join(self.tmp.name, "dict.json")
        self.dictionary.export_json(path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["app"], "Qwkhnd")
        self.assertEqual(data["version"], "0.1")
        self.assertEqual(data["marker"], "~")
        self.assertTrue(data["entries"])
        top = data["entries"][0]
        self.assertEqual(top["word"], "the")
        self.assertEqual(top["code"], "a")

    def test_text_export_is_readable(self):
        path = os.path.join(self.tmp.name, "dict.txt")
        self.dictionary.export_text(path)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("Qwkhnd dictionary", text)
        self.assertIn("the -> ~a", text)
        self.assertIn("quick -> ~", text)


class BuildFromFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "source")
        os.makedirs(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, content):
        path = os.path.join(self.folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode,
                  encoding=None if mode == "wb" else "utf-8") as fh:
            fh.write(content)

    def test_build_counts_and_codes(self):
        self._write("a.txt", "the quick brown fox " * 10)
        self._write("b.md", "the lazy dog " * 5)
        dictionary, report = build_from_folder(self.folder)
        self.assertEqual(report.files_read, 2)
        self.assertEqual(report.files_skipped, [])
        self.assertFalse(report.cancelled)
        self.assertEqual(report.total_words, 40 + 15)
        self.assertEqual(dictionary.word_to_code["the"], "a")
        self.assertGreater(report.codes_assigned, 0)
        self.assertGreater(report.sample_saved, 0)
        # The sample separates files, so words never glue together
        # across a file boundary ("dog." + "the" must not read "dog.the").
        self.assertIn("\n", report.sample_text)
        self.assertNotIn("dog.the", report.sample_text)

    def test_empty_folder(self):
        dictionary, report = build_from_folder(self.folder)
        self.assertEqual(len(dictionary), 0)
        self.assertEqual(report.files_read, 0)
        self.assertEqual(report.total_words, 0)
        self.assertEqual(report.sample_text, "")

    def test_skipped_files_listed(self):
        self._write("good.txt", "the quick brown fox")
        self._write("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        self._write("song.mp3", b"ID3" + b"\x00" * 100)
        _, report = build_from_folder(self.folder)
        self.assertEqual(report.files_read, 1)
        names = [name for name, _ in report.files_skipped]
        self.assertIn("photo.png", names)
        self.assertIn("song.mp3", names)
        reasons = dict(report.files_skipped)
        self.assertIn("OCR", reasons["photo.png"])

    def test_progress_called_per_file(self):
        self._write("a.txt", "hello world")
        self._write("b.txt", "hello again")
        seen = []

        def progress(done, total, name):
            seen.append((done, total, name))

        build_from_folder(self.folder, progress=progress)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][1], 2)
        self.assertEqual(seen[1][0], 2)

    def test_sample_round_trips(self):
        self._write("a.txt",
                    "the quick brown fox jumps over the lazy dog. " * 20)
        dictionary, report = build_from_folder(self.folder)
        self.assertEqual(dictionary.decode(report.sample_encoded),
                         report.sample_text)
        self.assertLess(report.sample_after, report.sample_before)

    def test_cancel_stops_the_build(self):
        # U26: cancelled() stops the build at the next file boundary.
        for i in range(10):
            self._write("f%02d.txt" % i, "the quick brown fox")
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 3

        dictionary, report = build_from_folder(
            self.folder, cancelled=cancelled)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.files_read, 3)
        self.assertGreater(len(dictionary), 0)

    def test_cancel_before_start(self):
        self._write("a.txt", "the quick brown fox")
        dictionary, report = build_from_folder(
            self.folder, cancelled=lambda: True)
        self.assertTrue(report.cancelled)
        self.assertEqual(report.files_read, 0)
        self.assertEqual(len(dictionary), 0)


if __name__ == "__main__":
    unittest.main()
