"""Text extraction from the Source Material folder.

What it reads
---------------
- .txt, .md and other text files: read as UTF-8 (bad bytes are
  tolerated, not fatal).
- .pdf: text layer via pypdf (pure Python). A scanned PDF has no
  text layer — that is reported, not faked: OCR is future work.
- .docx: the Word XML inside the zip, standard library only.

Everything else is attempted as plain text when it is not a known
binary type, and the binary check decides. Nothing is ever skipped
silently: every skipped file comes back with a reason, and the
window lists them all.
"""

import os
import zipfile
import xml.etree.ElementTree as ET

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

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Bytes that may appear in plain text (printables + common controls).
_TEXT_BYTES = frozenset(list(range(32, 256)) + [7, 8, 9, 10, 12, 13, 27])


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
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            full = os.path.join(root, name)
            if name.startswith("."):
                skipped.append((display_name(folder, full),
                                "hidden file"))
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


def extract_text(path):
    """Read a file as text. Returns (True, text) or (False, reason)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
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
        return False, "looks like a binary file, not readable text"
    return True, data.decode("utf-8", errors="replace")


def extract_pdf(path):
    """Read a PDF's text layer via pypdf."""
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
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue  # one bad page must not lose the rest
    text = "\n".join(pages)
    if not text.strip():
        return False, ("no extractable text in this PDF. It may be "
                       "scanned images, and OCR is not in this version")
    return True, text


def extract_docx(path):
    """Read a .docx with the standard library (zip + XML)."""
    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                return False, ("not a Word document "
                               "(no word/document.xml inside)")
            xml_bytes = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return False, "not a valid .docx file (damaged or not a Word file)"
    except OSError as exc:
        return False, "could not read the file (%s)" % _short_error(exc)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return False, "the Word file's text is damaged (bad XML)"
    paragraphs = []
    for para in root.iter("{%s}p" % _WORD_NS):
        runs = [node.text for node in para.iter("{%s}t" % _WORD_NS)
                if node.text]
        paragraphs.append("".join(runs))
    return True, "\n".join(paragraphs)


def extract_file(path):
    """Read one file. Returns (True, text) or (False, reason)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".docx":
        return extract_docx(path)
    if ext in MEDIA_EXTENSIONS:
        return False, MEDIA_REASON
    if ext in OLD_OFFICE_EXTENSIONS:
        return False, OLD_OFFICE_REASON
    if ext in BINARY_EXTENSIONS:
        return False, BINARY_REASON
    return extract_text(path)
