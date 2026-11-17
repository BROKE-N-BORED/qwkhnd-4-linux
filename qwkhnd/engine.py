"""Qwkhnd engine: frequency-ranked codes, encode, decode, export.

How it works
------------
1. Count how often each word appears across the Source Material.
2. Hand out the shortest codes to the words that save the most
   text (count times characters saved), so the total saving is
   the most the dictionary can give: the top word gets the
   1-letter code "a", the next "b", and so on, then the 2-letter
   codes, then 3-letter, .... A word gets no code when the code
   it would get cannot make it shorter.
3. Encode: a word is replaced by "~" + its code — but only when the
   coded form is actually shorter than the word, so encoding never
   makes text longer. A literal "~" in the original text is written
   as "~~" so decode can tell it apart from a code.
4. Decode: "~" + code expands back to the word; "~~" becomes "~".

The round-trip is exact: decode(encode(text)) == text for any text.
That is the property the tests hammer on.

Deliberate limits, all documented in the README:
- Words are case-sensitive ("The" and "the" are different entries).
  Case-folding is future work; exactness comes first.
- Words shorter than 3 letters never get codes: "~" + a 1-letter
  code is 2 characters, so a 1- or 2-letter word can never shrink.
- Codes use lowercase letters and digits only, so the decoder can
  always tell where a code ends.
"""

import json
import os
import re
import tempfile
from collections import Counter
from itertools import product

from . import APP_NAME, VERSION
from . import extract as _extract

MARKER = "~"
CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
CODE_CHARS = frozenset(CODE_ALPHABET)
MIN_WORD_LEN = 3
SAMPLE_CHARS = 1500


def atomic_write_text(path, text):
    """Write a text file atomically (T01): temp file in the same
    folder, then os.replace, so a crash mid-write leaves the
    previous good file in place. Removes the temp file on failure.
    """
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(prefix=".qwkhnd-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- tokens


def _is_word_char(ch):
    return ch.isalpha() or ch.isdigit()


# Tokenizer (T02): a regex pass instead of a char-by-char Python
# loop. The word rule is unchanged: a run of letters/digits, with
# an apostrophe kept inside when it sits between two word
# characters. [^\W_] is the regex word class minus the underscore
# (an underscore is a separator here, not a word character), and
# [\W_] is everything else, underscore included.
_TOKEN_RE = re.compile(r"([^\W_]+(?:'[^\W_]+)*)|([\W_]+)")


def _iter_tokens_charloop(text):
    """Yield (is_word, token) pairs the slow exact way: the v0.2
    char-by-char loop, as a generator (no list built). Used only
    for the non-ASCII words the regex cannot prove exact (see
    iter_tokens)."""
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
            yield True, text[i:j]
            i = j
        else:
            j = i + 1
            while j < n and not _is_word_char(text[j]):
                j += 1
            yield False, text[i:j]
            i = j


def iter_tokens(text):
    """Yield (is_word, token) pairs, streaming (T02).

    A regex pass finds the tokens; nothing is materialized, so
    counting a large corpus stays flat in RAM instead of building
    a list of every token (v0.2 peaked near 30x the text size).
    The token rules are exactly the v0.2 ones. One known regex
    edge: the regex word class also matches numeric symbols
    (vulgar fractions like 1/2) that the char rule calls
    separators, so a matched word with any non-ASCII character
    is re-split by the exact char loop instead. ASCII text (the
    common case) never takes the slow path.
    """
    for match in _TOKEN_RE.finditer(text):
        word = match.group(1)
        if word is None:
            yield False, match.group(2)
        elif word.isascii():
            yield True, word
        else:
            yield from _iter_tokens_charloop(word)


def split_tokens(text):
    """Split text into (is_word, token) pairs, preserving everything.

    A word is a run of letters/digits, with an apostrophe kept inside
    when it sits between two word characters ("don't" is one word,
    but the quotes around 'tis' are separators). Joining every token
    back together reproduces the input exactly.
    """
    return list(iter_tokens(text))


def count_words(text, counter=None):
    """Add the word frequencies of one text to a Counter (new if None)."""
    if counter is None:
        counter = Counter()
    # Counter.update counts in C (_count_elements); a manual
    # `counter[token] += 1` loop is measurably slower (T02: this
    # is what gets the streaming tokenizer under half the old
    # counting time on the probe corpus).
    counter.update(token for is_word, token in iter_tokens(text)
                   if is_word)
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
    """Map words to codes: ranked by characters saved (T06), ties
    broken by word. Only words whose code can actually shrink them
    get one (T05).

    Two passes. Pass 1 ranks by frequency (the v0.2 rule) to give
    every word a code-length estimate. Pass 2 re-ranks by expected
    saving: count times the characters the code would save (word
    length minus code length minus the marker). The shortest codes
    then go to the words that save the most text, which is the
    goal: fewer tokens. A word is skipped when the code it would
    get cannot make it shorter, so the dictionary holds no dead
    codes; the skipped code stays available for the next word.
    The result is deterministic for a given counter.
    """
    words = [w for w in counter if len(w) >= MIN_WORD_LEN]
    if not words:
        return {}
    words.sort(key=lambda w: (-counter[w], w))
    first_pass = {}
    for word, code in zip(words, generate_codes(len(words))):
        first_pass[word] = code
    words.sort(key=lambda w: (
        -counter[w] * max(0, len(w) - len(first_pass[w]) - 1), w))
    result = {}
    codes = generate_codes(len(words))
    pending = None
    for word in words:
        if pending is None:
            try:
                pending = next(codes)
            except StopIteration:
                break
        if len(pending) + 1 < len(word):
            result[word] = pending
            pending = None
    return result


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
        for is_word, token in iter_tokens(text):
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
        """Rebuild a dictionary from a saved JSON dict.

        Validates everything (T01): the shape, the marker, the
        version, and code uniqueness. Raises ValueError with a
        plain message on anything malformed, so the window can
        start empty with a notice instead of crashing. The old
        version strings are history, not the current version:
        the current one comes from VERSION, the single source.
        """
        if not isinstance(data, dict):
            raise ValueError("saved dictionary is not an object")
        if data.get("marker", MARKER) != MARKER:
            raise ValueError(
                "saved dictionary uses a different marker")
        version = data.get("version")
        if version is not None \
                and version not in ("0.1", "0.2", VERSION):
            raise ValueError(
                "saved dictionary is version %s, which this "
                "version cannot read" % version)
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError(
                "saved dictionary entries are not a list")
        word_to_code = {}
        counts = {}
        seen_codes = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    "dictionary entry is not an object")
            word = entry.get("word")
            code = entry.get("code")
            if not isinstance(word, str) or not word:
                raise ValueError(
                    "dictionary entry has no word")
            if not isinstance(code, str) or not code:
                raise ValueError(
                    "dictionary entry has no code")
            if any(ch not in CODE_CHARS for ch in code):
                raise ValueError(
                    "dictionary code has bad characters")
            if word in word_to_code:
                raise ValueError(
                    "dictionary lists a word twice")
            if code in seen_codes:
                raise ValueError(
                    "dictionary gives one code to two words")
            count = entry.get("count", 0)
            if not isinstance(count, int) \
                    or isinstance(count, bool) or count < 0:
                raise ValueError(
                    "dictionary entry has a bad count")
            word_to_code[word] = code
            counts[word] = count
            seen_codes[code] = word
        return cls(word_to_code, counts)

    def export_json(self, path):
        text = json.dumps(self.to_json_dict(), ensure_ascii=False,
                          indent=2) + "\n"
        atomic_write_text(path, text)

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
        atomic_write_text(path, "\n".join(lines) + "\n")


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
                      cancelled=None, file_progress=None):
    """Scan a folder and build a dictionary from everything readable.

    Files are processed one at a time (light on RAM: only one file's
    text is held at once). progress(done, total, name) is called per
    file when given. cancelled() is checked before each file and
    inside big files (per chunk for text, per page for PDFs): when
    it returns True the build stops, the report is marked
    cancelled, and the dictionary built from the files read so far
    is returned. file_progress(name, fraction) reports the read
    inside one big file when given. Returns (QwkhndDictionary,
    BuildReport).
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
        try:
            ok, payload = _extract.extract_file(
                path, cancelled=cancelled,
                file_progress=(
                    (lambda frac, _name=name:
                     file_progress(_name, frac))
                    if file_progress is not None else None))
        except _extract.Cancelled:
            report.cancelled = True
            if log is not None:
                log.info("rebuild cancelled inside %s", name)
            break
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
