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


def write_minimal_docx(path, paragraphs):
    """A .docx holding one paragraph per given string."""
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


def write_source_folder(folder, files):
    """Write {relative path: text or bytes} into a folder tree."""
    for rel, content in files.items():
        full = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full, mode, encoding=None if mode == "wb" else "utf-8") as fh:
            fh.write(content)
