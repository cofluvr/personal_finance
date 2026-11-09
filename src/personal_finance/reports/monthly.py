"""Monthly reports with disclosures (D-013, D-057 recommendations 6 and 7).

Everything here reads the ledger and nothing writes to it. Each transaction is in the month of its
effective transaction date, else its effective posting date, so the months add to `totals` exactly.
Migration 0001 refuses a transaction with neither date, and no correction clears one, so D-057's
no-date line would always be empty: a transaction without one stops the report instead.
"""

import calendar
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from personal_finance.reconcile.coverage_in_effect import (
    complete_coverage_by_basis,
    spans_cover_every_day,
)
from personal_finance.reports.totals import (
    CONFIRMED_TRANSFER_SQL,
    IncomeAndSpending,
    IncomeAndSpendingTally,
)

DATED_BY_TRANSACTION_DATE = "transaction_date"
DATED_BY_POSTING_DATE = "posting_date"


@dataclass
class MonthReport:
    """One calendar month, as YYYY-MM."""

    month: str
    transactions: int = 0
    pending_transactions: int = 0
    net_cents: int = 0
    dated_by_transaction_date: int = 0
    dated_by_posting_date: int = 0
    tally: IncomeAndSpendingTally = field(default_factory=IncomeAndSpendingTally)
    # Names of the accounts in scope whose complete transaction-basis coverage spans every day of
    # the month, and of the rest.
    accounts_covered: tuple[str, ...] = ()
    accounts_not_covered: tuple[str, ...] = ()
    open_review_items: set[str] = field(default_factory=set)
    transactions_in_open_review_items: int = 0
    transactions_with_unsettled_correction: int = 0
    transactions_with_unsettled_classification: int = 0
    transactions_with_unsettled_match: int = 0
    transactions_with_unsettled_one_sided_transfer: int = 0
    # Sides here of applied matches whose other side is in another month (G6).
    matched_sides_with_other_side_in_another_month: int = 0

    @property
    def income_and_spending(self) -> IncomeAndSpending:
        return self.tally.result()


@dataclass(frozen=True)
class MonthlyReport:
    months: tuple[MonthReport, ...]
    # Transactions in scope dated in months outside the range asked for, and their net amount.
    transactions_outside_range: int
    net_cents_outside_range: int
    # Rows of the accounts in scope that are no transaction, so no month counts them (D-050).
    unresolved_records: int


def month_days(month: str) -> list[date]:
    year, number = int(month[:4]), int(month[5:])
    first = date(year, number, 1)
    return [first + timedelta(days=offset)
            for offset in range(calendar.monthrange(year, number)[1])]


def months_between(first_month: str, last_month: str) -> list[str]:
    """Every month from the first through the last, as YYYY-MM."""
    year, number = int(first_month[:4]), int(first_month[5:])
    found = []
    while f"{year:04d}-{number:02d}" <= last_month:
        found.append(f"{year:04d}-{number:02d}")
        year, number = (year + 1, 1) if number == 12 else (year, number + 1)
    return found


def _transactions_with_unsettled_effects(conn) -> dict[str, set[str]]:
    """The transactions now holding each kind of unsettled correction, classification, match or
    one-sided transfer. A match or one-sided transfer that does not apply names no transaction, so
    it is placed through the current transactions of the records it binds."""
    return {
        kind: {row[0] for row in conn.execute(query)}
        for kind, query in (
            ("correction", """SELECT transaction_id FROM transaction_correction
                              WHERE state <> 'applied'"""),
            ("classification", """SELECT transaction_id FROM transaction_classification
                                  WHERE state <> 'applied'"""),
            ("match", """SELECT link.transaction_id FROM transfer_match_effect effect
                         JOIN transfer_match_record bound ON bound.match_id = effect.match_id
                         JOIN transaction_source link
                             ON link.source_record_id = bound.source_record_id
                         WHERE effect.state <> 'applied'"""),
            ("one_sided", """SELECT link.transaction_id FROM one_sided_transfer_effect effect
                             JOIN one_sided_transfer_record bound
                                 ON bound.one_sided_transfer_id = effect.one_sided_transfer_id
                             JOIN transaction_source link
                                 ON link.source_record_id = bound.source_record_id
                             WHERE effect.state <> 'applied'"""),
        )
    }


def monthly_report(conn: sqlite3.Connection, account_id: str | None = None,
                   first_month: str | None = None, last_month: str | None = None) -> MonthlyReport:
    """Each month from the first through the last, inclusive, for the ledger or one account.

    Without a range, the months run from the first month holding a transaction to the last, with
    empty months between shown, so a gap stays visible. Effective amounts and dates are corrected
    values where they apply (D-049). Months are YYYY-MM, already validated.
    """
    month_by_transaction = {}
    in_scope = []
    for (transaction_id, transaction_account_id, amount_cents, transaction_date, posting_date,
         settlement_status, financial_type, confirmed_transfer) in conn.execute(
        f"""SELECT entry.id, entry.account_id,
                   COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
                   COALESCE(date_fix.corrected_text, entry.transaction_date),
                   COALESCE(posting_fix.corrected_text, entry.posting_date),
                   entry.settlement_status, kind.financial_type,
                   {CONFIRMED_TRANSFER_SQL}
            FROM ledger_transaction entry
            LEFT JOIN transaction_correction amount_fix
                ON amount_fix.transaction_id = entry.id AND amount_fix.field = 'amount'
               AND amount_fix.state = 'applied'
            LEFT JOIN transaction_correction date_fix
                ON date_fix.transaction_id = entry.id AND date_fix.field = 'transaction_date'
               AND date_fix.state = 'applied'
            LEFT JOIN transaction_correction posting_fix
                ON posting_fix.transaction_id = entry.id AND posting_fix.field = 'posting_date'
               AND posting_fix.state = 'applied'
            LEFT JOIN transaction_classification kind ON kind.transaction_id = entry.id"""
    ):
        # Every transaction's month, so a match's side in another account can be compared.
        reporting_date = transaction_date or posting_date
        if reporting_date is None:
            raise AssertionError("a transaction has neither a transaction date nor a posting date")
        month_by_transaction[transaction_id] = reporting_date[:7]
        if account_id is None or transaction_account_id == account_id:
            dated_by = DATED_BY_TRANSACTION_DATE if transaction_date else DATED_BY_POSTING_DATE
            in_scope.append((transaction_id, amount_cents, settlement_status, financial_type,
                             confirmed_transfer, dated_by))

    dated_months = sorted({month_by_transaction[transaction_id]
                           for transaction_id, *_ in in_scope})
    if first_month is None and last_month is None and not dated_months:
        shown_months = []
    else:
        # A missing end defaults to the data's, stretched to reach the given one.
        last = last_month or max(month for month in (*dated_months[-1:], first_month) if month)
        first = first_month or min((*dated_months[:1], last))
        shown_months = months_between(first, last)
    reports = {month: MonthReport(month) for month in shown_months}

    accounts = conn.execute(
        """SELECT id, display_name FROM account WHERE :account IS NULL OR id = :account
           ORDER BY display_name, id""",
        {"account": account_id},
    ).fetchall()
    spans_by_account = {
        account: complete_coverage_by_basis(conn, account).get("transaction", [])
        for account, _ in accounts
    }
    for month, report in reports.items():
        days = month_days(month)
        covered = {account for account, _ in accounts
                   if spans_cover_every_day(days, spans_by_account[account])}
        report.accounts_covered = tuple(name for account, name in accounts if account in covered)
        report.accounts_not_covered = tuple(name for account, name in accounts
                                            if account not in covered)

    review_items_by_transaction = {}
    for transaction_id, item_id in conn.execute(
        """SELECT subject.transaction_id, issue.id
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           WHERE issue.status = 'open' AND subject.transaction_id IS NOT NULL"""
    ):
        review_items_by_transaction.setdefault(transaction_id, set()).add(item_id)
    unsettled = _transactions_with_unsettled_effects(conn)

    outside_range = outside_range_cents = 0
    for (transaction_id, amount_cents, settlement_status, financial_type, confirmed_transfer,
         dated_by) in in_scope:
        report = reports.get(month_by_transaction[transaction_id])
        if report is None:
            outside_range += 1
            outside_range_cents += amount_cents
            continue
        report.transactions += 1
        report.net_cents += amount_cents
        report.pending_transactions += settlement_status == "pending"
        report.dated_by_transaction_date += dated_by == DATED_BY_TRANSACTION_DATE
        report.dated_by_posting_date += dated_by == DATED_BY_POSTING_DATE
        report.tally.add(amount_cents, financial_type, confirmed_transfer)
        if transaction_id in review_items_by_transaction:
            report.open_review_items |= review_items_by_transaction[transaction_id]
            report.transactions_in_open_review_items += 1
        report.transactions_with_unsettled_correction += transaction_id in unsettled["correction"]
        report.transactions_with_unsettled_classification += (
            transaction_id in unsettled["classification"])
        report.transactions_with_unsettled_match += transaction_id in unsettled["match"]
        report.transactions_with_unsettled_one_sided_transfer += (
            transaction_id in unsettled["one_sided"])

    scope = {transaction_id for transaction_id, *_ in in_scope}
    for sides in conn.execute(
        """SELECT outflow_transaction_id, inflow_transaction_id FROM transfer_match_effect
           WHERE state = 'applied'"""
    ):
        outflow_month, inflow_month = (month_by_transaction[side] for side in sides)
        if outflow_month == inflow_month:
            continue
        for side, month in zip(sides, (outflow_month, inflow_month)):
            report = reports.get(month)
            if side in scope and report is not None:
                report.matched_sides_with_other_side_in_another_month += 1

    (unresolved,) = conn.execute(
        """SELECT COUNT(*)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN source_record record ON record.id = subject.source_record_id
           WHERE issue.kind = 'unresolved_record' AND issue.status = 'open'
             AND (:account IS NULL OR record.account_id = :account)""",
        {"account": account_id},
    ).fetchone()
    return MonthlyReport(tuple(reports.values()), outside_range, outside_range_cents, unresolved)
