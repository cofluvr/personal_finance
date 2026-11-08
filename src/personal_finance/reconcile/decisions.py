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
    STATE_ACTIVE,
    STATE_SUPERSEDED,
    is_current,
    load_constraints,
    load_evidence,
    reconcile_account,
)
from personal_finance.reconcile.classification_effects import unsettled_classifications
from personal_finance.reconcile.transfer_effects import unsettled_matches
from personal_finance.reconcile.correction_effects import unsettled_correction_fields
from personal_finance.reconcile.cross_document import (
    RELATION_DIFFERENT,
    RELATION_SAME,
    RULE_CANDIDATES,
    RULE_DECISION,
    _DisjointSet,
    directly_linked,
    is_pending_and_posted,
    joins_distinct_ids,
)
from personal_finance.reconcile.same_document import RULE_SAME_DOCUMENT_PENDING_POSTED
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.decision_evidence import (
    load_decision,
    undo_outlook,
)
from personal_finance.reports.review_evidence import (
    ReviewEvidence,
    load_merge_evidence,
    load_review_evidence,
    review_revision,
    transaction_revision,
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
    "only cross-document candidate items, decision conflicts and pending and posted rows of one "
    "document can be confirmed. Other kinds stay open for later workflows. Nothing was changed."
)
SAME_DOCUMENT_GROUP = (
    "rows of one document can only be confirmed as one group of one pending and one posted "
    "transaction, each a single row. Nothing was changed."
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
DECISION_SUPERSEDED_IN_CHAIN = (
    "this decision is superseded by decision {newer}, which is superseded in turn, so it does "
    "not apply now. Nothing was changed. Only the newest decision of the chain, {newest}, can "
    "be undone, and each undo restores the one before it."
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


TRANSACTION_NOT_FOUND = (
    "transaction not found. A later import or decision can retire one: run review merges"
)
TRANSACTION_WRONG_ACCOUNT = "this transaction belongs to another account. Nothing was changed."
ONE_RECORD = "this transaction holds one record, so there is nothing to separate. Nothing was changed."
NOTHING_AUTOMATIC = (
    "every record here was confirmed as one event, so nothing in this transaction was joined "
    "automatically. Nothing was changed. To separate it, name that confirmation with "
    "--supersedes, or undo it."
)
IN_CONFLICT = (
    "this transaction is in an open decision conflict, which is settled through that item. "
    "Nothing was changed. Run review list, then confirm a partition on the conflict."
)
STALE_TRANSACTION_REVISION = (
    "this revision does not match the transaction's current evidence. Nothing was changed. "
    "Run review merge show and check the evidence again."
)
RECORD_REPEATED = "a record was named more than once. Nothing was changed."
RECORD_OUTSIDE = "a group names a record that is not in this transaction. Nothing was changed."
RECORD_UNNAMED = (
    "every record of this transaction must be in a group, so that nothing is separated without "
    "being stated. Nothing was changed. Run review merge show to see its records."
)
ONE_GROUP = (
    "a single group keeps every record together, which separates nothing. Nothing was changed. "
    "Give at least two groups."
)
SPLITS_CONFIRMED = (
    "a group boundary would separate records that decision {decisions} confirmed as one event. "
    "Nothing was changed. Keep them in one group, or name that confirmation with --supersedes."
)
SPLITS_OTHERS = (
    "a group boundary would separate records that decision {decisions} confirmed as one event, "
    "and only the decision named with --supersedes can be replaced. Nothing was changed."
)
JOINS_DISAGREEING_CORRECTIONS = (
    "this confirmation would join transactions whose corrections disagree, or split the records "
    "one correction binds, so their source values would be used. It was not recorded and nothing "
    "was changed. Undo one of those corrections first."
)
SPLITS_CORRECTED_RECORDS = (
    "this separation would split the records that one correction binds, or join corrections "
    "that disagree, so their source values would be used. It was not recorded and nothing was "
    "changed. Undo that correction first, then correct each part."
)
LEAVES_CLASSIFICATION_UNSETTLED = (
    "this decision would leave a classified transaction unclassified, because classifications "
    "would disagree, lose their basis or no longer fit its direction. It was not recorded and "
    "nothing was changed. Undo the classification first, then classify the result."
)
# Shared by every command that refuses to leave a transfer match unsettled (D-054).
LEAVES_TRANSFER_UNSETTLED = (
    "this would stop a transfer match applying, because a side's records would split or reach "
    "another match, its amounts would no longer offset, or a type would no longer fit. It was not "
    "recorded and nothing was changed. Undo the transfer match first, with review transfer undo."
)
WOULD_SPLIT_MORE = (
    "this separation would change more than the transaction it names, so it was not recorded "
    "and nothing was changed."
)


# One confirmation names at most this many transactions (D-046).
MAX_CONFIRMED = 50

TOO_MANY = (
    f"one confirmation can name at most {MAX_CONFIRMED} transactions. Nothing was changed. "
    "Confirm part of the group, then review it again."
)
TOO_MANY_RECORDS = (
    f"one separation can name at most {MAX_CONFIRMED} records, and this transaction holds more. "
    "Nothing was changed."
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
class Separation:
    decision_id: str
    groups: int
    transactions_before: int
    transactions_after: int
    # The guarantee of an ID that records in different groups share, which this overrides.
    overridden_id_guarantee: str | None = None
    # The pairs of a superseded confirmation that this one contradicts, and those it keeps.
    contradicted_pairs: int = 0
    kept_pairs: int = 0


@dataclass(frozen=True)
class Undo:
    transactions_before: int
    transactions_after: int
    moved_records: int
    # The decision this one superseded, which applies again.
    restored: str | None = None
    # Fields of transactions left on their source value by this undo, and not before (D-049).
    newly_unsettled_correction_fields: int = 0
    # Transactions left unclassified by this undo for a disagreement, and not before (D-053).
    newly_unclassified_transactions: int = 0
    # Transfer matches this undo stops applying, and that applied before (D-054).
    newly_unsettled_matches: int = 0


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
        """INSERT INTO decision (id, account_id, target_id, target_revision)
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
    if item.rule not in (RULE_CANDIDATES, RULE_DECISION, RULE_SAME_DOCUMENT_PENDING_POSTED):
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
        overturned = _joined_pairs(replaced, groups, members)
        kept = _account_for_pairs(replaced, overturned, replacing[2])

    before = _memberships(conn, account_id)
    unsettled_before = unsettled_correction_fields(conn, account_id)
    unclassified_before = unsettled_classifications(conn, account_id)
    unmatched_before = unsettled_matches(conn)
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
        """INSERT INTO decision (id, account_id, target_id, target_revision, kind,
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
    if unsettled_correction_fields(conn, account_id) - unsettled_before:
        raise DecisionRefused(JOINS_DISAGREEING_CORRECTIONS)
    if unsettled_classifications(conn, account_id) - unclassified_before:
        raise DecisionRefused(LEAVES_CLASSIFICATION_UNSETTLED)
    if unsettled_matches(conn) - unmatched_before:
        raise DecisionRefused(LEAVES_TRANSFER_UNSETTLED)

    still_open = conn.execute("SELECT 1 FROM review_issue WHERE id = ?", (item_id,)).fetchone()
    return Confirmation(
        decision_id, len(groups), len(before), len(after), still_open is not None,
        len(overturned) if replaced else 0, len(kept),
    )


def _same_event_roots(constraints) -> dict[str, str]:
    """A representative for each record an active same_event pair binds. Records of a
    transaction with more than one representative hold something joined automatically, a
    record no pair binds being its own (D-047)."""
    bound = sorted({
        record
        for constraint in constraints if constraint.relation == RELATION_SAME
        for record in (*constraint.left, *constraint.right)
    })
    place = {record: index for index, record in enumerate(bound)}
    joined = _DisjointSet(len(bound))
    for constraint in constraints:
        if constraint.relation == RELATION_SAME:
            sides = [place[record] for record in (*constraint.left, *constraint.right)]
            for record in sides[1:]:
                joined.union(sides[0], record)
    return {record: bound[joined.find(index)] for record, index in place.items()}


def separable_transactions(conn: sqlite3.Connection, account_id: str) -> list[tuple]:
    """Transactions holding records joined automatically, as ID, record count and link rules.

    IDs and counts only, so that routine output holds no financial data.
    """
    root = _same_event_roots(load_constraints(conn, account_id))
    members = defaultdict(list)
    rules = defaultdict(set)
    for transaction_id, record_id, link_rule in conn.execute(
        """SELECT transaction_id, source_record_id, link_rule FROM transaction_source
           WHERE account_id = ?""",
        (account_id,),
    ):
        members[transaction_id].append(record_id)
        rules[transaction_id].add(link_rule)
    return [
        (transaction_id, len(records), tuple(sorted(rules[transaction_id])))
        for transaction_id, records in sorted(members.items())
        if len({root.get(record, record) for record in records}) > 1
    ]


def separate_records(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    groups: list[list[str]],
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
    keep: tuple[int, ...] = (),
) -> Separation:
    """Record an explicit partition of every record of one transaction (D-047).

    Records in one group are one event, and records in different groups different events.
    Whole-group withholding then keeps the automatic merge apart. supersedes names a
    confirmation whose one-event pairs these groups split, with its undo token, and keep the
    numbers of its other pairs, all of which carry over (D-048).
    """
    replacing = (supersedes, supersedes_revision, tuple(keep)) if supersedes else None
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _separate(conn, account_id, transaction_id, revision, groups, rules, replacing)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _separate(conn, account_id, transaction_id, revision, groups, rules, replacing) -> Separation:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    merge = load_merge_evidence(conn, transaction_id)
    if merge is None:
        raise DecisionRefused(TRANSACTION_NOT_FOUND)
    if merge.account_id != account_id:
        raise DecisionRefused(TRANSACTION_WRONG_ACCOUNT)
    records = [record.record_id for record in merge.transaction.records]
    if len(records) < 2:
        raise DecisionRefused(ONE_RECORD)
    root = _same_event_roots(load_constraints(conn, account_id))
    # Splitting a confirmed core is what superseding is for, so the core alone is enough then.
    if replacing is None and len({root.get(record, record) for record in records}) < 2:
        raise DecisionRefused(NOTHING_AUTOMATIC)
    if _in_open_conflict(conn, transaction_id):
        raise DecisionRefused(IN_CONFLICT)
    if transaction_revision(merge) != revision:
        raise DecisionRefused(STALE_TRANSACTION_REVISION)
    replaced = _replaced(conn, account_id, replacing, rules) if replacing else None
    _check_record_groups(records, groups)
    split = _split_cores(conn, account_id, groups)
    if replaced is None and split:
        raise DecisionRefused(SPLITS_CONFIRMED.format(decisions=", ".join(sorted(split))))
    kept = overturned = ()
    if replaced is not None:
        others = split - {replaced.decision_id}
        if others:
            raise DecisionRefused(SPLITS_OTHERS.format(decisions=", ".join(sorted(others))))
        overturned = _split_pairs(replaced, groups)
        kept = _account_for_pairs(replaced, overturned, replacing[2])

    before = _memberships(conn, account_id)
    unsettled_before = unsettled_correction_fields(conn, account_id)
    unclassified_before = unsettled_classifications(conn, account_id)
    unmatched_before = unsettled_matches(conn)
    expected = {records for key, records in before.items() if key != transaction_id}
    expected.update(frozenset(group) for group in groups)

    decision_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO decision (id, account_id, target_id, target_revision, kind, target_kind,
                                 supersedes_decision_id)
           VALUES (?, ?, ?, ?, 'confirm', 'transaction', ?)""",
        (decision_id, account_id, transaction_id, revision, replaced and replaced.decision_id),
    )
    written = _write_record_partition(conn, decision_id, transaction_id, groups)
    if kept:
        _copy_pairs(conn, replaced.decision_id, kept, decision_id, written)
    _record_event(conn, decision_id, "made", rules)

    reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = _memberships(conn, account_id)
    if set(after.values()) != expected or any(
        _in_open_conflict(conn, key) for key, held in after.items() if held & set(records)
    ):
        raise DecisionRefused(WOULD_SPLIT_MORE)
    if unsettled_correction_fields(conn, account_id) - unsettled_before:
        raise DecisionRefused(SPLITS_CORRECTED_RECORDS)
    if unsettled_classifications(conn, account_id) - unclassified_before:
        raise DecisionRefused(LEAVES_CLASSIFICATION_UNSETTLED)
    if unsettled_matches(conn) - unmatched_before:
        raise DecisionRefused(LEAVES_TRANSFER_UNSETTLED)
    return Separation(
        decision_id, len(groups), len(before), len(after), _overridden_guarantee(merge, groups),
        len(overturned), len(kept),
    )


def _check_record_groups(records, groups) -> None:
    named = [record for group in groups for record in group]
    if len(named) != len(set(named)):
        raise DecisionRefused(RECORD_REPEATED)
    if not set(named) <= set(records):
        raise DecisionRefused(RECORD_OUTSIDE)
    if len(records) > MAX_CONFIRMED:
        raise DecisionRefused(TOO_MANY_RECORDS)
    if set(named) != set(records):
        raise DecisionRefused(RECORD_UNNAMED)
    if len(groups) < 2:
        raise DecisionRefused(ONE_GROUP)


def _split_cores(conn, account_id, groups) -> set[str]:
    """Active decisions with one-event pairs that a group boundary would split."""
    group_of = {record: number for number, group in enumerate(groups) for record in group}
    return {
        constraint.decision_id
        for constraint in load_constraints(conn, account_id)
        if constraint.relation == RELATION_SAME
        and len({group_of[record] for record in (*constraint.left, *constraint.right)
                 if record in group_of}) > 1
    }


def _in_open_conflict(conn, transaction_id) -> bool:
    return conn.execute(
        """SELECT 1 FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           WHERE issue.kind = 'decision_conflict' AND issue.status = 'open'
             AND subject.transaction_id = ?""",
        (transaction_id,),
    ).fetchone() is not None


def _write_record_partition(conn, decision_id, transaction_id, groups) -> None:
    """Every record pair, written out: one event within a group, different events between.

    Both sides start in one transaction, so the group numbers tell them apart. The lower group
    is always on the left. Returns how many pairs were written.
    """
    part = {record: number for number, group in enumerate(groups, start=1) for record in group}
    pairs = sorted(
        tuple(sorted(pair, key=lambda record: (part[record], record)))
        for pair in combinations(sorted(part), 2)
    )
    conn.executemany(
        """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                                            left_transaction_id, right_transaction_id,
                                            left_record_id, right_record_id, left_part,
                                            right_part)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (decision_id, RELATION_SAME if part[left] == part[right] else RELATION_DIFFERENT,
             number, transaction_id, transaction_id, left, right, part[left], part[right])
            for number, (left, right) in enumerate(pairs, start=1)
        ],
    )
    return len(pairs)


def _overridden_guarantee(merge, groups) -> str | None:
    """The guarantee of an ID shared by records that this puts in different groups, if any.

    Ordered by namespace, ID and guarantee, so that the choice never depends on generated IDs.
    """
    documents = {document.content_sha256: document for document in merge.documents}
    group_of = {record: number for number, group in enumerate(groups) for record in group}
    found = defaultdict(set)
    for record in merge.transaction.records:
        document = documents[record.content_sha256]
        if record.parsed.external_id and document.id_guarantee != "none":
            key = (document.id_namespace, record.parsed.external_id, document.id_guarantee)
            found[key].add(group_of[record.record_id])
    return next((key[2] for key, numbers in sorted(found.items()) if len(numbers) > 1), None)


def _replaced(conn, account_id, replacing, rules):
    """The decision being superseded, checked as undo would check it (D-043, D-046)."""
    decision_id, revision, _ = replacing
    decision = load_decision(conn, decision_id)
    if decision is None:
        raise DecisionRefused(DECISION_NOT_FOUND)
    if decision.account_id != account_id:
        raise DecisionRefused(DECISION_WRONG_ACCOUNT)
    _check_active(decision)
    if undo_outlook(conn, decision, rules).revision != revision:
        raise DecisionRefused(STALE_DECISION_REVISION)
    return decision


def _check_active(decision) -> None:
    """Only the newest decision of a chain applies, and only it can be undone (D-048)."""
    if decision.state == STATE_SUPERSEDED:
        if decision.newest != decision.superseded_by:
            raise DecisionRefused(DECISION_SUPERSEDED_IN_CHAIN.format(
                newer=decision.superseded_by, newest=decision.newest
            ))
        raise DecisionRefused(DECISION_SUPERSEDED.format(newer=decision.superseded_by))
    if decision.state != STATE_ACTIVE:
        raise DecisionRefused(DECISION_NOT_ACTIVE)


def _joined_pairs(replaced, groups, members) -> set[int]:
    """Numbers of the old decision's different_event pairs that a confirmation's groups join."""
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
    return overturned


def _split_pairs(replaced, groups) -> set[int]:
    """Numbers of the old decision's same_event pairs that a separation's groups split (D-048)."""
    group_of = {record: number for number, group in enumerate(groups) for record in group}
    return {
        number for number, pair in enumerate(replaced.pairs, start=1)
        if pair.relation == RELATION_SAME
        and len({group_of[record.record_id] for record in (*pair.left, *pair.right)
                 if record.record_id in group_of}) > 1
    }


def _account_for_pairs(replaced, overturned, keep):
    """Every pair of the old decision is contradicted or kept, and nothing is dropped silently.

    overturned holds the numbers of the pairs the new decision contradicts. Returns the numbers
    kept.
    """
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
    return tuple(sorted(set(keep)))


def _copy_pairs(conn, old_id, numbers, new_id, after) -> None:
    """Kept pairs, record for record, so that no new record is bound by carrying them over."""
    stored = sorted({row[0] for row in conn.execute(
        "SELECT pair_number FROM decision_constraint WHERE decision_id = ?", (old_id,)
    )})
    for offset, number in enumerate(numbers, start=after + 1):
        conn.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                                                left_transaction_id, right_transaction_id,
                                                left_record_id, right_record_id, left_part,
                                                right_part)
               SELECT ?, relation, ?, left_transaction_id, right_transaction_id, left_record_id,
                      right_record_id, left_part, right_part
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
    if item.rule == RULE_SAME_DOCUMENT_PENDING_POSTED:
        return _checked_same_document_pair(groups, members)
    for group in groups:
        held = [row for transaction_id in group for row in members[transaction_id]]
        if len({row.document_id for row in held}) < len(held):
            raise DecisionRefused(GROUP_SHARES_DOCUMENT)
        if joins_distinct_ids(held, {document.id: document for document in documents}):
            raise DecisionRefused(GROUP_DISTINCT_IDS)
        if not _connected(group, members, documents, rules):
            raise DecisionRefused(GROUP_NOT_CONNECTED)
    return members


def _checked_same_document_pair(groups, members) -> dict[str, list]:
    """The D-021 flag is the evidence that two rows of one document may be one event, so the only
    statement allowed is that one pending and one posted row are (D-052)."""
    if len(groups) != 1 or len(groups[0]) != 2:
        raise DecisionRefused(SAME_DOCUMENT_GROUP)
    rows = [members[transaction_id] for transaction_id in groups[0]]
    if any(len(held) != 1 for held in rows):
        raise DecisionRefused(SAME_DOCUMENT_GROUP)
    (left,), (right,) = rows
    if left.document_id != right.document_id or not is_pending_and_posted(left, right):
        raise DecisionRefused(SAME_DOCUMENT_GROUP)
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
    _check_active(decision)
    if undo_outlook(conn, decision, rules).revision != revision:
        raise DecisionRefused(STALE_DECISION_REVISION)
    restored = decision.supersedes_decision_id
    if restored and _inconsistent(conn, account_id, decision_id):
        raise DecisionRefused(RESTORE_CONTRADICTS.format(restored=restored))

    before = account_movement(conn, account_id).transactions
    unsettled_before = unsettled_correction_fields(conn, account_id)
    unclassified_before = unsettled_classifications(conn, account_id)
    unmatched_before = unsettled_matches(conn)
    _record_event(conn, decision_id, "undone", rules)
    result = reconcile_account(conn, account_id, rules, decision_id=decision_id)
    after = account_movement(conn, account_id).transactions
    newly_unsettled = unsettled_correction_fields(conn, account_id) - unsettled_before
    newly_unclassified = unsettled_classifications(conn, account_id) - unclassified_before
    return Undo(before, after, result.moved_records, restored, len(newly_unsettled),
                len(newly_unclassified), len(unsettled_matches(conn) - unmatched_before))


def _inconsistent(conn, account_id, without) -> bool:
    """Whether the decisions left after undoing one would join records kept apart.

    A restored decision can add different_event pairs, and a confirmation restored from under a
    separation its same_event pairs too (D-048), so every pair left is checked.
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
