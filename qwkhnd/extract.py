"""Text extraction from the Source Material folder.

What it reads
---------------
- .txt, .md and other text files: read as UTF-8 (bad bytes are
  tolerated, not fatal).
- .pdf: text layer via pypdf (pure Python). A scanned PDF has no
  text layer — that is reported, not faked: OCR is future work.
- .docx: the Word XML inside the zip, standard library only.
- .epub: the chapters in spine order, markup stripped.
- .html/.htm: markup stripped (script and style dropped).
- .md: link URLs dropped, link text kept; bare URLs dropped.

Everything else is attempted as plain text when it is not a known
binary type, and the binary check decides. Nothing is ever skipped
silently: every skipped file comes back with a reason, and the
window lists them all.
"""

import os
import re
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from . import APP_ID

# Images, audio and video need OCR or speech recognition to turn
# into text. That is future work. This version says so instead of faking it.
MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif",
    ".tiff", ".ico", ".heic", ".mp3", ".wav", ".flac", ".ogg",
    ".m4a", ".aac", ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".wmv", ".flv",
}
MEDIA_REASON = ("images, audio and video need OCR or speech "
                "recognition, which is not in this version")

# Archives, programs, databases, fonts: no readable text.
BINARY_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".bin", ".dmg", ".iso", ".img",
    ".db", ".sqlite", ".sqlite3",
    ".ttf", ".otf", ".woff", ".woff2",
    ".class", ".o", ".a", ".pyc",
}
BINARY_REASON = "not a readable text format"

OLD_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt"}
OLD_OFFICE_REASON = ("old Office format: not readable, "
                     "save it as .docx to use it")

# T21: the app's own files are never source material. If the user
# points the source folder at the data folder itself, the scan
# must not read its own dictionary (which would count every word
# in it) or its own logs.
OWN_FILES = {APP_ID + "-dictionary.json",
             APP_ID + "-dictionary.previous.json"}
OWN_FILE_REASON = "the app's own dictionary file, not source material"
OWN_LOG_REASON = "a log file, not source material"
OWN_LOGS_DIR_REASON = "the app's own log folder"

# No per-file size cap, by Joshua's decision (T08): streaming
# keeps RAM flat, so the guards are Cancel (checked per chunk
# and per page) and the symlink skip below, not a limit. Do not
# re-add a cap here without his say-so.
SYMLINK_REASON = "symbolic link, not followed"

# Text files are read in 1 MB chunks, so Cancel can stop a big
# file part-way through and progress can move inside it (T08).
_CHUNK_BYTES = 1024 * 1024

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Bytes that may appear in plain text (printables + common controls).
_TEXT_BYTES = frozenset(list(range(32, 256)) + [7, 8, 9, 10, 12, 13, 27])


class Cancelled(Exception):
    """Raised when a read is cancelled mid-file (T08). The build
    catches it, marks the report cancelled, and stops."""


class _HTMLTextParser(HTMLParser):
    """Pull the readable text out of HTML, dropping script and
    style (T12/T13). Block tags become line breaks so words from
    neighbouring blocks never run together."""

    _BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
                   "li", "tr", "blockquote", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0  # inside script/style

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS or tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            if self._skip_depth:
                self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def text(self):
        return "".join(self.parts)


def strip_html(text):
    """Remove HTML markup from text, dropping script and style
    contents (T13)."""
    parser = _HTMLTextParser()
    parser.feed(text)
    parser.close()
    return parser.text()


def strip_markdown(text):
    """Drop Markdown markup, keeping the readable words (T13):
    link URLs are dropped but link text is kept, bare URLs are
    dropped, and code is dropped. Single * and _ emphasis is
    left alone: the tokenizer treats those as separators anyway,
    and stripping them would join words like some_variable."""
    # Fenced code blocks first: they may contain backticks.
    text = re.sub(r"(?ms)^```.*?^```[ \t]*$", "", text)
    # Images: ![alt](url) -> alt (the words, not the file name).
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Links: [text](url) -> text.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Reference-style links: [text][ref] -> text.
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    # Link definitions: [ref]: http://... -> dropped.
    text = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*\S+\s*$", "", text)
    # Bare URLs -> dropped.
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    # Code spans -> dropped (they are code, not prose).
    text = re.sub(r"`[^`]*`", "", text)
    # Headings, bold, strikethrough, quotes, list markers.
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*([-*+]|\d+\.)\s+", "", text)
    return text


def display_name(folder, path):
    """A short name for the UI: the path relative to the folder."""
    try:
        return os.path.relpath(path, folder)
    except ValueError:
        return os.path.basename(path)


def scan_folder(folder):
    """List the files to read, and the ones skipped before reading.

    Walks the folder recursively (no following of folder symlinks).
    Hidden files and folders are skipped and listed, never read.
    Returns (paths, skipped) with skipped as [(name, reason)].
    """
    paths = []
    skipped = []
    for root, dirnames, filenames in os.walk(folder, topdown=True,
                                             followlinks=False):
        kept = []
        for name in sorted(dirnames):
            if name.startswith("."):
                skipped.append((display_name(
                    folder, os.path.join(root, name)), "hidden folder"))
            elif name == "logs":
                # T21: the app's own log folder is not source
                # material.
                skipped.append((display_name(
                    folder, os.path.join(root, name)),
                    OWN_LOGS_DIR_REASON))
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            full = os.path.join(root, name)
            if name.startswith("."):
                skipped.append((display_name(folder, full),
                                "hidden file"))
            elif name in OWN_FILES:
                # T21: never read the app's own dictionary.
                skipped.append((display_name(folder, full),
                                OWN_FILE_REASON))
            elif name.endswith(".log"):
                skipped.append((display_name(folder, full),
                                OWN_LOG_REASON))
            elif os.path.islink(full):
                # T08: never follow a file symlink. A link to a
                # huge file (or to /dev/zero) would otherwise be
                # read until RAM runs out.
                skipped.append((display_name(folder, full),
                                SYMLINK_REASON))
            else:
                paths.append(full)
    paths.sort()
    skipped.sort()
    return paths, skipped


def _short_error(exc):
    """One line of an exception, capped so the UI stays readable."""
    text = str(exc).replace("\n", " ").strip()
    if len(text) > 120:
        text = text[:117] + "..."
    return text or exc.__class__.__name__


def _looks_binary(data):
    """True when a byte sample is almost certainly not text."""
    if not data:
        return False
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    bad = sum(1 for byte in sample if byte not in _TEXT_BYTES)
    return bad / len(sample) > 0.30


def extract_text(path, cancelled=None, file_progress=None):
    """Read a file as text. Returns (True, text) or (False, reason).

    Reads in chunks (T08): cancelled() is checked per chunk and
    file_progress(fraction) reports the read, so a big file can
    be stopped part-way through. Raises Cancelled when cancelled.
    There is no size cap (Joshua's decision): a big file is read
    in full unless cancelled.
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
    chunks = []
    read = 0
    try:
        with open(path, "rb") as fh:
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                data = fh.read(_CHUNK_BYTES)
                if not data:
                    break
                chunks.append(data)
                read += len(data)
                if file_progress is not None and size:
                    file_progress(read / size)
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
    data = b"".join(chunks)
    if not data:
        return True, ""
    if _looks_binary(data):
        # UTF-16 text trips the binary check (null bytes between
        # letters); honour a byte-order mark when one is present.
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            try:
                return True, data.decode("utf-16")
            except UnicodeDecodeError:
                pass
        # T21: UTF-16 without a mark has the same null-byte
        # pattern; detect it from the byte layout.
        encoding = _detect_utf16(data)
        if encoding is not None:
            try:
                return True, data.decode(encoding)
            except UnicodeDecodeError:
                pass
        return False, "looks like a binary file, not readable text"
    return True, data.decode("utf-8", errors="replace")


def _detect_utf16(data):
    """Return "utf-16-le", "utf-16-be", or None (T21): UTF-16 text
    without a byte-order mark has a null in every other byte.
    ASCII text in UTF-16-LE has nulls on the odd bytes; in
    UTF-16-BE they are on the even bytes."""
    sample = data[:512]
    if len(sample) < 4:
        return None
    evens = sample[0::2]
    odds = sample[1::2]
    even_nulls = evens.count(0)
    odd_nulls = odds.count(0)
    if (odd_nulls > len(odds) * 0.7
            and even_nulls < len(evens) * 0.3):
        return "utf-16-le"
    if (even_nulls > len(evens) * 0.7
            and odd_nulls < len(odds) * 0.3):
        return "utf-16-be"
    return None


def extract_pdf(path, cancelled=None, file_progress=None):
    """Read a PDF's text layer via pypdf. cancelled() is checked
    per page and file_progress(fraction) reports the read (T08).
    Raises Cancelled when cancelled."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return False, "pypdf is not installed, so PDFs cannot be read"
    try:
        reader = PdfReader(path)
    except Exception as exc:  # pypdf raises its own error types
        return False, "could not open as a PDF (%s)" % _short_error(exc)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
        if reader.is_encrypted:
            return False, "encrypted PDF: a password is needed"
    pages = []
    total = len(reader.pages)
    for number, page in enumerate(reader.pages, start=1):
        if cancelled is not None and cancelled():
            raise Cancelled()
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue  # one bad page must not lose the rest
        if file_progress is not None and total:
            file_progress(number / total)
    text = "\n".join(pages)
    if not text.strip():
        return False, ("no extractable text in this PDF. It may be "
                       "scanned images, and OCR is not in this version")
    return True, text


def _word_xml_to_text(xml_bytes):
    """The paragraph text of one Word XML part."""
    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for para in root.iter("{%s}p" % _WORD_NS):
        runs = [node.text for node in para.iter("{%s}t" % _WORD_NS)
                if node.text]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs)


def extract_docx(path):
    """Read a .docx with the standard library (zip + XML): the
    main text plus headers, footers, footnotes and endnotes
    (T21)."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "word/document.xml" not in names:
                return False, ("not a Word document "
                               "(no word/document.xml inside)")
            parts = ["word/document.xml"]
            parts += sorted(n for n in names
                            if re.match(r"word/header\d+\.xml$", n))
            parts += sorted(n for n in names
                            if re.match(r"word/footer\d+\.xml$", n))
            for extra in ("word/footnotes.xml", "word/endnotes.xml"):
                if extra in names:
                    parts.append(extra)
            texts = []
            document_bad = False
            for part in parts:
                try:
                    texts.append(_word_xml_to_text(zf.read(part)))
                except ET.ParseError:
                    # One bad part must not lose the rest; a bad
                    # main document with nothing else readable
                    # still reports as damaged below.
                    if part == "word/document.xml":
                        document_bad = True
                    continue
    except zipfile.BadZipFile:
        return False, "not a valid .docx file (damaged or not a Word file)"
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
    text = "\n".join(t for t in texts if t)
    if not text.strip():
        if document_bad:
            return False, "the Word file's text is damaged (bad XML)"
        return False, "no extractable text in this Word file"
    return True, text


def extract_epub(path):
    """Read an EPUB's chapters in spine order (T12). Returns
    (True, text) or (False, reason)."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return False, "not a valid EPUB file (damaged or not an EPUB)"
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
    with zf:
        try:
            container = zf.read("META-INF/container.xml")
        except KeyError:
            return False, ("not a valid EPUB file "
                           "(no container.xml inside)")
        try:
            root = ET.fromstring(container)
        except ET.ParseError:
            return False, ("not a valid EPUB file "
                           "(damaged container.xml)")
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = root.find(".//c:rootfile", ns)
        if rootfile is None:  # some EPUBs omit the namespace
            rootfile = root.find(".//rootfile")
        if rootfile is None or not rootfile.get("full-path"):
            return False, ("not a valid EPUB file "
                           "(no package file listed)")
        opf_path = rootfile.get("full-path")
        try:
            opf = zf.read(opf_path)
        except KeyError:
            return False, ("not a valid EPUB file "
                           "(package file missing)")
        try:
            opf_root = ET.fromstring(opf)
        except ET.ParseError:
            return False, ("not a valid EPUB file "
                           "(damaged package file)")
        opf_ns = {"o": "http://www.idpf.org/2007/opf"}
        items = opf_root.findall(".//o:item", opf_ns)
        refs = opf_root.findall(".//o:itemref", opf_ns)
        if not items:  # namespace omitted again
            items = opf_root.findall(".//item")
            refs = opf_root.findall(".//itemref")
        manifest = {}
        for item in items:
            if item.get("media-type") in ("application/xhtml+xml",
                                          "text/html"):
                manifest[item.get("id")] = item.get("href")
        base = opf_path.rsplit("/", 1)[0] + "/" \
            if "/" in opf_path else ""
        parts = []
        for ref in refs:
            href = manifest.get(ref.get("idref"))
            if href is None:
                continue
            name = base + urllib.parse.unquote(href)
            try:
                zf.getinfo(name)
            except KeyError:
                continue  # one missing chapter must not lose the rest
            parser = _HTMLTextParser()
            try:
                parser.feed(zf.read(name).decode(
                    "utf-8", errors="replace"))
                parser.close()
            except Exception:
                continue
            parts.append(parser.text())
    text = "\n".join(parts)
    if not text.strip():
        return False, "no extractable text in this EPUB"
    return True, text


def extract_file(path, cancelled=None, file_progress=None):
    """Read one file. Returns (True, text) or (False, reason).
    cancelled and file_progress are passed through to the text
    and PDF readers (T08); Cancelled is raised when cancelled."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path, cancelled=cancelled,
                           file_progress=file_progress)
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".epub":
        return extract_epub(path)
    if ext in (".html", ".htm"):
        # T13: strip the markup; the text underneath is what counts.
        ok, text = extract_text(path, cancelled=cancelled,
                                file_progress=file_progress)
        if not ok:
            return False, text
        return True, strip_html(text)
    if ext == ".md":
        # T13: drop link URLs and code, keep the readable words.
        ok, text = extract_text(path, cancelled=cancelled,
                                file_progress=file_progress)
        if not ok:
            return False, text
        return True, strip_markdown(text)
    if ext in MEDIA_EXTENSIONS:
        return False, MEDIA_REASON
    if ext in OLD_OFFICE_EXTENSIONS:
        return False, OLD_OFFICE_REASON
    if ext in BINARY_EXTENSIONS:
        return False, BINARY_REASON
    return extract_text(path, cancelled=cancelled,
                        file_progress=file_progress)
