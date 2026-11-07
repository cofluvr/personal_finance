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
    directly_linked,
    joins_distinct_ids,
)
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.decision_evidence import (
    STATE_ACTIVE,
    STATE_SUPERSEDED,
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
GROUP_DISTINCT_IDS = (
    "a group would join two different IDs that the source guarantees unique, which proves "
    "they are different events. Nothing was changed. Put them in separate groups."
)
GROUP_NOT_CONNECTED = (
    "a group holds a transaction that is not linked directly to the rest of it. Nothing was "
    "changed. Run review show to see the direct pairs."
)
CONTRADICTS = (
    "a group joins transactions that decision {decisions} keeps apart. Nothing was changed. "
    "To replace that decision, inspect it with review decision show, then confirm again "
    "naming it with --supersedes."
)
CONTRADICTS_OTHERS = (
    "a group joins transactions that decision {decisions} keeps apart, and only the decision "
    "named with --supersedes can be replaced. Nothing was changed."
)
SUPERSEDES_NOTHING = (
    "these groups contradict nothing in the decision named with --supersedes, so there is "
    "nothing to replace. Nothing was changed."
)
KEEP_UNKNOWN = "--keep names a pair that the superseded decision does not have. Nothing was changed."
KEEP_CONTRADICTED = (
    "pair {number} of the superseded decision is contradicted by these groups, so it cannot be "
    "kept. Nothing was changed."
)
PAIR_UNACCOUNTED = (
    "pair {number} of the superseded decision is neither contradicted by these groups nor kept. "
    "Nothing was changed. Keep it with --keep {number}, or state the groups that replace it."
)
DECISION_SUPERSEDED = (
    "this decision is superseded by decision {newer}, so it does not apply now. Nothing was "
    "changed. Undo that decision instead, which restores this one."
)
RESTORE_CONTRADICTS = (
    "undoing this decision would restore decision {restored}, which contradicts decisions "
    "made since. Nothing was changed."
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
    # The pairs of a superseded decision that this one contradicts, and those it keeps.
    contradicted_pairs: int = 0
    kept_pairs: int = 0


@dataclass(frozen=True)
class Undo:
    transactions_before: int
    transactions_after: int
    moved_records: int
    # The decision this one superseded, which applies again.
    restored: str | None = None


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
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
    keep: tuple[int, ...] = (),
) -> Confirmation:
    """Record an explicit partition of some of an item's transactions (D-046).

    Within a group the transactions are one event, and between groups different events.
    Nothing is implied about transactions left unnamed. supersedes names the one decision
    this replaces, with its undo token, and keep the numbers of its pairs to carry over.
    """
    replacing = (supersedes, supersedes_revision, tuple(keep)) if supersedes else None
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _confirm(conn, account_id, item_id, revision, groups, rules, replacing)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _confirm(conn, account_id, item_id, revision, groups, rules, replacing) -> Confirmation:
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
    replaced = _replaced(conn, account_id, replacing, rules) if replacing else None
    members = _check_groups(conn, item, groups, rules)
    contradicted = _contradicted(conn, account_id, groups, members)
    if replaced is None and contradicted:
        raise DecisionRefused(CONTRADICTS.format(decisions=", ".join(sorted(contradicted))))
    kept = ()
    if replaced is not None:
        others = contradicted - {replaced.decision_id}
        if others:
            raise DecisionRefused(CONTRADICTS_OTHERS.format(decisions=", ".join(sorted(others))))
        kept, overturned = _account_for_pairs(replaced, groups, members, replacing[2])

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
        """INSERT INTO decision (id, account_id, review_issue_id, item_revision, kind,
                                 supersedes_decision_id)
           VALUES (?, ?, ?, ?, 'confirm', ?)""",
        (decision_id, account_id, item_id, revision, replaced and replaced.decision_id),
    )
    written = _write_partition(conn, decision_id, groups, members)
    if kept:
        _copy_pairs(conn, replaced.decision_id, kept, decision_id, written)
    _record_event(conn, decision_id, "made", rules)

    reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = _memberships(conn, account_id)
    if set(after.values()) != expected:
        raise DecisionRefused(WOULD_CHANGE_MORE)

    still_open = conn.execute("SELECT 1 FROM review_issue WHERE id = ?", (item_id,)).fetchone()
    return Confirmation(
        decision_id, len(groups), len(before), len(after), still_open is not None,
        len(overturned) if replaced else 0, len(kept),
    )


def _replaced(conn, account_id, replacing, rules):
    """The decision being superseded, checked as undo would check it (D-043, D-046)."""
    decision_id, revision, _ = replacing
    decision = load_decision(conn, decision_id)
    if decision is None:
        raise DecisionRefused(DECISION_NOT_FOUND)
    if decision.account_id != account_id:
        raise DecisionRefused(DECISION_WRONG_ACCOUNT)
    if decision.state == STATE_SUPERSEDED:
        raise DecisionRefused(DECISION_SUPERSEDED.format(newer=decision.superseded_by))
    if decision.state != STATE_ACTIVE:
        raise DecisionRefused(DECISION_NOT_ACTIVE)
    if undo_outlook(conn, decision, rules).revision != revision:
        raise DecisionRefused(STALE_DECISION_REVISION)
    return decision


def _account_for_pairs(replaced, groups, members, keep):
    """Every pair of the old decision is contradicted or kept, and nothing is dropped silently.

    Returns the pair numbers kept and those contradicted.
    """
    held = [{row.id for transaction_id in group for row in members[transaction_id]}
            for group in groups]
    overturned = set()
    for number, pair in enumerate(replaced.pairs, start=1):
        left = {record.record_id for record in pair.left}
        right = {record.record_id for record in pair.right}
        if pair.relation == RELATION_DIFFERENT and any(
            records & left and records & right for records in held
        ):
            overturned.add(number)
    if not overturned:
        raise DecisionRefused(SUPERSEDES_NOTHING)
    for number in sorted(keep):
        if not 1 <= number <= len(replaced.pairs):
            raise DecisionRefused(KEEP_UNKNOWN)
        if number in overturned:
            raise DecisionRefused(KEEP_CONTRADICTED.format(number=number))
    for number in range(1, len(replaced.pairs) + 1):
        if number not in overturned and number not in keep:
            raise DecisionRefused(PAIR_UNACCOUNTED.format(number=number))
    return tuple(sorted(set(keep))), overturned


def _copy_pairs(conn, old_id, numbers, new_id, after) -> None:
    """Kept pairs, record for record, so that no new record is bound by carrying them over."""
    stored = sorted({row[0] for row in conn.execute(
        "SELECT pair_number FROM decision_constraint WHERE decision_id = ?", (old_id,)
    )})
    for offset, number in enumerate(numbers, start=after + 1):
        conn.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                                                left_transaction_id, right_transaction_id,
                                                left_record_id, right_record_id)
               SELECT ?, relation, ?, left_transaction_id, right_transaction_id, left_record_id,
                      right_record_id
               FROM decision_constraint WHERE decision_id = ? AND pair_number = ?""",
            (new_id, offset, old_id, stored[number - 1]),
        )


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

    documents, records, _, _ = load_evidence(conn, item.account_id)
    rows = {record.id: record for record in records}
    members = {
        transaction_id: [rows[record.record_id] for record in present[transaction_id].records]
        for transaction_id in named
    }
    for group in groups:
        held = [row for transaction_id in group for row in members[transaction_id]]
        if len({row.document_id for row in held}) < len(held):
            raise DecisionRefused(GROUP_SHARES_DOCUMENT)
        if joins_distinct_ids(held, {document.id: document for document in documents}):
            raise DecisionRefused(GROUP_DISTINCT_IDS)
        if not _connected(group, members, documents, rules):
            raise DecisionRefused(GROUP_NOT_CONNECTED)
    return members


def _connected(group, members, documents, rules) -> bool:
    """Through direct links (D-045). The transactions of a withheld automatic match are always
    linked directly, because it joins rows alike in amount, dates and description."""
    joined = _DisjointSet(len(group))
    for left, right in combinations(range(len(group)), 2):
        if directly_linked(members[group[left]], members[group[right]], documents, rules):
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


def _write_partition(conn, decision_id, groups, members) -> int:
    """Every stated pair, written out: one event within a group, different events between.

    Returns how many pairs were written.
    """
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
    return len(pairs)


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
    if decision.state == STATE_SUPERSEDED:
        raise DecisionRefused(DECISION_SUPERSEDED.format(newer=decision.superseded_by))
    if decision.state != STATE_ACTIVE:
        raise DecisionRefused(DECISION_NOT_ACTIVE)
    if undo_outlook(conn, decision, rules).revision != revision:
        raise DecisionRefused(STALE_DECISION_REVISION)
    restored = decision.supersedes_decision_id
    if restored and _inconsistent(conn, account_id, decision_id):
        raise DecisionRefused(RESTORE_CONTRADICTS.format(restored=restored))

    before = account_movement(conn, account_id).transactions
    _record_event(conn, decision_id, "undone", rules)
    result = reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = account_movement(conn, account_id).transactions
    return Undo(before, after, result.moved_records, restored)


def _inconsistent(conn, account_id, without) -> bool:
    """Whether the decisions left after undoing one would join records kept apart.

    A restored decision adds no same_event pair, because superseding had to keep every one
    of them (D-046), so only its different_event pairs can contradict.
    """
    constraints = load_constraints(conn, account_id, without=without)
    _, records, _, _ = load_evidence(conn, account_id)
    place = {record.id: index for index, record in enumerate(records)}
    joined = _DisjointSet(len(place))
    for constraint in constraints:
        if constraint.relation == RELATION_SAME:
            bound = [place[record] for record in (*constraint.left, *constraint.right)]
            for record in bound[1:]:
                joined.union(bound[0], record)
    root = {record_id: joined.find(index) for record_id, index in place.items()}
    return any(
        {root[record] for record in constraint.left} & {root[record] for record in constraint.right}
        for constraint in _different(constraints)
    )
