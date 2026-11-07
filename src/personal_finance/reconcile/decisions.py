"""Writing identity decisions. See decisions.md D-042, D-043, D-045 and D-046.

Every command checks everything under one write lock and either commits the decision with
its re-derivation or changes nothing. Refusals name no amounts or descriptions.
"""

import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations, product

from personal_finance.reconcile.apply import (
    is_current,
    load_constraints,
    load_evidence,
    reconcile_account,
)
from personal_finance.reconcile.cross_document import (
    RELATION_DIFFERENT,
    RELATION_SAME,
    RULE_CANDIDATES,
    RULE_DECISION,
    _DisjointSet,
    derive,
    directly_linked,
)
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
CONFIRM_UNSUPPORTED = (
    "only cross-document candidate items and decision conflicts can be confirmed. Other kinds "
    "stay open for later workflows. Nothing was changed."
)
GROUP_REPEATED = "a transaction was named more than once. Nothing was changed."
GROUP_OUTSIDE = "a group names a transaction that is not in this item. Nothing was changed."
STATES_NOTHING = (
    "these groups state nothing: name at least two transactions, in one group or in two. "
    "Nothing was changed."
)
CONFIRMS_NOTHING = (
    "every group here holds one transaction, so this only keeps them apart. Nothing was "
    "changed. Use review reject for direct pairs."
)
GROUP_SHARES_DOCUMENT = (
    "a group would hold two records from one document, which one transaction cannot. Nothing "
    "was changed. Put them in separate groups."
)
GROUP_NOT_CONNECTED = (
    "a group holds a transaction that is not linked to the rest of it directly, or through one "
    "withheld match. Nothing was changed. Run review show to see the direct pairs."
)
CONTRADICTS = (
    "a group joins transactions that decision {decisions} keeps apart. Nothing was changed. "
    "To replace that decision, inspect it with review decision show, then confirm again "
    "naming it with --supersedes."
)
WOULD_CHANGE_MORE = (
    "this confirmation would change more than the transactions it names, so it was not "
    "recorded and nothing was changed."
)
STALE_DECISION_REVISION = (
    "this revision does not match the decision's current evidence, so undoing it could regroup "
    "records you have not seen. Nothing was changed. Run review decision show and check again."
)


# One confirmation names at most this many transactions (D-046).
MAX_CONFIRMED = 50

TOO_MANY = (
    f"one confirmation can name at most {MAX_CONFIRMED} transactions. Nothing was changed. "
    "Confirm part of the group, then review it again."
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
class Confirmation:
    decision_id: str
    groups: int
    transactions_before: int
    transactions_after: int
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
    for constraint in _different(load_constraints(conn, item.account_id)):
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
        for constraint in _different(load_constraints(conn, item.account_id))
    )


def _different(constraints):
    return [item for item in constraints if item.relation == RELATION_DIFFERENT]


def confirm_groups(
    conn: sqlite3.Connection,
    account_id: str,
    item_id: str,
    revision: str,
    groups: list[list[str]],
    rules: MatchingRules = DEFAULT_RULES,
) -> Confirmation:
    """Record an explicit partition of some of an item's transactions (D-046).

    Within a group the transactions are one event, and between groups different events.
    Nothing is implied about transactions left unnamed.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _confirm(conn, account_id, item_id, revision, groups, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _confirm(conn, account_id, item_id, revision, groups, rules) -> Confirmation:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    item = load_review_evidence(conn, item_id)
    if item is None:
        raise DecisionRefused(ITEM_NOT_FOUND)
    if item.account_id != account_id:
        raise DecisionRefused(ITEM_WRONG_ACCOUNT)
    if item.rule not in (RULE_CANDIDATES, RULE_DECISION):
        raise DecisionRefused(CONFIRM_UNSUPPORTED)
    if item.status != "open":
        raise DecisionRefused(ITEM_NOT_OPEN)
    if review_revision(item) != revision:
        raise DecisionRefused(STALE_REVISION)
    members = _check_groups(conn, item, groups, rules)
    contradicted = _contradicted(conn, account_id, groups, members)
    if contradicted:
        raise DecisionRefused(CONTRADICTS.format(decisions=", ".join(sorted(contradicted))))

    before = _memberships(conn, account_id)
    expected = {
        records for transaction_id, records in before.items()
        if not any(transaction_id in group for group in groups)
    }
    expected.update(
        frozenset(record for transaction_id in group for record in before[transaction_id])
        for group in groups
    )

    decision_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO decision (id, account_id, review_issue_id, item_revision, kind)
           VALUES (?, ?, ?, ?, 'confirm')""",
        (decision_id, account_id, item_id, revision),
    )
    _write_partition(conn, decision_id, groups, members)
    _record_event(conn, decision_id, "made", rules)

    reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = _memberships(conn, account_id)
    if set(after.values()) != expected:
        raise DecisionRefused(WOULD_CHANGE_MORE)

    still_open = conn.execute("SELECT 1 FROM review_issue WHERE id = ?", (item_id,)).fetchone()
    return Confirmation(decision_id, len(groups), len(before), len(after), still_open is not None)


def _check_groups(conn, item, groups, rules) -> dict[str, list]:
    """Each named transaction's records, once every group is shown to be valid."""
    present = {entry.transaction_id: entry for entry in item.transactions}
    named = [transaction_id for group in groups for transaction_id in group]
    if len(named) != len(set(named)):
        raise DecisionRefused(GROUP_REPEATED)
    if not set(named) <= present.keys():
        raise DecisionRefused(GROUP_OUTSIDE)
    if len(named) > MAX_CONFIRMED:
        raise DecisionRefused(TOO_MANY)
    if len(named) < 2:
        raise DecisionRefused(STATES_NOTHING)
    # Rejection is for direct pairs only (D-045). A conflict can be settled by keeping all apart.
    if item.rule == RULE_CANDIDATES and all(len(group) == 1 for group in groups):
        raise DecisionRefused(CONFIRMS_NOTHING)

    documents, records, unresolved, _ = load_evidence(conn, item.account_id)
    rows = {record.id: record for record in records}
    members = {
        transaction_id: [rows[record.record_id] for record in present[transaction_id].records]
        for transaction_id in named
    }
    withheld = ()
    if item.rule == RULE_DECISION:
        constraints = load_constraints(conn, item.account_id)
        withheld = derive(documents, records, unresolved, rules, constraints).withheld_merges

    for group in groups:
        held = [row for transaction_id in group for row in members[transaction_id]]
        if len({row.document_id for row in held}) < len(held):
            raise DecisionRefused(GROUP_SHARES_DOCUMENT)
        if not _connected(group, members, documents, rules, withheld):
            raise DecisionRefused(GROUP_NOT_CONNECTED)
    return members


def _connected(group, members, documents, rules, withheld) -> bool:
    """Through direct links (D-045), or for a conflict through one withheld merge."""
    if len(group) < 2:
        return True
    merge_of = {record: number for number, merge in enumerate(withheld) for record in merge}
    joined = _DisjointSet(len(group))
    for left, right in combinations(range(len(group)), 2):
        one, other = members[group[left]], members[group[right]]
        shared = {merge_of.get(row.id) for row in one} & {merge_of.get(row.id) for row in other}
        if shared - {None} or directly_linked(one, other, documents, rules):
            joined.union(left, right)
    return len(joined.components()) == 1


def _contradicted(conn, account_id, groups, members) -> set[str]:
    """Active decisions keeping apart records that a group would join."""
    found = set()
    constraints = _different(load_constraints(conn, account_id))
    for group in groups:
        held = {row.id for transaction_id in group for row in members[transaction_id]}
        for constraint in constraints:
            if held.intersection(constraint.left) and held.intersection(constraint.right):
                found.add(constraint.decision_id)
    return found


def _write_partition(conn, decision_id, groups, members) -> None:
    """Every stated pair, written out: one event within a group, different events between."""
    pairs = [
        (RELATION_SAME, pair) for group in groups for pair in combinations(sorted(group), 2)
    ]
    pairs += [
        (RELATION_DIFFERENT, tuple(sorted(pair)))
        for one, other in combinations(groups, 2)
        for pair in product(one, other)
    ]
    for number, (relation, (left, right)) in enumerate(sorted(pairs), start=1):
        conn.executemany(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                                                left_transaction_id, right_transaction_id,
                                                left_record_id, right_record_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (decision_id, relation, number, left, right, one.id, other.id)
                for one, other in product(members[left], members[right])
            ],
        )


def _memberships(conn, account_id) -> dict[str, frozenset[str]]:
    found = defaultdict(set)
    for transaction_id, record_id in conn.execute(
        "SELECT transaction_id, source_record_id FROM transaction_source WHERE account_id = ?",
        (account_id,),
    ):
        found[transaction_id].add(record_id)
    return {key: frozenset(value) for key, value in found.items()}


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
