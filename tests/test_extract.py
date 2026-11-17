"""Extraction tests: every file type, and every skip with a reason."""

import os
import tempfile
import unittest

from fixtures import (
    write_minimal_docx, write_minimal_epub, write_minimal_pdf,
    write_minimal_pdf_pages)
from qwkhnd.extract import (
    BINARY_REASON, MEDIA_REASON, OLD_OFFICE_REASON,
    Cancelled, extract_epub, extract_file, extract_pdf,
    extract_text, scan_folder, strip_html, strip_markdown,
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

    def test_no_size_cap(self):
        # T08, Joshua's decision: there is no per-file size cap.
        # A multi-megabyte file is scanned and read in full.
        big = "the quick brown fox jumps over the lazy dog. "
        path = self._write("big.txt", big * 60000)
        paths, skipped = scan_folder(self.folder)
        self.assertEqual(len(paths), 1)
        self.assertEqual(skipped, [])
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertEqual(len(text), len(big) * 60000)

    def test_symlink_skipped_in_scan(self):
        # T08: file symlinks are never followed.
        target = self._write("real.txt", "the quick brown fox")
        link = self._path("link.txt")
        os.symlink(target, link)
        paths, skipped = scan_folder(self.folder)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(names, ["real.txt"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("link.txt", skipped[0][0])
        self.assertIn("symbolic link", skipped[0][1])

    def test_extract_text_cancellable(self):
        path = self._write("big.txt", "the quick brown fox " * 100)
        with self.assertRaises(Cancelled):
            extract_text(path, cancelled=lambda: True)

    def test_extract_text_reports_progress(self):
        path = self._write("big.txt", "the quick brown fox " * 100)
        seen = []
        ok, text = extract_text(
            path, file_progress=seen.append)
        self.assertTrue(ok)
        self.assertEqual(seen[-1], 1.0)
        self.assertIn("quick brown fox", text)

    def test_extract_pdf_cancellable_per_page(self):
        path = self._path("multi.pdf")
        write_minimal_pdf_pages(
            path, [["page one words"], ["page two words"],
                   ["page three words"]])
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 1

        with self.assertRaises(Cancelled):
            extract_pdf(path, cancelled=cancelled)

    def test_extract_pdf_reports_progress(self):
        path = self._path("multi.pdf")
        write_minimal_pdf_pages(
            path, [["page one words"], ["page two words"]])
        seen = []
        ok, text = extract_pdf(path, file_progress=seen.append)
        self.assertTrue(ok)
        self.assertEqual(seen, [0.5, 1.0])
        self.assertIn("page one words", text)
        self.assertIn("page two words", text)

    def test_multi_page_pdf_reads_all_pages(self):
        # T26: every page's text, in order.
        path = self._path("multi.pdf")
        write_minimal_pdf_pages(
            path, [["page one alpha"], ["page two beta"],
                   ["page three gamma"]])
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertLess(text.index("alpha"), text.index("beta"))
        self.assertLess(text.index("beta"), text.index("gamma"))

    def test_scanned_pdf_has_no_text_layer(self):
        # T26: pages with no text are reported, not faked.
        path = self._path("scanned.pdf")
        write_minimal_pdf_pages(path, [[], []])
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("no extractable text", reason)
        self.assertIn("scanned", reason)

    def test_encrypted_pdf_needs_password(self):
        # T26: a password-locked PDF is skipped with a reason.
        from pypdf import PdfWriter
        path = self._path("locked.pdf")
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        writer.encrypt("secret")
        with open(path, "wb") as fh:
            writer.write(fh)
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("encrypted", reason)

    def test_epub_reads_chapters_in_spine_order(self):
        # T12: the spine order is the reading order, even when
        # the files sit in the zip in a different order.
        path = self._path("book.epub")
        write_minimal_epub(
            path, [["chapter one alpha"], ["chapter two beta"]])
        ok, text = extract_epub(path)
        self.assertTrue(ok)
        self.assertLess(text.index("alpha"), text.index("beta"))
        self.assertIn("chapter one", text)
        self.assertIn("chapter two", text)

    def test_epub_drops_markup_and_scripts(self):
        path = self._path("book.epub")
        write_minimal_epub(
            path, [["<b>bold</b> words",
                    "<script>var secret = 1;</script>kept words"]])
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("bold words", text)
        self.assertIn("kept words", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("<b>", text)

    def test_corrupt_epub_skipped(self):
        path = self._write("bad.epub", "this is not a zip file")
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("EPUB", reason)

    def test_epub_without_container_skipped(self):
        import zipfile
        path = self._path("empty.epub")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
        ok, reason = extract_file(path)
        self.assertFalse(ok)
        self.assertIn("EPUB", reason)

    def test_html_markup_stripped(self):
        # T13: tags go, words stay, script and style go entirely.
        path = self._write(
            "page.html",
            "<html><head><style>.x { color: red; }</style></head>"
            "<body><h1>Title words</h1>"
            "<p>Hello <b>brave</b> world</p>"
            "<script>var hidden = 1;</script></body></html>")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("Title words", text)
        self.assertIn("Hello brave world", text)
        self.assertNotIn("<", text)
        self.assertNotIn("hidden", text)
        self.assertNotIn("color", text)

    def test_html_blocks_do_not_join_words(self):
        self.assertNotIn("alphabeta",
                         strip_html("<p>alpha</p><p>beta</p>"))
        self.assertIn("alpha", strip_html("<p>alpha</p><p>beta</p>"))
        self.assertIn("beta", strip_html("<p>alpha</p><p>beta</p>"))

    def test_markdown_links_keep_text_drop_url(self):
        # T13: the link text counts, the URL does not.
        path = self._write(
            "notes.md",
            "Read [the quick brown](https://example.com/fox) fox.")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("the quick brown", text)
        self.assertNotIn("example", text)
        self.assertNotIn("https", text)

    def test_markdown_bare_url_dropped(self):
        text = strip_markdown(
            "see https://example.com/page and www.other.org/x "
            "for more")
        self.assertNotIn("example", text)
        self.assertNotIn("other", text)
        self.assertIn("see", text)
        self.assertIn("for more", text)

    def test_markdown_code_dropped(self):
        text = strip_markdown(
            "text `code_word` more\n```\nfenced_word\n```\nend")
        self.assertNotIn("code_word", text)
        self.assertNotIn("fenced_word", text)
        self.assertIn("text", text)
        self.assertIn("end", text)

    def test_markdown_headings_and_bold_kept(self):
        text = strip_markdown("# Heading words\n\n**bold** and "
                              "~~struck~~ words")
        self.assertIn("Heading words", text)
        self.assertIn("bold", text)
        self.assertIn("struck", text)
        self.assertNotIn("#", text)
        self.assertNotIn("**", text)

    def test_docx_headers_footers_and_notes(self):
        # T21: headers, footers, footnotes and endnotes count.
        path = self._path("full.docx")
        write_minimal_docx(
            path, ["Body paragraph here."],
            parts={"word/header1.xml": ["Header words here."],
                   "word/footer1.xml": ["Footer words here."],
                   "word/footnotes.xml": ["Footnote words here."],
                   "word/endnotes.xml": ["Endnote words here."]})
        ok, text = extract_file(path)
        self.assertTrue(ok)
        for words in ("Body paragraph", "Header words",
                      "Footer words", "Footnote words",
                      "Endnote words"):
            self.assertIn(words, text)
        self.assertLess(text.index("Body paragraph"),
                        text.index("Header words"))

    def test_docx_bad_header_does_not_lose_body(self):
        import zipfile
        path = self._path("badheader.docx")
        write_minimal_docx(path, ["Body paragraph here."])
        with zipfile.ZipFile(path, "a") as zf:
            zf.writestr("word/header1.xml", "<w:document><broken")
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertIn("Body paragraph", text)

    def test_utf16_without_bom_le(self):
        # T21: UTF-16 with no byte-order mark is detected from
        # the null-byte pattern.
        path = self._path("utf16le.txt")
        with open(path, "wb") as fh:
            fh.write("the quick brown fox jumps".encode("utf-16-le"))
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertEqual(text, "the quick brown fox jumps")

    def test_utf16_without_bom_be(self):
        path = self._path("utf16be.txt")
        with open(path, "wb") as fh:
            fh.write("the quick brown fox jumps".encode("utf-16-be"))
        ok, text = extract_file(path)
        self.assertTrue(ok)
        self.assertEqual(text, "the quick brown fox jumps")

    def test_own_files_excluded_from_scan(self):
        # T21: the app's own dictionary, logs and log folder are
        # skipped with a reason, never read as source material.
        self._write("qwkhnd-dictionary.json",
                    '{"marker": "~", "entries": []}')
        self._write("qwkhnd-dictionary.previous.json",
                    '{"marker": "~", "entries": []}')
        self._write("debug.log", "some log lines")
        self._write("notes.txt", "the quick brown fox")
        logs = os.path.join(self.folder, "logs")
        os.makedirs(logs)
        with open(os.path.join(logs, "app.log"), "w") as fh:
            fh.write("log lines")
        paths, skipped = scan_folder(self.folder)
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(names, ["notes.txt"])
        reasons = {name: reason for name, reason in skipped}
        self.assertIn("qwkhnd-dictionary.json", reasons)
        self.assertIn("app's own dictionary",
                      reasons["qwkhnd-dictionary.json"])
        self.assertIn("qwkhnd-dictionary.previous.json", reasons)
        self.assertIn("debug.log", reasons)
        self.assertIn("logs", reasons)
        self.assertIn("log folder", reasons["logs"])

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
