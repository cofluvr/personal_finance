"""Reads CSV bytes into raw records without interpreting them."""

import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import Layout

METADATA_KEYS = {"coverage-kind", "coverage-start", "coverage-end", "coverage-basis", "generated-on"}


@dataclass(frozen=True)
class RawRecord:
    index: int
    cells: tuple[str, ...]
    raw_json: str
    fingerprint: str
    occurrence: int


def read_document(content: bytes, layout: Layout) -> tuple[dict[str, str], list[RawRecord]]:
    """Return a document's metadata and every data row exactly as read."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFailure("invalid_encoding") from None

    metadata, body = _split_preamble(text) if layout.has_metadata_preamble else ({}, text)

    try:
        rows = list(csv.reader(io.StringIO(body, newline=""), strict=True))
    except csv.Error:
        raise ImportFailure("malformed_csv") from None

    if not rows or tuple(rows[0]) != layout.columns:
        raise ImportFailure("header_mismatch")

    return metadata, raw_records(cells for cells in rows[1:] if cells)


def raw_records(rows: Iterable[Sequence[str]]) -> list[RawRecord]:
    """Each row as stored: numbered from 1, with its cells' JSON, their fingerprint, and its
    occurrence among identical rows. Shared by CSV and PDF documents."""
    records = []
    seen: Counter[str] = Counter()
    for cells in rows:
        raw_json = json.dumps(list(cells), ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        seen[fingerprint] += 1
        records.append(
            RawRecord(len(records) + 1, tuple(cells), raw_json, fingerprint, seen[fingerprint])
        )
    return records


def _split_preamble(text: str) -> tuple[dict[str, str], str]:
    lines = text.split("\n")
    metadata: dict[str, str] = {}
    count = 0
    for line in lines:
        if not line.startswith("#"):
            break
        key, separator, value = line[1:].partition(":")
        key = key.strip()
        if not separator or key not in METADATA_KEYS or key in metadata:
            raise ImportFailure("invalid_coverage_metadata")
        metadata[key] = value.strip()
        count += 1
    return metadata, "\n".join(lines[count:])
