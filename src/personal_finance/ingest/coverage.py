"""What a document claims to contain. See decisions.md D-005.

Coverage comes only from document metadata or a user declaration. Nothing here
looks at transaction rows, so it cannot be inferred from their dates.
"""

from dataclasses import dataclass
from datetime import date

from personal_finance.ingest.errors import ImportFailure

DATE_BASES = ("transaction", "posting")


@dataclass(frozen=True)
class Coverage:
    kind: str = "unknown"
    start: str | None = None
    end: str | None = None
    date_basis: str | None = None
    evidence: str | None = None


UNKNOWN = Coverage()


def parse_iso_date(text: str) -> str:
    """Return text unchanged if it is a real YYYY-MM-DD date, or raise ValueError."""
    if date.fromisoformat(text).isoformat() != text:
        raise ValueError("not a YYYY-MM-DD date")
    return text


def declare_complete(start: str, end: str, date_basis: str) -> Coverage:
    """Build a user's explicit claim that an inclusive interval is complete."""
    return _complete(start, end, date_basis, "user_declared")


def from_metadata(metadata: dict[str, str]) -> Coverage:
    """Read the coverage a document states about itself."""
    kind = metadata.get("coverage-kind")
    start = metadata.get("coverage-start")
    end = metadata.get("coverage-end")
    basis = metadata.get("coverage-basis")

    if kind is None or kind == "unknown":
        if start or end or basis:
            raise ImportFailure("invalid_coverage_metadata")
        return UNKNOWN
    if kind == "complete":
        return _complete(start, end, basis, "document_metadata")
    if kind == "partial":
        return _partial(start, end, basis)
    raise ImportFailure("invalid_coverage_metadata")


def _complete(start, end, date_basis, evidence) -> Coverage:
    code = "invalid_coverage_metadata" if evidence == "document_metadata" else "invalid_coverage_declaration"
    if not (start and end and date_basis):
        raise ImportFailure(code)
    return Coverage("complete", *_checked(start, end, date_basis, code), evidence)


def _partial(start, end, date_basis) -> Coverage:
    code = "invalid_coverage_metadata"
    return Coverage("partial", *_checked(start, end, date_basis, code), "document_metadata")


def _checked(start, end, date_basis, code) -> tuple[str | None, str | None, str | None]:
    try:
        start = parse_iso_date(start) if start else None
        end = parse_iso_date(end) if end else None
    except ValueError:
        raise ImportFailure(code) from None
    if start and end and start > end:
        raise ImportFailure(code)
    if date_basis and date_basis not in DATE_BASES:
        raise ImportFailure(code)
    return start, end, date_basis
