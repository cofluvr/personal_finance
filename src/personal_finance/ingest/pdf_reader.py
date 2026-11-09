"""Reads a PDF's text as pages of lines, through pypdf (D-060 point 1).

This is the only module that imports pypdf, so its errors are caught here and become a fixed
failure code. pypdf can run an outside program, jbig2dec, to decode a JBIG2 image. Every call here
runs with that program unset, so pypdf never runs it (D-060 point 1, as amended). pypdf logs
warnings that can quote a file's bytes, so its log is never printed (D-037).
"""

import io
import logging
from contextlib import contextmanager

import pypdf

from personal_finance.ingest.errors import ImportFailure

# Joins a layout's parser version, so another pypdf release is another interpretation (D-026).
EXTRACTOR_VERSION = f"pypdf-{pypdf.__version__}"

_pypdf_log = logging.getLogger("pypdf")
_pypdf_log.addHandler(logging.NullHandler())
_pypdf_log.propagate = False


@contextmanager
def without_outside_programs():
    """pypdf's configuration for every call here: jbig2dec unset, so no program can run."""
    with pypdf.apply_configuration(jbig2dec_binary=None):
        yield


def read_pdf_lines(content: bytes) -> list[list[str]]:
    """Each page's lines of text in order, in pypdf's layout mode, which keeps a statement's
    columns apart. Trailing spaces are dropped, and so are blank lines."""
    try:
        with without_outside_programs():
            reader = pypdf.PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ImportFailure("encrypted_pdf")
            pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
    except ImportFailure:
        raise
    except Exception:
        raise ImportFailure("unreadable_pdf") from None

    lines = [[line.rstrip() for line in text.splitlines() if line.strip()] for text in pages]
    if not any(lines):
        raise ImportFailure("no_text_layer")
    return lines
