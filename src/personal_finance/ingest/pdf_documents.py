"""Reads a PDF document into raw records without interpreting them (D-060 point 6).

The layout groups the PDF's lines into rows, each a tuple of text cells starting with its page,
so a row keeps the lines it was read from and traces like a CSV row.
"""

from personal_finance.ingest.csv_reader import RawRecord, raw_records
from personal_finance.ingest.layouts import Layout
from personal_finance.ingest.pdf_reader import read_pdf_lines


def read_pdf_document(content: bytes, layout: Layout) -> tuple[dict[str, str], list[RawRecord]]:
    """No metadata, and every row the layout finds, recognized or not."""
    return {}, raw_records(layout.group_lines(read_pdf_lines(content)))
