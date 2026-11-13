"""Qwkhnd engine: frequency-ranked codes, encode, decode, export.

How it works
------------
1. Count how often each word appears across the Source Material.
2. Hand out the shortest codes to the most frequent words (the most
   common word gets the 1-letter code "a", the next "b", and so on,
   then the 2-letter codes, then 3-letter, ...).
3. Encode: a word is replaced by "~" + its code — but only when the
   coded form is actually shorter than the word, so encoding never
   makes text longer. A literal "~" in the original text is written
   as "~~" so decode can tell it apart from a code.
4. Decode: "~" + code expands back to the word; "~~" becomes "~".

The round-trip is exact: decode(encode(text)) == text for any text.
That is the property the tests hammer on.

Deliberate v0.1 limits, all documented in the README:
- Words are case-sensitive ("The" and "the" are different entries).
  Case-folding is future work; exactness comes first.
- Words shorter than 3 letters never get codes: "~" + a 1-letter
  code is 2 characters, so a 1- or 2-letter word can never shrink.
- Codes use lowercase letters and digits only, so the decoder can
  always tell where a code ends.
"""

import json
from collections import Counter
from itertools import product

from . import APP_NAME, VERSION
from . import extract as _extract

MARKER = "~"
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
CODE_CHARS = frozenset(CODE_ALPHABET)
MIN_WORD_LEN = 3
SAMPLE_CHARS = 1500


# ---------------------------------------------------------------- tokens


def _is_word_char(ch):
    return ch.isalpha() or ch.isdigit()


def split_tokens(text):
    """Split text into (is_word, token) pairs, preserving everything.

    A word is a run of letters/digits, with an apostrophe kept inside
    when it sits between two word characters ("don't" is one word,
    but the quotes around 'tis' are separators). Joining every token
    back together reproduces the input exactly.
    """
    tokens = []
    i, n = 0, len(text)
    while i < n:
        if _is_word_char(text[i]):
            j = i + 1
            while j < n:
                ch = text[j]
                if _is_word_char(ch):
                    j += 1
                elif (ch == "'" and j + 1 < n
                      and _is_word_char(text[j + 1])):
                    j += 1
                else:
                    break
            tokens.append((True, text[i:j]))
            i = j
        else:
            j = i + 1
            while j < n and not _is_word_char(text[j]):
                j += 1
            tokens.append((False, text[i:j]))
            i = j
    return tokens


def count_words(text, counter=None):
    """Add the word frequencies of one text to a Counter (new if None)."""
    if counter is None:
        counter = Counter()
    for is_word, token in split_tokens(text):
        if is_word:
            counter[token] += 1
    return counter


# ---------------------------------------------------------------- codes


def generate_codes(count):
    """Yield `count` codes: shortest first, alphabetical in a length."""
    made = 0
    length = 1
    while made < count:
        for combo in product(CODE_ALPHABET, repeat=length):
            yield "".join(combo)
            made += 1
            if made >= count:
                return
        length += 1


def build_word_codes(counter):
    """Map words to codes: most frequent first, ties broken by word.

    Only words of MIN_WORD_LEN or more get codes (shorter words can
    never shrink). The result is deterministic for a given counter.
    """
    words = [w for w in counter if len(w) >= MIN_WORD_LEN]
    words.sort(key=lambda w: (-counter[w], w))
    codes = generate_codes(len(words))
    return {word: next(codes) for word in words}


# ---------------------------------------------------------------- dictionary


class QwkhndDictionary:
    """A built shorthand dictionary: words, codes, and the codec."""

    def __init__(self, word_to_code=None, counts=None):
        self.word_to_code = dict(word_to_code or {})
        self.code_to_word = {c: w for w, c in self.word_to_code.items()}
        self.counts = dict(counts or {})

    def __len__(self):
        return len(self.word_to_code)

    def __bool__(self):
        return bool(self.word_to_code)

    # -- codec ------------------------------------------------------
    def encode(self, text):
        """Full text -> shorthand. Never makes text longer (except a
        literal "~" in the input, which becomes "~~")."""
        out = []
        for is_word, token in split_tokens(text):
            if is_word:
                code = self.word_to_code.get(token)
                if code is not None and len(code) + 1 < len(token):
                    out.append(MARKER + code)
                else:
                    out.append(token)
            else:
                out.append(token.replace(MARKER, MARKER + MARKER))
        return "".join(out)

    def decode(self, text):
        """Qwkhnd -> full text. decode(encode(x)) == x, always."""
        out = []
        i, n = 0, len(text)
        while i < n:
            if text[i] != MARKER:
                out.append(text[i])
                i += 1
                continue
            if i + 1 < n and text[i + 1] == MARKER:
                out.append(MARKER)
                i += 2
                continue
            j = i + 1
            while j < n and text[j] in CODE_CHARS:
                j += 1
            run = text[i + 1:j]
            if run and run in self.code_to_word:
                out.append(self.code_to_word[run])
            else:
                # Unknown "~..." sequence: leave it exactly as-is.
                out.append(text[i:j] if j > i + 1 else MARKER)
            i = j if j > i + 1 else i + 1
        return "".join(out)

    def savings(self, text):
        """(before_chars, after_chars, saved_chars, saved_pct)."""
        before = len(text)
        after = len(self.encode(text))
        saved = before - after
        pct = (100.0 * saved / before) if before else 0.0
        return before, after, saved, pct

    # -- export -----------------------------------------------------
    def _sorted_entries(self):
        return sorted(
            self.word_to_code.items(),
            key=lambda kv: (-self.counts.get(kv[0], 0), kv[0]))

    def to_json_dict(self):
        return {
            "app": APP_NAME,
            "version": VERSION,
            "marker": MARKER,
            "entries": [
                {"word": word, "code": code,
                 "count": self.counts.get(word, 0)}
                for word, code in self._sorted_entries()
            ],
        }

    @classmethod
    def from_json_dict(cls, data):
        word_to_code = {}
        counts = {}
        for entry in data.get("entries", []):
            word_to_code[entry["word"]] = entry["code"]
            counts[entry["word"]] = entry.get("count", 0)
        return cls(word_to_code, counts)

    def export_json(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_json_dict(), fh, ensure_ascii=False,
                      indent=2)
            fh.write("\n")

    def export_text(self, path):
        lines = [
            "%s dictionary (v%s) - %d codes"
            % (APP_NAME, VERSION, len(self)),
            "Most frequent words first. A code is used as ~"
            "<code>, e.g. ~a.",
            "",
        ]
        for word, code in self._sorted_entries():
            lines.append("%s -> ~%s  (used %d times)"
                         % (word, code, self.counts.get(word, 0)))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- build


class BuildReport:
    """What a rebuild found, for the window and the logs."""

    def __init__(self):
        self.files_read = 0
        self.files_skipped = []  # [(display name, reason)]
        self.total_words = 0
        self.unique_words = 0
        self.codes_assigned = 0
        self.cancelled = False  # True when the build stopped early
        self.sample_text = ""
        self.sample_encoded = ""
        self.sample_before = 0
        self.sample_after = 0
        self.sample_saved = 0
        self.sample_saved_pct = 0.0


def build_from_folder(folder, log=None, progress=None,
                      cancelled=None):
    """Scan a folder and build a dictionary from everything readable.

    Files are processed one at a time (light on RAM: only one file's
    text is held at once). progress(done, total, name) is called per
    file when given. cancelled() is checked before each file when
    given: when it returns True the build stops at the next file
    boundary, the report is marked cancelled, and the dictionary
    built from the files read so far is returned. Returns
    (QwkhndDictionary, BuildReport).
    """
    if log is not None:
        log.info("rebuild started: %s", folder)
    paths, skipped = _extract.scan_folder(folder)
    report = BuildReport()
    report.files_skipped = list(skipped)
    counter = Counter()
    sample_parts = []
    sample_len = 0
    total = len(paths)
    for done, path in enumerate(paths, start=1):
        if cancelled is not None and cancelled():
            report.cancelled = True
            if log is not None:
                log.info("rebuild cancelled after %d files", done - 1)
            break
        name = _extract.display_name(folder, path)
        if progress is not None:
            progress(done, total, name)
        ok, payload = _extract.extract_file(path)
        if not ok:
            report.files_skipped.append((name, payload))
            if log is not None:
                log.info("skipped %s: %s", name, payload)
            continue
        report.files_read += 1
        count_words(payload, counter)
        if sample_len < SAMPLE_CHARS:
            if sample_parts:
                sample_parts.append("\n")
                sample_len += 1
            take = payload[:SAMPLE_CHARS - sample_len]
            sample_parts.append(take)
            sample_len += len(take)
    report.total_words = sum(counter.values())
    report.unique_words = len(counter)
    dictionary = QwkhndDictionary(build_word_codes(counter), counter)
    report.codes_assigned = len(dictionary)
    report.sample_text = "".join(sample_parts)
    if report.sample_text:
        (report.sample_before, report.sample_after,
         report.sample_saved, report.sample_saved_pct) = \
            dictionary.savings(report.sample_text)
        report.sample_encoded = dictionary.encode(report.sample_text)
    if log is not None:
        log.info("rebuild done: %d files read, %d skipped, "
                 "%d words, %d unique, %d codes",
                 report.files_read, len(report.files_skipped),
                 report.total_words, report.unique_words,
                 report.codes_assigned)
    return dictionary, report
