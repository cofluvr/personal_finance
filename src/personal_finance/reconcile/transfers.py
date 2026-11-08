"""Matching transfers between two accounts, as a person states them. See decisions.md D-054.

Every command checks both accounts under one write lock and either commits with the ledger's
match outcomes rewritten or changes nothing. A match moves no record and changes no amount or
type, so nothing is derived again, and neither account is reconciled for the person.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.reconcile.apply import is_current
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE
from personal_finance.reconcile.transfer_effects import (
    INFLOW,
    MATCH_APPLIED,
    OUTFLOW,
    PAIR_ALREADY_MATCHED,
    PAIR_AMOUNTS_DO_NOT_OFFSET,
    PAIR_DATES_TOO_FAR,
    PAIR_NO_TRANSFER_TYPE,
    PAIR_SAME_ACCOUNT,
    PAIR_TYPE_DOES_NOT_FIT,
    TRANSFER_DATE_WINDOW_DAYS,
    current_transfer_effects,
    pair_refusal,
    transaction_facts,
    write_transfer_effects,
)
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision
from personal_finance.reports.transfer_evidence import load_match, match_revision

TRANSACTION_NOT_FOUND = (
    "transaction {transaction} not found. A later import or decision can retire one: run "
    "transactions"
)
TRANSACTION_WRONG_ACCOUNT = (
    "transaction {transaction} belongs to another account. Nothing was changed."
)
STALE_TRANSACTION_REVISION = (
    "the revision of transaction {transaction} does not match its current evidence. Nothing was "
    "changed. Run review transaction show and check the evidence again."
)
REFUSAL_BY_REASON = {
    PAIR_SAME_ACCOUNT: (
        "both transactions are in one account, and a transfer joins two. Nothing was changed."
    ),
    PAIR_ALREADY_MATCHED: (
        "a transfer match already binds one of these transactions. Nothing was changed. Undo it "
        "first, with review transfer undo."
    ),
    PAIR_AMOUNTS_DO_NOT_OFFSET: (
        "the amounts do not offset exactly, so these cannot be the two sides of one transfer. "
        "Nothing was changed. Fees apart from the amount transferred are not matched yet."
    ),
    PAIR_NO_TRANSFER_TYPE: (
        "neither transaction is classified as a transfer, card payment, loan payment or "
        "investment contribution. Nothing was changed. Equal amounts are not proof: classify one "
        "side first with review classify."
    ),
    PAIR_TYPE_DOES_NOT_FIT: (
        "a type stated on one side does not fit a transfer between these accounts. A card "
        "payment needs a credit card, a loan payment a loan, and an investment contribution an "
        "investment or retirement account. Nothing was changed."
    ),
    PAIR_DATES_TOO_FAR: (
        f"no date of one side is within {TRANSFER_DATE_WINDOW_DAYS} days of a date of the other. "
        "Nothing was changed."
    ),
}
MATCH_NOT_FOUND = "transfer match not found. Run review transfers."
MATCH_WRONG_ACCOUNT = (
    "this transfer match joins two other accounts. Name either of its accounts. Nothing was "
    "changed."
)
MATCH_NOT_ACTIVE = "this transfer match has already been undone. Nothing was changed."
STALE_MATCH_REVISION = (
    "this revision does not match the transfer match's current evidence. Nothing was changed. Run "
    "review transfer show and check again."
)


@dataclass(frozen=True)
class TransferMatched:
    match_id: str
    outflow_transaction_id: str
    inflow_transaction_id: str
    outflow_record_count: int
    inflow_record_count: int


def match_transfer(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    counterpart_account_id: str,
    counterpart_transaction_id: str,
    counterpart_revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> TransferMatched:
    """Record that two transactions of two accounts are the two sides of one transfer.

    Only a candidate pair can be matched. Each side binds every record of its transaction now, as
    a classification does (D-053, D-054).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _match(conn, ((account_id, transaction_id, revision),
                               (counterpart_account_id, counterpart_transaction_id,
                                counterpart_revision)), rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _match(conn, named_sides, rules) -> TransferMatched:
    if named_sides[0][0] == named_sides[1][0]:
        raise DecisionRefused(REFUSAL_BY_REASON[PAIR_SAME_ACCOUNT])
    for account_id, _, _ in named_sides:
        if not is_current(conn, account_id, rules):
            raise DecisionRefused(STALE_ACCOUNT)
    record_ids_by_transaction = {}
    for account_id, transaction_id, revision in named_sides:
        merge = load_merge_evidence(conn, transaction_id)
        if merge is None:
            raise DecisionRefused(TRANSACTION_NOT_FOUND.format(transaction=transaction_id))
        if merge.account_id != account_id:
            raise DecisionRefused(TRANSACTION_WRONG_ACCOUNT.format(transaction=transaction_id))
        if transaction_revision(merge) != revision:
            raise DecisionRefused(STALE_TRANSACTION_REVISION.format(transaction=transaction_id))
        record_ids_by_transaction[transaction_id] = sorted(
            record.record_id for record in merge.transaction.records)

    facts = transaction_facts(conn, list(record_ids_by_transaction))
    one, other = (facts[transaction_id] for _, transaction_id, _ in named_sides)
    reason = pair_refusal(one, other)
    if reason is not None:
        raise DecisionRefused(REFUSAL_BY_REASON[reason])
    outflow, inflow = (one, other) if one.amount_cents < 0 else (other, one)
    revision_by_transaction = {transaction_id: revision for _, transaction_id, revision in named_sides}

    match_id = str(uuid.uuid4())
    conn.execute("INSERT INTO transfer_match (id) VALUES (?)", (match_id,))
    for side, facts_of_side in ((OUTFLOW, outflow), (INFLOW, inflow)):
        conn.execute(
            """INSERT INTO transfer_match_side (match_id, side, account_id, target_transaction_id,
                                                target_revision)
               VALUES (?, ?, ?, ?, ?)""",
            (match_id, side, facts_of_side.account_id, facts_of_side.transaction_id,
             revision_by_transaction[facts_of_side.transaction_id]),
        )
        conn.executemany(
            """INSERT INTO transfer_match_record (match_id, side, source_record_id)
               VALUES (?, ?, ?)""",
            [(match_id, side, record_id)
             for record_id in record_ids_by_transaction[facts_of_side.transaction_id]],
        )
    _record_match_event(conn, match_id, "made")
    write_transfer_effects(conn)
    # A candidate always applies once matched. Anything else is a fault here, never stored.
    if current_transfer_effects(conn)[0][match_id].state != MATCH_APPLIED:
        raise AssertionError("a matched candidate did not apply")
    return TransferMatched(
        match_id, outflow.transaction_id, inflow.transaction_id,
        len(record_ids_by_transaction[outflow.transaction_id]),
        len(record_ids_by_transaction[inflow.transaction_id]),
    )


def undo_transfer(
    conn: sqlite3.Connection,
    account_id: str,
    match_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> None:
    """Stop a match applying, keeping it on record. Both sides are unmatched again.

    A match constrains no identity, so this never refuses for contradiction (D-054).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        _undo(conn, account_id, match_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _undo(conn, account_id, match_id, revision, rules) -> None:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    match = load_match(conn, match_id)
    if match is None:
        raise DecisionRefused(MATCH_NOT_FOUND)
    if account_id not in match.account_ids:
        raise DecisionRefused(MATCH_WRONG_ACCOUNT)
    for side_account in match.account_ids:
        if not is_current(conn, side_account, rules):
            raise DecisionRefused(STALE_ACCOUNT)
    if match.state != STATE_ACTIVE:
        raise DecisionRefused(MATCH_NOT_ACTIVE)
    if match_revision(conn, match) != revision:
        raise DecisionRefused(STALE_MATCH_REVISION)
    _record_match_event(conn, match_id, "undone")
    write_transfer_effects(conn)


def _record_match_event(conn, match_id, event) -> None:
    conn.execute(
        "INSERT INTO transfer_match_event (match_id, event) VALUES (?, ?)", (match_id, event)
    )
