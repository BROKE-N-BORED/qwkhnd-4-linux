"""Test fixtures: a minimal PDF and a minimal .docx, built by hand.

No third-party writer is needed: the PDF is raw PDF syntax with
byte offsets computed here (pypdf reads it fine), and the .docx
is a zip holding the Word XML the reader expects.
"""

import os
import zipfile
from xml.sax.saxutils import escape


def write_minimal_pdf(path, lines):
    """A one-page PDF whose text layer holds the given lines."""
    def esc(text):
        return (text.replace("\\", "\\\\")
                    .replace("(", "\\(").replace(")", "\\)"))

    parts = []
    for i, line in enumerate(lines):
        if i:
            parts.append("0 -30 Td ")
        parts.append("(%s) Tj " % esc(line))
    stream = ("BT /F1 24 Tf 72 720 Td " + "".join(parts) + "ET")
    stream_bytes = stream.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        (b"<< /Length %d >>\nstream\n" % len(stream_bytes)
         + stream_bytes + b"\nendstream"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % number).encode("latin-1")
        out += body + b"\nendobj\n"
    xref_pos = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += ("%010d 00000 n \n" % offset).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\n"
            "startxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_pos)).encode("latin-1")
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def write_minimal_pdf_pages(path, pages):
    """A PDF with one page per list of lines in `pages`."""
    def esc(text):
        return (text.replace("\\", "\\\\")
                    .replace("(", "\\(").replace(")", "\\)"))

    objects = []
    kids = []
    for page_index, lines in enumerate(pages):
        content_number = 3 + page_index * 2
        page_number = 4 + page_index * 2
        kids.append("%d 0 R" % page_number)
        parts = []
        for i, line in enumerate(lines):
            if i:
                parts.append("0 -30 Td ")
            parts.append("(%s) Tj " % esc(line))
        stream = ("BT /F1 24 Tf 72 720 Td " + "".join(parts) + "ET")
        stream_bytes = stream.encode("latin-1")
        objects.append(
            (b"<< /Length %d >>\nstream\n" % len(stream_bytes)
             + stream_bytes + b"\nendstream"))
        objects.append(
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
             "/Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> "
             ">> >>" % (content_number,
                        3 + len(pages) * 2)).encode("latin-1"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont "
                   b"/Helvetica >>")
    objects.insert(0, b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.insert(1, ("<< /Type /Pages /Kids [%s] /Count %d >>"
                       % (" ".join(kids), len(pages))).encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % number).encode("latin-1")
        out += body + b"\nendobj\n"
    xref_pos = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += ("%010d 00000 n \n" % offset).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\n"
            "startxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_pos)).encode("latin-1")
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def write_minimal_epub(path, chapters):
    """An EPUB with one chapter file per list of paragraphs."""
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>'
        '</rootfiles></container>')
    items = []
    refs = []
    for i in range(len(chapters)):
        items.append('<item id="ch%d" href="ch%d.xhtml" '
                     'media-type="application/xhtml+xml"/>' % (i, i))
        refs.append('<itemref idref="ch%d"/>' % i)
    opf = (
        '<?xml version="1.0"?><package version="3.0" '
        'xmlns="http://www.idpf.org/2007/opf" '
        'unique-identifier="id"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="id">test</dc:identifier>'
        '<dc:title>Test</dc:title><dc:language>en</dc:language>'
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z'
        '</meta></metadata><manifest>' + "".join(items) +
        '</manifest><spine>' + "".join(refs) +
        '</spine></package>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        for i, paragraphs in enumerate(chapters):
            body = "".join("<p>%s</p>" % p for p in paragraphs)
            xhtml = ('<?xml version="1.0"?><html xmlns='
                     '"http://www.w3.org/1999/xhtml"><body>' + body +
                     '</body></html>')
            zf.writestr("OEBPS/ch%d.xhtml" % i, xhtml)


def write_minimal_docx(path, paragraphs, parts=None):
    """A .docx holding one paragraph per given string. `parts`
    adds extra Word XML parts: {zip name: [paragraphs]}, for
    headers, footers, footnotes and endnotes (T21)."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types">'
        '<Default Extension="rels" ContentType="application/vnd.'
        'openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.wordprocessingml'
        '.document.main+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>')
    body = "".join(
        '<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % escape(p)
        for p in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>%s</w:body></w:document>'
        % body)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
        for name, paras in (parts or {}).items():
            part_body = "".join(
                '<w:p><w:r><w:t>%s</w:t></w:r></w:p>' % escape(p)
                for p in paras)
            zf.writestr(
                name,
                '<?xml version="1.0" encoding="UTF-8" '
                'standalone="yes"?>\n'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body>%s</w:body>'
                '</w:document>' % part_body)


def write_source_folder(folder, files):
    """Write {relative path: text or bytes} into a folder tree."""
    for rel, content in files.items():
        full = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full, mode, encoding=None if mode == "wb" else "utf-8") as fh:
            fh.write(content)
