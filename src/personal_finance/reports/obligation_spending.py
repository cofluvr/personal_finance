"""Fixed and discretionary spending (D-068 point 5, IB3): D-056's Spending split by the class of
the obligation reaching each transaction, read from the derived transaction_obligation.

A spending transaction reached by a fixed obligation, outside obligation_conflict, is fixed. Every
other spending transaction is discretionary, refunds included. Categories are untouched.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL, SPENDING_TYPES
from personal_finance.reports.totals import GroupTotal


@dataclass(frozen=True)
class SpendingByClass:
    """D-056's Spending split by obligation class, actual amounts. They add to Spending exactly,
    in transactions, money out and money in (IB3)."""

    fixed: GroupTotal
    discretionary: GroupTotal


def spending_by_class(conn: sqlite3.Connection, account_id: str | None = None,
                      month: str | None = None) -> SpendingByClass:
    """Spending reached by a fixed obligation, outside obligation_conflict, is fixed. Every other
    spending transaction, refunds included, is discretionary. A month is chosen as D-057's."""
    marks = ", ".join("?" for _ in SPENDING_TYPES)
    fixed = discretionary = GroupTotal()
    for amount_cents, is_fixed in conn.execute(
        f"""SELECT COALESCE(fix.corrected_amount_cents, entry.amount_cents),
                   EXISTS (SELECT 1 FROM transaction_obligation derived
                           WHERE derived.transaction_id = entry.id
                             AND derived.obligation_class = 'fixed')
            FROM ledger_transaction entry
            JOIN transaction_classification kind
                ON kind.transaction_id = entry.id AND kind.state = 'applied'
               AND kind.financial_type IN ({marks})
            LEFT JOIN transaction_correction fix
                ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
            LEFT JOIN transaction_correction date_fix
                ON date_fix.transaction_id = entry.id
               AND date_fix.field = 'transaction_date' AND date_fix.state = 'applied'
            LEFT JOIN transaction_correction posting_fix
                ON posting_fix.transaction_id = entry.id
               AND posting_fix.field = 'posting_date' AND posting_fix.state = 'applied'
            WHERE NOT ({CONFIRMED_TRANSFER_SQL})
              AND (? IS NULL OR entry.account_id = ?)
              AND (? IS NULL OR substr(COALESCE(date_fix.corrected_text, entry.transaction_date,
                                                posting_fix.corrected_text, entry.posting_date),
                                       1, 7) = ?)""",
        (*SPENDING_TYPES, account_id, account_id, month, month),
    ):
        if is_fixed:
            fixed = fixed.adding(amount_cents)
        else:
            discretionary = discretionary.adding(amount_cents)
    return SpendingByClass(fixed, discretionary)
