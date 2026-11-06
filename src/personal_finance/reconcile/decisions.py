"""Writing identity decisions. See decisions.md D-042, D-043 and D-045.

Every command checks everything under one write lock and either commits the decision with
its re-derivation or changes nothing. Refusals name no amounts or descriptions.
"""

import sqlite3
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations, product

from personal_finance.reconcile.apply import (
    is_current,
    load_constraints,
    load_evidence,
    reconcile_account,
)
from personal_finance.reconcile.cross_document import RULE_CANDIDATES, directly_linked
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.decision_evidence import (
    STATE_ACTIVE,
    load_decision,
    undo_outlook,
)
from personal_finance.reports.review_evidence import (
    ReviewEvidence,
    load_review_evidence,
    review_revision,
)
from personal_finance.reports.totals import account_movement

STALE_ACCOUNT = (
    "this account is not current, so its evidence may have changed. Nothing was changed, and "
    "this command does not reconcile for you. Run reconcile, then review the evidence again."
)
ITEM_NOT_FOUND = "review item not found. A later import can replace one: run review list"
ITEM_WRONG_ACCOUNT = "this review item belongs to another account. Nothing was changed."
ITEM_UNSUPPORTED = (
    "only cross-document candidate items can be rejected. Other kinds stay open for later "
    "workflows. Nothing was changed."
)
ITEM_NOT_OPEN = "this review item is not open. Nothing was changed."
STALE_REVISION = (
    "this revision does not match the item's current evidence. Nothing was changed. "
    "Run review show and check the evidence again."
)
PAIR_SAME = "a pair must name two different transactions. Nothing was changed."
PAIR_REPEATED = "the same pair was given twice. Nothing was changed."
PAIR_OUTSIDE = "a pair names a transaction that is not in this item. Nothing was changed."
PAIR_DECIDED = "this pair is already kept apart by a decision. Nothing was changed."
PAIR_NOT_DIRECT = (
    "these two transactions are in this item only through other records, so they are not a "
    "direct candidate pair and cannot be rejected. Nothing was changed. Run review show to "
    "see the direct pairs."
)
WOULD_CHANGE_LEDGER = (
    "this rejection would change totals or source memberships, so it was not recorded and "
    "nothing was changed. Separating an existing merge belongs to a later workflow."
)
DECISION_NOT_FOUND = "decision not found. Run review decisions."
DECISION_WRONG_ACCOUNT = "this decision belongs to another account. Nothing was changed."
DECISION_NOT_ACTIVE = "this decision has already been undone. Nothing was changed."
STALE_DECISION_REVISION = (
    "this revision does not match the decision's current evidence, so undoing it could regroup "
    "records you have not seen. Nothing was changed. Run review decision show and check again."
)


class DecisionRefused(Exception):
    """A decision command was refused, and nothing changed."""


@dataclass(frozen=True)
class Rejection:
    decision_id: str
    pairs: int
    bound_record_pairs: int
    item_still_open: bool


@dataclass(frozen=True)
class Undo:
    transactions_before: int
    transactions_after: int
    moved_records: int


def undecided_direct_pairs(
    conn: sqlite3.Connection,
    item: ReviewEvidence,
    rules: MatchingRules = DEFAULT_RULES,
    among=None,
) -> Iterator[frozenset[str]]:
    """Transaction pairs in an item that a person can reject: linked directly, undecided.

    Lazy, because a dense group holds quadratically many. among limits it to given pairs.
    """
    documents, records, _, _ = load_evidence(conn, item.account_id)
    rows = {record.id: record for record in records}
    members = {
        entry.transaction_id: [rows[record.record_id] for record in entry.records]
        for entry in item.transactions
    }
    decided = set()
    for constraint in load_constraints(conn, item.account_id):
        decided.update(frozenset(pair) for pair in product(constraint.left, constraint.right))

    pairs = combinations(sorted(members), 2) if among is None else map(sorted, among)
    for left, right in pairs:
        bound = any(
            frozenset((one.id, other.id)) in decided
            for one, other in product(members[left], members[right])
        )
        if not bound and directly_linked(members[left], members[right], documents, rules):
            yield frozenset((left, right))


def reject_pairs(
    conn: sqlite3.Connection,
    account_id: str,
    item_id: str,
    revision: str,
    pairs: list[tuple[str, str]],
    rules: MatchingRules = DEFAULT_RULES,
) -> Rejection:
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _reject(conn, account_id, item_id, revision, pairs, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _reject(conn, account_id, item_id, revision, pairs, rules) -> Rejection:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    item = load_review_evidence(conn, item_id)
    if item is None:
        raise DecisionRefused(ITEM_NOT_FOUND)
    if item.account_id != account_id:
        raise DecisionRefused(ITEM_WRONG_ACCOUNT)
    if item.rule != RULE_CANDIDATES:
        raise DecisionRefused(ITEM_UNSUPPORTED)
    if item.status != "open":
        raise DecisionRefused(ITEM_NOT_OPEN)
    if review_revision(item) != revision:
        raise DecisionRefused(STALE_REVISION)
    _check_pairs(conn, item, pairs, rules)

    before = _ledger_state(conn, account_id)
    decision_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO decision (id, account_id, review_issue_id, item_revision)
           VALUES (?, ?, ?, ?)""",
        (decision_id, account_id, item_id, revision),
    )
    members = {
        entry.transaction_id: [record.record_id for record in entry.records]
        for entry in item.transactions
    }
    bound = 0
    for number, (left, right) in enumerate(pairs, start=1):
        for left_record, right_record in product(members[left], members[right]):
            conn.execute(
                """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                                                    left_transaction_id, right_transaction_id,
                                                    left_record_id, right_record_id)
                   VALUES (?, 'different_event', ?, ?, ?, ?, ?)""",
                (decision_id, number, left, right, left_record, right_record),
            )
            bound += 1
    _record_event(conn, decision_id, "made", rules)

    result = reconcile_account(conn, account_id, rules)
    if result.moved_records or _ledger_state(conn, account_id) != before:
        raise DecisionRefused(WOULD_CHANGE_LEDGER)

    still_open = conn.execute("SELECT 1 FROM review_issue WHERE id = ?", (item_id,)).fetchone()
    return Rejection(decision_id, len(pairs), bound, still_open is not None)


def _check_pairs(conn, item, pairs, rules) -> None:
    present = {entry.transaction_id for entry in item.transactions}
    seen = set()
    for left, right in pairs:
        if left == right:
            raise DecisionRefused(PAIR_SAME)
        if left not in present or right not in present:
            raise DecisionRefused(PAIR_OUTSIDE)
        pair = frozenset((left, right))
        if pair in seen:
            raise DecisionRefused(PAIR_REPEATED)
        seen.add(pair)

    direct = set(undecided_direct_pairs(conn, item, rules, among=seen))
    for pair in seen - direct:
        raise DecisionRefused(PAIR_DECIDED if _already_decided(conn, item, pair) else PAIR_NOT_DIRECT)


def _already_decided(conn, item, pair) -> bool:
    records = {
        entry.transaction_id: {record.record_id for record in entry.records}
        for entry in item.transactions
    }
    left, right = (records[transaction_id] for transaction_id in sorted(pair))
    return any(
        (left & set(constraint.left) and right & set(constraint.right))
        or (left & set(constraint.right) and right & set(constraint.left))
        for constraint in load_constraints(conn, item.account_id)
    )


def _ledger_state(conn, account_id):
    """Totals and memberships, which a rejection must leave exactly as they were."""
    links = conn.execute(
        """SELECT transaction_id, source_record_id FROM transaction_source
           WHERE account_id = ? ORDER BY source_record_id""",
        (account_id,),
    ).fetchall()
    movement = account_movement(conn, account_id)
    return links, movement.inflow_cents, movement.outflow_cents, movement.transactions


def _record_event(conn, decision_id, event, rules) -> None:
    conn.execute(
        "INSERT INTO decision_event (decision_id, event, rules_fingerprint) VALUES (?, ?, ?)",
        (decision_id, event, rules.fingerprint()),
    )


def undo_decision(
    conn: sqlite3.Connection,
    account_id: str,
    decision_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> Undo:
    """Re-derive from current evidence without this decision, keeping it on record.

    This is not a restored snapshot: evidence may have arrived since (D-043).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _undo(conn, account_id, decision_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _undo(conn, account_id, decision_id, revision, rules) -> Undo:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    decision = load_decision(conn, decision_id)
    if decision is None:
        raise DecisionRefused(DECISION_NOT_FOUND)
    if decision.account_id != account_id:
        raise DecisionRefused(DECISION_WRONG_ACCOUNT)
    if decision.state != STATE_ACTIVE:
        raise DecisionRefused(DECISION_NOT_ACTIVE)
    if undo_outlook(conn, decision, rules).revision != revision:
        raise DecisionRefused(STALE_DECISION_REVISION)

    before = account_movement(conn, account_id).transactions
    _record_event(conn, decision_id, "undone", rules)
    result = reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = account_movement(conn, account_id).transactions
    return Undo(before, after, result.moved_records)
