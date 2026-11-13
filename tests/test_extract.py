"""Extraction tests: every file type, and every skip with a reason."""

import os
import tempfile
import unittest

from fixtures import write_minimal_docx, write_minimal_pdf
from qwkhnd.extract import (
    BINARY_REASON, MEDIA_REASON, OLD_OFFICE_REASON,
    extract_file, scan_folder,
)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "source")
        os.makedirs(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _write(self, name, content):
        path = self._path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode,
                  encoding=None if mode == "wb" else "utf-8") as fh:
            fh.write(content)
        return path

    def test_txt(self):
        path = self._write("notes.txt", "the quick brown fox")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("quick brown fox", text)

    def test_md(self):
        path = self._write("notes.md", "# Title\n\nSome body text.")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("Some body text", text)

    def test_unknown_extension_text(self):
        path = self._write("data.xyz", "plain words in a strange file")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("plain words", text)

    def test_code_file_is_text(self):
        path = self._write("script.py", "def hello():\n    return 42\n")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("hello", text)

    def test_bad_utf8_tolerated(self):
        path = self._write("messy.txt", b"good words \xff\xfe bad bytes")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("good words", text)

    def test_utf16_with_bom(self):
        path = self._write("utf16.txt",
                           "hello utf sixteen".encode("utf-16"))
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("hello utf sixteen", text)

    def test_empty_file_reads(self):
        path = self._write("empty.txt", "")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertEqual(text, "")

    def test_pdf(self):
        path = self._path("doc.pdf")
        write_minimal_pdf(path, ["the quick brown fox",
                                 "jumps over the lazy dog"])
        ok, text = extract_file(path)
        self.assertTrue(ok, text)
        self.assertIn("quick brown fox", text)
        self.assertIn("lazy dog", text)

    def test_corrupt_pdf_skipped_with_reason(self):
        path = self._write("broken.pdf", b"this is not a pdf at all")
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("PDF", reason)

    def test_docx(self):
        path = self._path("doc.docx")
        write_minimal_docx(path, ["First paragraph here.",
                                  "Second paragraph here."])
        ok, text = extract_file(path)
        self.assertTrue(ok, text)
        self.assertIn("First paragraph", text)
        self.assertIn("Second paragraph", text)

    def test_corrupt_docx_skipped_with_reason(self):
        path = self._write("broken.docx", b"not a zip at all")
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("docx", reason)

    def test_png_skipped_as_media(self):
        path = self._write("pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("OCR", reason)

    def test_mp4_skipped_as_media(self):
        path = self._write("clip.mp4", b"\x00\x00\x00\x18ftypmp42")
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("OCR", reason)

    def test_mp3_skipped_as_media(self):
        path = self._write("song.mp3", b"ID3" + b"\x00" * 64)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("speech", reason)

    def test_old_doc_skipped(self):
        path = self._write("old.doc", b"\xd0\xcf\x11\xe0" + b"\x00" * 64)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("docx", reason)

    def test_zip_skipped(self):
        path = self._write("pack.zip", b"PK\x03\x04" + b"\x00" * 64)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("not a readable text format", reason)

    def test_binary_blob_skipped(self):
        path = self._write("blob.dat", bytes(range(256)) * 4)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("binary", reason)

    def test_missing_file_skipped(self):
        ok, reason = extract_file(self._path("nope.txt"))
        self.assertFalse(ok)
        self.assertIn("could not read", reason)

    def test_skip_reasons_have_no_em_dash(self):
        # U33: every skip reason is shown in the window.
        reasons = [MEDIA_REASON, BINARY_REASON, OLD_OFFICE_REASON]
        _, reason = extract_file(
            self._write("broken.pdf", b"this is not a pdf at all"))
        reasons.append(reason)
        _, reason = extract_file(
            self._write("old.doc", b"\xd0\xcf\x11\xe0" + b"\x00" * 64))
        reasons.append(reason)
        for reason in reasons:
            self.assertNotIn("\u2014", reason, reason)


class ScanFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "source")
        os.makedirs(self.folder)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, content="words here"):
        path = os.path.join(self.folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_recurses_into_subfolders(self):
        self._write("top.txt")
        self._write("sub/nested.txt")
        self._write("sub/deep/deeper.txt")
        paths, skipped = scan_folder(self.folder)
        names = sorted(os.path.basename(p) for p in paths)
        self.assertEqual(names, ["deeper.txt", "nested.txt", "top.txt"])
        self.assertEqual(skipped, [])

    def test_hidden_file_skipped_and_listed(self):
        self._write("visible.txt")
        self._write(".hidden.txt")
        paths, skipped = scan_folder(self.folder)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(skipped), 1)
        self.assertIn(".hidden.txt", skipped[0][0])
        self.assertIn("hidden", skipped[0][1])

    def test_hidden_folder_skipped_and_listed(self):
        self._write("visible.txt")
        self._write(".secret/inside.txt")
        paths, skipped = scan_folder(self.folder)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(skipped), 1)
        self.assertIn(".secret", skipped[0][0])
        self.assertIn("hidden folder", skipped[0][1])

    def test_empty_folder(self):
        paths, skipped = scan_folder(self.folder)
        self.assertEqual(paths, [])
        self.assertEqual(skipped, [])

    def test_deterministic_order(self):
        for name in ("z.txt", "a.txt", "m.txt"):
            self._write(name)
        first, _ = scan_folder(self.folder)
        second, _ = scan_folder(self.folder)
        self.assertEqual(first, second)
        self.assertEqual([os.path.basename(p) for p in first],
                         ["a.txt", "m.txt", "z.txt"])


if __name__ == "__main__":
    unittest.main()
