"""Account movement totals. See decisions.md D-010.

These are movements on accounts, not income or spending: they still include
transfers and card payments.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.apply import STATE_ACTIVE, decision_states, declared_coverage
from personal_finance.reconcile.classification_effects import FINANCIAL_TYPES
from personal_finance.reconcile.transfer_effects import TRANSFER_TYPES, transfer_candidates


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
    # Transactions holding records a person confirmed as one event (D-046).
    transactions_confirmed: int = 0
    # Transactions holding records a separation keeps apart from an automatic match (D-047).
    transactions_separated: int = 0
    # Transactions using at least one corrected value, and those where corrections leave a field
    # on its source value because they disagree or lost their basis (D-049).
    transactions_corrected: int = 0
    transactions_with_correction_conflict: int = 0
    transactions_with_correction_basis_changed: int = 0
    # Transactions holding a record completed by hand, and rows dismissed as adding no transaction
    # (D-050).
    transactions_completed: int = 0
    records_dismissed: int = 0
    # Documents whose coverage a person declared after import (D-051).
    documents_with_declared_coverage: int = 0
    # Transactions counted at a posted amount other than their pending row's, and pending
    # transactions left long after the account's latest date (D-052).
    transactions_posted_at_changed_amount: int = 0
    stale_pending_transactions: int = 0
    # Each financial type that some transaction has, in the order of FINANCIAL_TYPES, with its
    # transaction count and effective amount, and the same for unclassified transactions (D-053). A
    # derived row holds a type only while it applies.
    financial_types: tuple[tuple[str, int, int], ...] = ()
    unclassified_transactions: int = 0
    unclassified_cents: int = 0
    # Transactions left unclassified because classifications disagree, lost their basis, or no
    # longer fit the transaction's direction (D-053).
    transactions_with_classification_conflict: int = 0
    transactions_with_classification_basis_changed: int = 0
    transactions_with_classification_against_direction: int = 0


def account_movement(conn: sqlite3.Connection, account_id: str | None = None) -> AccountMovement:
    """Summarise every logical transaction, or those of one account.

    Amounts are effective: a corrected amount where one applies, else the source value (D-049).
    """
    inflow, outflow, net, transactions, pending = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN effective_amount_cents > 0
                                    THEN effective_amount_cents END), 0),
                  COALESCE(-SUM(CASE WHEN effective_amount_cents < 0
                                     THEN effective_amount_cents END), 0),
                  COALESCE(SUM(effective_amount_cents), 0),
                  COUNT(*),
                  COUNT(CASE WHEN settlement_status = 'pending' THEN 1 END)
           FROM (SELECT COALESCE(fix.corrected_amount_cents, entry.amount_cents)
                            AS effective_amount_cents,
                        entry.settlement_status
                 FROM ledger_transaction entry
                 LEFT JOIN transaction_correction fix
                     ON fix.transaction_id = entry.id AND fix.field = 'amount'
                    AND fix.state = 'applied'
                 WHERE :account IS NULL OR entry.account_id = :account)""",
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

    confirmed = conn.execute(
        """SELECT COUNT(DISTINCT transaction_id) FROM transaction_source
           WHERE link_rule = 'confirmed_same_event'
             AND (:account IS NULL OR account_id = :account)""",
        {"account": account_id},
    ).fetchone()[0]

    corrections = conn.execute(
        """SELECT COUNT(DISTINCT CASE WHEN fix.state = 'applied' THEN fix.transaction_id END),
                  COUNT(DISTINCT CASE WHEN fix.state = 'conflict' THEN fix.transaction_id END),
                  COUNT(DISTINCT CASE WHEN fix.state = 'basis_changed'
                                      THEN fix.transaction_id END)
           FROM transaction_correction fix
           JOIN ledger_transaction entry ON entry.id = fix.transaction_id
           WHERE :account IS NULL OR entry.account_id = :account""",
        {"account": account_id},
    ).fetchone()

    resolutions = conn.execute(
        """SELECT COUNT(DISTINCT CASE WHEN resolution.kind = 'completed'
                                      THEN link.transaction_id END),
                  COUNT(CASE WHEN resolution.kind = 'dismissed' THEN 1 END)
           FROM record_resolution resolution
           LEFT JOIN transaction_source link ON link.source_record_id = resolution.source_record_id
           WHERE (:account IS NULL OR resolution.account_id = :account)
             AND NOT EXISTS (SELECT 1 FROM record_resolution_event undone
                             WHERE undone.resolution_id = resolution.id
                               AND undone.event = 'undone')""",
        {"account": account_id},
    ).fetchone()

    return AccountMovement(
        inflow, outflow, net, transactions, pending, unresolved, groups, members, *conflicts,
        confirmed, _separated(conn, account_id), *corrections, *resolutions,
        _declared_documents(conn, account_id), *_pending_disclosures(conn, account_id),
        *_classifications(conn, account_id),
    )


def _classifications(conn, account_id) -> tuple:
    by_type = {
        financial_type: (count, cents)
        for financial_type, count, cents in conn.execute(
            """SELECT kind.financial_type, COUNT(*),
                      COALESCE(SUM(COALESCE(fix.corrected_amount_cents, entry.amount_cents)), 0)
               FROM ledger_transaction entry
               LEFT JOIN transaction_correction fix
                   ON fix.transaction_id = entry.id AND fix.field = 'amount'
                  AND fix.state = 'applied'
               LEFT JOIN transaction_classification kind
                   ON kind.transaction_id = entry.id
               WHERE :account IS NULL OR entry.account_id = :account
               GROUP BY kind.financial_type""",
            {"account": account_id},
        )
    }
    unclassified_count, unclassified_cents = by_type.pop(None, (0, 0))
    unsettled = conn.execute(
        """SELECT COUNT(CASE WHEN kind.state = 'conflict' THEN 1 END),
                  COUNT(CASE WHEN kind.state = 'basis_changed' THEN 1 END),
                  COUNT(CASE WHEN kind.state = 'against_direction' THEN 1 END)
           FROM transaction_classification kind
           JOIN ledger_transaction entry ON entry.id = kind.transaction_id
           WHERE :account IS NULL OR entry.account_id = :account""",
        {"account": account_id},
    ).fetchone()
    return (
        tuple((financial_type, *by_type[financial_type])
              for financial_type in FINANCIAL_TYPES if financial_type in by_type),
        unclassified_count, unclassified_cents, *unsettled,
    )


@dataclass(frozen=True)
class TransferSummary:
    """Transfers between accounts, counted for the ledger or for the matches with a side in one
    account (D-054). Account movement is unchanged by any of it."""

    # Applied matches, and the amount they move, counted once per match.
    matches: int
    matched_cents: int
    # Transactions in a candidate pair, the account's own only for one account.
    transactions_in_candidates: int
    # Transactions of a transfer kind that are in neither a match nor a candidate pair.
    unpaired_transfer_kind: int
    basis_changed: int
    conflicts: int
    amounts_differ: int
    types_differ: int


def transfer_summary(conn: sqlite3.Connection, account_id: str | None = None) -> TransferSummary:
    states = dict(conn.execute(
        """SELECT effect.state, COUNT(*) FROM transfer_match_effect effect
           WHERE :account IS NULL OR EXISTS (
               SELECT 1 FROM transfer_match_side side
               WHERE side.match_id = effect.match_id AND side.account_id = :account)
           GROUP BY effect.state""",
        {"account": account_id},
    ))
    matched_cents = conn.execute(
        """SELECT COALESCE(SUM(COALESCE(fix.corrected_amount_cents, entry.amount_cents)), 0)
           FROM transfer_match_effect effect
           JOIN ledger_transaction entry ON entry.id = effect.inflow_transaction_id
           LEFT JOIN transaction_correction fix
               ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
           WHERE :account IS NULL OR :account IN (
               entry.account_id,
               (SELECT outflow.account_id FROM ledger_transaction outflow
                WHERE outflow.id = effect.outflow_transaction_id))""",
        {"account": account_id},
    ).fetchone()[0]
    in_candidates = {
        facts.transaction_id
        for candidate in transfer_candidates(conn, account_id)
        for facts in (candidate.outflow, candidate.inflow)
        if account_id is None or facts.account_id == account_id
    }
    marks = ", ".join("?" for _ in TRANSFER_TYPES)
    unpaired = sum(
        transaction_id not in in_candidates
        for (transaction_id,) in conn.execute(
            f"""SELECT entry.id FROM ledger_transaction entry
                JOIN transaction_classification kind ON kind.transaction_id = entry.id
                WHERE kind.state = 'applied' AND kind.financial_type IN ({marks})
                  AND (? IS NULL OR entry.account_id = ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM transaction_source link
                      JOIN transfer_match_record bound
                          ON bound.source_record_id = link.source_record_id
                      WHERE link.transaction_id = entry.id
                        AND NOT EXISTS (SELECT 1 FROM transfer_match_event undone
                                        WHERE undone.match_id = bound.match_id
                                          AND undone.event = 'undone'))""",
            (*TRANSFER_TYPES, account_id, account_id),
        )
    )
    return TransferSummary(
        states.get("applied", 0), matched_cents, len(in_candidates), unpaired,
        states.get("basis_changed", 0), states.get("conflict", 0),
        states.get("amounts_differ", 0), states.get("type_differs", 0),
    )


# A pending transaction this much older than its account's latest date is disclosed (D-016).
STALE_PENDING_DAYS = 10


def _pending_disclosures(conn, account_id) -> tuple[int, int]:
    changed = conn.execute(
        """SELECT COUNT(DISTINCT entry.id)
           FROM ledger_transaction entry
           JOIN transaction_source link ON link.transaction_id = entry.id
           JOIN document_interpretation meaning
               ON meaning.source_document_id = link.source_document_id
           JOIN record_parse parse ON parse.source_record_id = link.source_record_id
                                  AND parse.parser_version = meaning.parser_version
           WHERE (:account IS NULL OR entry.account_id = :account)
             AND entry.settlement_status <> 'pending' AND parse.settlement_status = 'pending'
             AND parse.amount_cents <> entry.amount_cents""",
        {"account": account_id},
    ).fetchone()[0]
    stale = conn.execute(
        """SELECT COUNT(*)
           FROM ledger_transaction entry
           JOIN (SELECT account_id,
                        MAX(MAX(COALESCE(transaction_date, '')), MAX(COALESCE(posting_date, '')))
                            AS latest
                 FROM ledger_transaction GROUP BY account_id) newest
               ON newest.account_id = entry.account_id
           WHERE (:account IS NULL OR entry.account_id = :account)
             AND entry.settlement_status = 'pending'
             AND julianday(newest.latest)
                 - julianday(COALESCE(entry.posting_date, entry.transaction_date)) > :days""",
        {"account": account_id, "days": STALE_PENDING_DAYS},
    ).fetchone()[0]
    return changed, stale


def _declared_documents(conn, account_id) -> int:
    accounts = [row[0] for row in conn.execute(
        """SELECT DISTINCT account_id FROM coverage_declaration
           WHERE :account IS NULL OR account_id = :account""",
        {"account": account_id},
    )]
    return sum(len(declared_coverage(conn, account)) for account in accounts)


def _separated(conn, account_id) -> int:
    separations = conn.execute(
        """SELECT id, account_id FROM decision
           WHERE target_kind = 'transaction' AND (:account IS NULL OR account_id = :account)""",
        {"account": account_id},
    ).fetchall()
    states = {}
    for account in {account for _, account in separations}:
        states.update(decision_states(conn, account))
    active = [decision for decision, _ in separations if states[decision] == STATE_ACTIVE]
    if not active:
        return 0
    marks = ", ".join("?" for _ in active)
    return conn.execute(
        f"""SELECT COUNT(DISTINCT link.transaction_id)
            FROM decision_constraint pair
            JOIN transaction_source link
                ON link.source_record_id IN (pair.left_record_id, pair.right_record_id)
            WHERE pair.relation = 'different_event' AND pair.decision_id IN ({marks})""",
        active,
    ).fetchone()[0]
