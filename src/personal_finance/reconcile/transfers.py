"""Matching transfers between two accounts, and stating one-sided transfers, as a person states
them. See decisions.md D-054 and D-055.

Every command checks both accounts under one write lock and either commits with the ledger's
transfer outcomes rewritten or changes nothing. Neither moves a record or changes an amount or
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
    TRANSFER_TYPES,
    counterpart_found,
    coverage_spans_window,
    current_transfer_effects,
    holds_active_one_sided,
    one_sided_type_fits,
    pair_refusal,
    transaction_facts,
    unsettled_transfers,
    write_transfer_effects,
)
from personal_finance.reconcile.coverage_in_effect import complete_coverage_by_basis
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision
from personal_finance.reports.transfer_evidence import (
    load_match,
    load_one_sided,
    match_revision,
    one_sided_revision,
)

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
PAIR_HOLDS_ONE_SIDED = (
    "a one-sided transfer binds one of these transactions. Nothing was changed. Undo it first, "
    "with review transfer undo, then match."
)
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


ONE_SIDED_SAME_ACCOUNT = (
    "the counterpart is the transaction's own account, and a transfer moves money between two. "
    "Nothing was changed."
)
ONE_SIDED_ALREADY_MATCHED = (
    "a transfer match already binds this transaction. Nothing was changed. Undo it first, with "
    "review transfer undo."
)
ONE_SIDED_ALREADY_STATED = (
    "a one-sided transfer already binds this transaction. Nothing was changed. Undo it first, "
    "with review transfer undo."
)
ONE_SIDED_NO_TRANSFER_TYPE = (
    "the transaction is not classified as a transfer, card payment, loan payment or investment "
    "contribution. Nothing was changed. Classify it first with review classify."
)
ONE_SIDED_TYPE_DOES_NOT_FIT = (
    "the transaction's type does not fit a transfer to the counterpart account. A card payment "
    "needs a credit card, a loan payment a loan, and an investment contribution an investment or "
    "retirement account. Nothing was changed."
)
ONE_SIDED_COUNTERPART_IN_VIEW = (
    "a transaction of the counterpart account may be the other side, so the transfer is not "
    "one-sided. Nothing was changed. Run review transfers, and match the pair instead."
)
ONE_SIDED_COUNTERPART_COVERED = (
    "the counterpart account's complete coverage spans every date within "
    f"{TRANSFER_DATE_WINDOW_DAYS} days of this transaction, so its other side would be in the "
    "ledger. Nothing was changed. Check the counterpart, or its coverage."
)
ONE_SIDED_NOT_FOUND = "one-sided transfer not found. Run review transfers."
ONE_SIDED_WRONG_ACCOUNT = (
    "this one-sided transfer is between two other accounts. Name its account or its counterpart. "
    "Nothing was changed."
)
ONE_SIDED_NOT_ACTIVE = "this one-sided transfer has already been undone. Nothing was changed."
STALE_ONE_SIDED_REVISION = (
    "this revision does not match the one-sided transfer's current evidence. Nothing was changed. "
    "Run review transfer show and check again."
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
    if any(holds_active_one_sided(conn, transaction_id)
           for transaction_id in record_ids_by_transaction):
        raise DecisionRefused(PAIR_HOLDS_ONE_SIDED)
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
) -> int:
    """Stop a match applying, keeping it on record. Both sides are unmatched again.

    A match constrains no identity, so this never refuses for contradiction (D-054). It returns
    how many one-sided transfers it newly leaves unsettled, as a side freed can bring their
    counterpart into view (D-055).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        newly_unsettled = _undo(conn, account_id, match_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return newly_unsettled


def _undo(conn, account_id, match_id, revision, rules) -> int:
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
    unsettled_before = unsettled_transfers(conn)
    _record_match_event(conn, match_id, "undone")
    write_transfer_effects(conn)
    return len(unsettled_transfers(conn) - unsettled_before)


def _record_match_event(conn, match_id, event) -> None:
    conn.execute(
        "INSERT INTO transfer_match_event (match_id, event) VALUES (?, ?)", (match_id, event)
    )


@dataclass(frozen=True)
class OneSidedStated:
    one_sided_transfer_id: str
    record_count: int


def state_one_sided(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    counterpart_account_id: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> OneSidedStated:
    """Record that a transaction moves money between its account and a counterpart account whose
    side is not in the ledger. It binds every record of the transaction now (D-055)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _state_one_sided(conn, account_id, transaction_id, revision,
                                  counterpart_account_id, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _state_one_sided(conn, account_id, transaction_id, revision, counterpart_account_id,
                     rules) -> OneSidedStated:
    if account_id == counterpart_account_id:
        raise DecisionRefused(ONE_SIDED_SAME_ACCOUNT)
    for account in (account_id, counterpart_account_id):
        if not is_current(conn, account, rules):
            raise DecisionRefused(STALE_ACCOUNT)
    merge = load_merge_evidence(conn, transaction_id)
    if merge is None:
        raise DecisionRefused(TRANSACTION_NOT_FOUND.format(transaction=transaction_id))
    if merge.account_id != account_id:
        raise DecisionRefused(TRANSACTION_WRONG_ACCOUNT.format(transaction=transaction_id))
    if transaction_revision(merge) != revision:
        raise DecisionRefused(STALE_TRANSACTION_REVISION.format(transaction=transaction_id))

    facts = transaction_facts(conn, [transaction_id])[transaction_id]
    if facts.matched:
        raise DecisionRefused(ONE_SIDED_ALREADY_MATCHED)
    if holds_active_one_sided(conn, transaction_id):
        raise DecisionRefused(ONE_SIDED_ALREADY_STATED)
    if facts.financial_type not in TRANSFER_TYPES:
        raise DecisionRefused(ONE_SIDED_NO_TRANSFER_TYPE)
    (counterpart_type,) = conn.execute(
        "SELECT account_type FROM account WHERE id = ?", (counterpart_account_id,)).fetchone()
    if not one_sided_type_fits(facts, counterpart_type):
        raise DecisionRefused(ONE_SIDED_TYPE_DOES_NOT_FIT)
    if counterpart_found(conn, facts, counterpart_account_id):
        raise DecisionRefused(ONE_SIDED_COUNTERPART_IN_VIEW)
    if coverage_spans_window(facts.dates,
                             complete_coverage_by_basis(conn, counterpart_account_id)):
        raise DecisionRefused(ONE_SIDED_COUNTERPART_COVERED)

    statement_id = str(uuid.uuid4())
    record_ids = sorted(record.record_id for record in merge.transaction.records)
    conn.execute(
        """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                           target_transaction_id, target_revision)
           VALUES (?, ?, ?, ?, ?)""",
        (statement_id, account_id, counterpart_account_id, transaction_id, revision),
    )
    conn.executemany(
        """INSERT INTO one_sided_transfer_record (one_sided_transfer_id, source_record_id)
           VALUES (?, ?)""",
        [(statement_id, record_id) for record_id in record_ids],
    )
    _record_one_sided_event(conn, statement_id, "made")
    write_transfer_effects(conn)
    # A statement that passed every check always applies. Anything else is a fault here.
    if current_transfer_effects(conn)[1][statement_id].state != MATCH_APPLIED:
        raise AssertionError("a one-sided transfer that passed its checks did not apply")
    return OneSidedStated(statement_id, len(record_ids))


def undo_one_sided(
    conn: sqlite3.Connection,
    account_id: str,
    statement_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> int:
    """Stop a one-sided transfer applying, keeping it on record. It never refuses for
    contradiction, and returns how many statements it newly leaves unsettled (D-055)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        newly_unsettled = _undo_one_sided(conn, account_id, statement_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return newly_unsettled


def _undo_one_sided(conn, account_id, statement_id, revision, rules) -> int:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    statement = load_one_sided(conn, statement_id)
    if statement is None:
        raise DecisionRefused(ONE_SIDED_NOT_FOUND)
    if account_id not in statement.account_ids:
        raise DecisionRefused(ONE_SIDED_WRONG_ACCOUNT)
    for account in statement.account_ids:
        if not is_current(conn, account, rules):
            raise DecisionRefused(STALE_ACCOUNT)
    if statement.state != STATE_ACTIVE:
        raise DecisionRefused(ONE_SIDED_NOT_ACTIVE)
    if one_sided_revision(conn, statement) != revision:
        raise DecisionRefused(STALE_ONE_SIDED_REVISION)
    unsettled_before = unsettled_transfers(conn)
    _record_one_sided_event(conn, statement_id, "undone")
    write_transfer_effects(conn)
    return len(unsettled_transfers(conn) - unsettled_before)


def _record_one_sided_event(conn, statement_id, event) -> None:
    conn.execute(
        "INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) VALUES (?, ?)",
        (statement_id, event),
    )
