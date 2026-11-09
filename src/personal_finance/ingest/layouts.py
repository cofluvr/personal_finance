"""Tested document layouts. See layouts.md for what each one promises.

The synthetic layouts are invented for development. The institution layouts are
written from the lead engineer's knowledge of each export, not from a sample, and stay
unverified until a real file reconciles with its statement (D-059). A layout's meaning
never changes once used: a change in meaning needs a new layout_id, so that stored documents
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
    # What the layout promises about its IDs: none, stable or stable_unique. Only a
    # namespace with a guarantee makes IDs comparable (D-026).
    external_id_guarantee: str = "none"
    external_id_namespace: str | None = None
    has_metadata_preamble: bool = False
    # A column naming the account by its last four digits. Every row must name the importing
    # account's, so a file cannot import into another account (D-061).
    account_number_column: str | None = None

    @property
    def external_ids_reliable(self) -> bool:
        return self.external_id_guarantee != "none"


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


def _debit_or_credit(debit_text: str, credit_text: str, problems: list[str]) -> int | None:
    """Money out as negative cents from a positive debit, money in from a positive credit."""
    debit = _amount(debit_text, problems)
    credit = _amount(credit_text, problems)
    if problems:
        return None
    if debit is not None and credit is not None:
        problems.append("conflicting_amount")
        return None
    if (debit or 0) < 0 or (credit or 0) < 0:
        problems.append("invalid_amount")
        return None
    if debit is not None:
        return -debit
    return credit


def _parse_card_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    amount = _debit_or_credit(cells["Debit"], cells["Credit"], problems)
    row = ParsedRow(
        posting_date=_date(cells["Date"], "%m/%d/%Y", problems),
        amount_cents=amount,
        description=cells["Description"].strip() or None,
        settlement_status="posted",
    )
    return _finish(row, problems)


def _parse_capital_one_card_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    amount = _debit_or_credit(cells["Debit"], cells["Credit"], problems)
    row = ParsedRow(
        transaction_date=_date(cells["Transaction Date"], "%Y-%m-%d", problems),
        posting_date=_date(cells["Posted Date"], "%Y-%m-%d", problems),
        amount_cents=amount,
        description=cells["Description"].strip() or None,
    )
    return _finish(row, problems)


_CAPITAL_ONE_BANK_DIRECTION = {"DEBIT": -1, "CREDIT": 1}


def _parse_capital_one_bank_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    direction = _CAPITAL_ONE_BANK_DIRECTION.get(cells["Transaction Type"].strip().upper())
    if direction is None:
        problems.append("invalid_direction")
    amount = _amount(cells["Transaction Amount"], problems)
    if amount is not None and amount < 0 and not problems:
        problems.append("invalid_amount")
    signed = None if problems or amount is None else direction * amount
    row = ParsedRow(
        transaction_date=_date(cells["Transaction Date"], "%m/%d/%y", problems),
        amount_cents=signed,
        description=cells["Transaction Description"].strip() or None,
    )
    return _finish(row, problems)


_DEBIT_OR_CREDIT = {"DEBIT": -1, "CREDIT": 1}


def _signed_agreeing(amount_text: str, direction_text: str, problems: list[str]) -> int | None:
    """A signed amount, which a Debit or Credit column must agree with."""
    direction = _DEBIT_OR_CREDIT.get(direction_text.strip().upper())
    if direction is None:
        problems.append("invalid_direction")
    amount = _amount(amount_text, problems)
    if amount is not None and amount * (direction or 0) < 0 and not problems:
        problems.append("conflicting_amount")
    return None if problems else amount


def _parse_us_bank_row(cells: Mapping[str, str]) -> ParsedRow:
    problems: list[str] = []
    signed = _signed_agreeing(cells["Amount"], cells["Transaction"], problems)
    row = ParsedRow(
        posting_date=_date(cells["Date"], "%Y-%m-%d", problems),
        amount_cents=signed,
        description=cells["Name"].strip() or None,
    )
    return _finish(row, problems)


def _parse_bfsfcu_row(cells: Mapping[str, str]) -> ParsedRow:
    """Only Posted is known from a real export, so any other status leaves the row unresolved."""
    problems: list[str] = []
    signed = _signed_agreeing(cells["Amount"], cells["Transaction Type"], problems)
    if cells["Posting Status"].strip().upper() != "POSTED":
        problems.append("invalid_status")
    row = ParsedRow(
        posting_date=_date(cells["Posting Date"], "%m/%d/%Y", problems),
        amount_cents=signed,
        description=cells["Description"].strip() or None,
        settlement_status="posted",
    )
    return _finish(row, problems)


def _parse_amex_row(cells: Mapping[str, str]) -> ParsedRow:
    """A charge is positive in this export, so the sign is reversed."""
    problems: list[str] = []
    amount = _amount(cells["Amount"], problems)
    signed = None if amount is None else -amount
    row = ParsedRow(
        posting_date=_date(cells["Date"], "%m/%d/%Y", problems),
        amount_cents=signed,
        description=cells["Description"].strip() or None,
    )
    return _finish(row, problems)


SYNTHETIC_CHECKING_V1 = Layout(
    layout_id="synthetic_checking_v1",
    parser_version="1",
    columns=("Transaction ID", "Transaction Date", "Posted Date", "Description", "Amount", "Status"),
    parse_row=_parse_checking_row,
    pending_in_complete_coverage={"transaction": True, "posting": False},
    external_id_guarantee="stable_unique",
    external_id_namespace="synthetic_checking_v1",
    has_metadata_preamble=True,
)

SYNTHETIC_CARD_V1 = Layout(
    layout_id="synthetic_card_v1",
    parser_version="1",
    columns=("Date", "Description", "Debit", "Credit"),
    parse_row=_parse_card_row,
    pending_in_complete_coverage={"posting": False},
)

# Capital One's card export. Card No. and Category stay in the raw cells, unread.
CAPITAL_ONE_CARD_V1 = Layout(
    layout_id="capital_one_card_v1",
    parser_version="1",
    columns=("Transaction Date", "Posted Date", "Card No.", "Description", "Category", "Debit", "Credit"),
    parse_row=_parse_capital_one_card_row,
    pending_in_complete_coverage={"transaction": False, "posting": False},
)

# Capital One's checking and savings export, its format confirmed from the owner's exports (D-061).
# Account Number must be the account's last four digits. Balance stays in the raw cells, unread: a
# balance is a person's observation, never transaction evidence (D-057).
CAPITAL_ONE_BANK_V1 = Layout(
    layout_id="capital_one_bank_v1",
    parser_version="1",
    columns=(
        "Account Number",
        "Transaction Description",
        "Transaction Date",
        "Transaction Type",
        "Transaction Amount",
        "Balance",
    ),
    parse_row=_parse_capital_one_bank_row,
    pending_in_complete_coverage={"transaction": False},
    account_number_column="Account Number",
)

# U.S. Bank's CSV activity list. Memo stays in the raw cells, unread.
US_BANK_V1 = Layout(
    layout_id="us_bank_v1",
    parser_version="1",
    columns=("Date", "Transaction", "Name", "Memo", "Amount"),
    parse_row=_parse_us_bank_row,
    pending_in_complete_coverage={"posting": False},
)

# American Express's card export. Nothing in a row can confirm the sign, so a statement
# reconciliation is the only check of it (D-059 point F).
AMEX_CARD_V1 = Layout(
    layout_id="amex_card_v1",
    parser_version="1",
    columns=("Date", "Description", "Amount"),
    parse_row=_parse_amex_row,
    pending_in_complete_coverage={"posting": False},
)

# BFSFCU's export, the one layout whose header and row format came from a real export, its
# values never kept (D-059 point E). Effective Date can fall after Posting Date, so it is not
# read as the transaction date. It, the Transaction ID and the other columns stay in the raw
# cells, unread.
BFSFCU_V1 = Layout(
    layout_id="bfsfcu_v1",
    parser_version="1",
    columns=(
        "Transaction ID",
        "Posting Date",
        "Effective Date",
        "Transaction Type",
        "Posting Status",
        "Amount",
        "Check Number",
        "Reference Number",
        "Description",
        "Transaction Category",
        "Type",
        "Balance",
        "Memo",
        "Extended Description",
    ),
    parse_row=_parse_bfsfcu_row,
    pending_in_complete_coverage={"posting": False},
)

LAYOUTS = {
    layout.layout_id: layout
    for layout in (
        SYNTHETIC_CHECKING_V1,
        SYNTHETIC_CARD_V1,
        CAPITAL_ONE_CARD_V1,
        CAPITAL_ONE_BANK_V1,
        US_BANK_V1,
        AMEX_CARD_V1,
        BFSFCU_V1,
    )
}
