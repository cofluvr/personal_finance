"""Writes small synthetic PDFs for tests, with the standard library only.

Each page is a list of lines, set in Helvetica one under another, so a reader that keeps line
order returns them as written. A line is a string, or a tuple of (x, text) pieces placed apart on
one baseline, as a statement's columns are. Text is ASCII, written into the content stream as is.
"""

import zlib

PAGE_WIDTH, PAGE_HEIGHT = 612, 792
TOP, LEADING, LEFT = 750, 14, 50


def _escaped(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(lines: list) -> bytes:
    commands = ["BT", "/F1 10 Tf"]
    for number, line in enumerate(lines):
        pieces = [(LEFT, line)] if isinstance(line, str) else line
        for x, text in pieces:
            commands.append(f"1 0 0 1 {x} {TOP - number * LEADING} Tm ({_escaped(text)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("ascii")


def pdf_bytes(pages: list[list], *, extra_objects: list[bytes] = (),
              page_resources: bytes = b"") -> bytes:
    """A PDF of the given pages. Extra objects are numbered after the pages' objects, and the
    page resources are added to each page's /Resources dictionary."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")
    page_tree = add(b"")
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    page_numbers = []
    for lines in pages:
        stream = zlib.compress(_content(lines))
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                      + stream + b"\nendstream")
        page_numbers.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> %s >> >>"
            % (page_tree, PAGE_WIDTH, PAGE_HEIGHT, content, font, page_resources)))
    for body in extra_objects:
        add(body)
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % page_tree
    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)
    objects[page_tree - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_numbers))

    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        output += b"%010d 00000 n \n" % offset
    output += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objects) + 1, catalog, xref))
    return bytes(output)
