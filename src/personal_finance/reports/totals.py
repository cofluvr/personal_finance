"""Account movement totals. See decisions.md D-010.

These are movements on accounts, not income or spending: they still include
transfers and card payments.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountMovement:
    inflow_cents: int
    outflow_cents: int
    net_cents: int
    transactions: int
    pending_transactions: int
    unresolved_records: int
    candidate_groups: int
    transactions_in_candidate_groups: int
    decision_conflicts: int = 0
    transactions_in_decision_conflicts: int = 0
    transactions_with_withheld_match: int = 0
    transactions_with_changed_basis: int = 0


def account_movement(conn: sqlite3.Connection, account_id: str | None = None) -> AccountMovement:
    """Summarise every logical transaction, or those of one account."""
    inflow, outflow, net, transactions, pending = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN amount_cents > 0 THEN amount_cents END), 0),
                  COALESCE(-SUM(CASE WHEN amount_cents < 0 THEN amount_cents END), 0),
                  COALESCE(SUM(amount_cents), 0),
                  COUNT(*),
                  COUNT(CASE WHEN settlement_status = 'pending' THEN 1 END)
           FROM ledger_transaction
           WHERE :account IS NULL OR account_id = :account""",
        {"account": account_id},
    ).fetchone()

    unresolved = conn.execute(
        """SELECT COUNT(*)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN source_record record ON record.id = subject.source_record_id
           WHERE issue.kind = 'unresolved_record' AND issue.status = 'open'
             AND (:account IS NULL OR record.account_id = :account)""",
        {"account": account_id},
    ).fetchone()[0]

    groups, members = conn.execute(
        """SELECT COUNT(DISTINCT issue.id), COUNT(DISTINCT subject.transaction_id)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN ledger_transaction entry ON entry.id = subject.transaction_id
           WHERE issue.kind = 'possible_duplicate' AND issue.status = 'open'
             AND (:account IS NULL OR entry.account_id = :account)""",
        {"account": account_id},
    ).fetchone()

    conflicts = conn.execute(
        """SELECT COUNT(DISTINCT issue.id), COUNT(DISTINCT subject.transaction_id),
                  COUNT(DISTINCT CASE WHEN EXISTS (
                      SELECT 1 FROM json_each(issue.evidence_json, '$.reasons')
                      WHERE value = 'automatic_match_withheld')
                      THEN subject.transaction_id END),
                  COUNT(DISTINCT CASE WHEN EXISTS (
                      SELECT 1 FROM json_each(issue.evidence_json, '$.reasons')
                      WHERE value = 'decision_basis_changed')
                      THEN subject.transaction_id END)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN ledger_transaction entry ON entry.id = subject.transaction_id
           WHERE issue.kind = 'decision_conflict' AND issue.status = 'open'
             AND (:account IS NULL OR entry.account_id = :account)""",
        {"account": account_id},
    ).fetchone()

    return AccountMovement(
        inflow, outflow, net, transactions, pending, unresolved, groups, members, *conflicts
    )
