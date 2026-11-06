"""Tested document layouts. See layouts.md for what each one promises.

Both layouts here are invented for development. A layout's meaning never changes
once used: a change in meaning needs a new layout_id, so that stored documents
keep the meaning they were imported under.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from personal_finance.money import MoneyParseError, parse_cents


@dataclass(frozen=True)
class ParsedRow:
    """One row after parsing. reason_code is set when the row is unresolved."""

    reason_code: str | None = None
    transaction_date: str | None = None
    posting_date: str | None = None
    amount_cents: int | None = None
    description: str | None = None
    external_id: str | None = None
    settlement_status: str = "unknown"


@dataclass(frozen=True)
class Layout:
    layout_id: str
    parser_version: str
    columns: tuple[str, ...]
    parse_row: Callable[[Mapping[str, str]], ParsedRow]
    # Date basis a coverage claim can use, mapped to whether pending transactions
    # fall within a complete claim on that basis.
    pending_in_complete_coverage: Mapping[str, bool]
    external_ids_reliable: bool = False
    has_metadata_preamble: bool = False


def _date(text: str, date_format: str, problems: list[str]) -> str | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, date_format).date().isoformat()
    except ValueError:
        problems.append("invalid_date")
        return None


def _amount(text: str, problems: list[str]) -> int | None:
    try:
        return parse_cents(text)
    except MoneyParseError:
        problems.append("invalid_amount")
        return None


def _finish(row: ParsedRow, problems: list[str]) -> ParsedRow:
    if row.amount_cents is None and not problems:
        problems.append("missing_amount")
    if row.transaction_date is None and row.posting_date is None and "invalid_date" not in problems:
        problems.append("missing_date")
    if not problems:
        return row
    return ParsedRow(
        problems[0],
        row.transaction_date,
        row.posting_date,
        row.amount_cents,
        row.description,
        row.external_id,
        row.settlement_status,
    )


_CHECKING_STATUS = {"": "unknown", "PENDING": "pending", "POSTED": "posted"}


def _parse_checking_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    status = _CHECKING_STATUS.get(cells["Status"].strip().upper())
    if status is None:
        problems.append("invalid_status")
        status = "unknown"
    row = ParsedRow(
        transaction_date=_date(cells["Transaction Date"], "%Y-%m-%d", problems),
        posting_date=_date(cells["Posted Date"], "%Y-%m-%d", problems),
        amount_cents=_amount(cells["Amount"], problems),
        description=cells["Description"].strip() or None,
        external_id=cells["Transaction ID"].strip() or None,
        settlement_status=status,
    )
    return _finish(row, problems)


def _parse_card_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    debit = _amount(cells["Debit"], problems)
    credit = _amount(cells["Credit"], problems)

    amount = None
    if not problems:
        if debit is not None and credit is not None:
            problems.append("conflicting_amount")
        elif (debit or 0) < 0 or (credit or 0) < 0:
            problems.append("invalid_amount")
        elif debit is not None:
            amount = -debit
        else:
            amount = credit

    row = ParsedRow(
        posting_date=_date(cells["Date"], "%m/%d/%Y", problems),
        amount_cents=amount,
        description=cells["Description"].strip() or None,
        settlement_status="posted",
    )
    return _finish(row, problems)


SYNTHETIC_CHECKING_V1 = Layout(
    layout_id="synthetic_checking_v1",
    parser_version="1",
    columns=("Transaction ID", "Transaction Date", "Posted Date", "Description", "Amount", "Status"),
    parse_row=_parse_checking_row,
    pending_in_complete_coverage={"transaction": True, "posting": False},
    external_ids_reliable=True,
    has_metadata_preamble=True,
)

SYNTHETIC_CARD_V1 = Layout(
    layout_id="synthetic_card_v1",
    parser_version="1",
    columns=("Date", "Description", "Debit", "Credit"),
    parse_row=_parse_card_row,
    pending_in_complete_coverage={"posting": False},
)

LAYOUTS = {layout.layout_id: layout for layout in (SYNTHETIC_CHECKING_V1, SYNTHETIC_CARD_V1)}
