"""What one stored decision rests on, and what undoing it would regroup (D-043, D-045).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from personal_finance.reconcile.apply import (
    decision_states,
    load_constraints,
    load_evidence,
    superseded_by,
)
from personal_finance.reconcile.classification_effects import (
    effective_classifications,
    load_active_classifications,
)
from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    effective_field_corrections,
    load_active_corrections,
)
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reconcile.supersession import successor_and_newest

# Bump whenever the material below changes, so an old token can never appear current. Version 3
# restores only the decision just before this one, so a chain reads differently (D-048). Version 4
# adds corrections binding records in scope, left out where there are none (D-049). Version 5
# marks records in scope completed by hand, left out where they are not (D-050). Version 6 adds
# classifications binding records in scope, left out where there are none (D-053).
DECISION_REVISION_VERSION = 6


@dataclass(frozen=True)
class BoundRecord:
    record_id: str
    content_sha256: str
    file_name: str
    row: int
    # Where the record is now, or None if it is not in a transaction.
    transaction_id: str | None


@dataclass(frozen=True)
class BoundPair:
    relation: str
    # Transaction IDs at decision time. A merge can retire them since.
    left_transaction_id: str
    right_transaction_id: str
    left: tuple[BoundRecord, ...]
    right: tuple[BoundRecord, ...]
    # A separation's group numbers, since both sides started in one transaction (D-047).
    left_part: int | None = None
    right_part: int | None = None


@dataclass(frozen=True)
class DecisionEvidence:
    decision_id: str
    account_id: str
    account_name: str
    # The review item or, for a separation, the transaction it was made on (D-047).
    target_id: str
    created_at: str
    state: str
    undone_at: str | None
    pairs: tuple[BoundPair, ...]
    # reject or confirm (D-046).
    kind: str = "reject"
    supersedes_decision_id: str | None = None
    # The decision replacing this one, while it is superseded. It can be superseded in turn.
    superseded_by: str | None = None
    # item or transaction.
    target_kind: str = "item"
    # The newest decision of its chain while superseded, the only one that can be undone (D-048).
    newest: str | None = None


@dataclass(frozen=True)
class UndoOutlook:
    """What undoing would do to the evidence as it stands now."""

    revision: str
    transactions_now: int
    transactions_after: int
    # Whether undoing would change which corrected values apply, or where (D-049).
    changes_corrected_values: bool = False
    # Whether undoing would change which classifications apply, or where (D-053).
    changes_classifications: bool = False


def shown_kind(kind: str, target_kind: str) -> str:
    """A separation is stored as a confirmation of a transaction's records (D-047)."""
    return "separate" if target_kind == "transaction" else kind


def list_decisions(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, kinds, states and counts only, so that routine output holds no financial data."""
    rows = conn.execute(
        """SELECT decision.id, account.display_name, decision.created_at, decision.account_id,
                  (SELECT COUNT(DISTINCT pair_number) FROM decision_constraint pair
                   WHERE pair.decision_id = decision.id),
                  CASE WHEN decision.target_kind = 'transaction' THEN 'separate'
                       ELSE decision.kind END
           FROM decision
           JOIN account ON account.id = decision.account_id
           WHERE :account IS NULL OR decision.account_id = :account
           ORDER BY decision.created_at, decision.id""",
        {"account": account_id},
    ).fetchall()
    states = {}
    for account in {row[3] for row in rows}:
        states.update(decision_states(conn, account))
    return [
        (decision_id, name, created_at, states[decision_id], pairs, kind)
        for decision_id, name, created_at, _, pairs, kind in rows
    ]


def load_decision(conn: sqlite3.Connection, decision_id: str) -> DecisionEvidence | None:
    row = conn.execute(
        """SELECT decision.account_id, account.display_name, decision.target_id,
                  decision.created_at, undone.created_at, decision.kind,
                  decision.supersedes_decision_id, decision.target_kind
           FROM decision
           JOIN account ON account.id = decision.account_id
           LEFT JOIN decision_event undone
               ON undone.decision_id = decision.id AND undone.event = 'undone'
           WHERE decision.id = ?""",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    account_id, account_name, target, created_at, undone_at, kind, supersedes, target_kind = row

    sides = {}
    for (number, relation, left_transaction, right_transaction, left, right, left_part,
         right_part) in conn.execute(
        """SELECT pair_number, relation, left_transaction_id, right_transaction_id,
                  left_record_id, right_record_id, left_part, right_part
           FROM decision_constraint WHERE decision_id = ?""",
        (decision_id,),
    ):
        entry = sides.setdefault(
            number,
            (relation, left_transaction, right_transaction, set(), set(), left_part, right_part),
        )
        entry[3].add(left)
        entry[4].add(right)

    pairs = tuple(
        BoundPair(relation, left_transaction, right_transaction,
                  _bound_records(conn, left), _bound_records(conn, right), left_part, right_part)
        for _, (relation, left_transaction, right_transaction, left, right, left_part,
                right_part) in sorted(sides.items())
    )
    states = decision_states(conn, account_id)
    successors = superseded_by(conn, account_id)
    newer, newest = successor_and_newest(successors, decision_id)
    return DecisionEvidence(
        decision_id, account_id, account_name, target, created_at, states[decision_id], undone_at,
        pairs, kind, supersedes, newer, target_kind, newest,
    )


def _bound_records(conn, record_ids) -> tuple[BoundRecord, ...]:
    found = []
    for record_id in record_ids:
        found.append(
            BoundRecord(
                record_id,
                *conn.execute(
                    """SELECT document.content_sha256, document.file_name, record.record_index,
                              link.transaction_id
                       FROM source_record record
                       JOIN source_document document ON document.id = record.source_document_id
                       LEFT JOIN transaction_source link ON link.source_record_id = record.id
                       WHERE record.id = ?""",
                    (record_id,),
                ).fetchone(),
            )
        )
    return tuple(sorted(found, key=lambda record: (record.content_sha256, record.row)))


def undo_outlook(
    conn: sqlite3.Connection, decision: DecisionEvidence, rules: MatchingRules
) -> UndoOutlook:
    """The undo token, and the transaction counts either side of an undo (D-045).

    The token covers the decision's state and everything relevant to regrouping: what
    derivation gives with and without this decision, and the evidence of every record
    that differs between the two or is bound by the decision. Without it means with any
    decision it superseded restored (D-046). Evidence that cannot affect the undo leaves it
    unchanged, so an unrelated file does not force another inspection.
    """
    documents, records, unresolved, _ = load_evidence(conn, decision.account_id)
    constraints = load_constraints(conn, decision.account_id)
    others = load_constraints(conn, decision.account_id, without=decision.decision_id)
    now = derive(documents, records, unresolved, rules, constraints)
    after = derive(documents, records, unresolved, rules, others)

    by_id = {document.id: document for document in documents}
    keys = {
        record.id: (by_id[record.document_id].content_sha256, record.row_index)
        for record in records
    }

    scope = {
        bound.record_id for pair in decision.pairs for bound in (*pair.left, *pair.right)
    }
    for changed in set(now.groups) ^ set(after.groups):
        scope.update(changed.record_ids)
    for changed in set(now.items) ^ set(after.items):
        scope.update(record for member in changed.members for record in member)
    for result in (now, after):
        for group in result.groups:
            if scope.intersection(group.record_ids):
                scope.update(group.record_ids)

    def key_of(record_id):
        return keys.get(record_id)

    def keyed(record_ids):
        return sorted(map(key_of, record_ids), key=repr)

    def view(result):
        return {
            "groups": sorted(
                ([keyed(group.record_ids), group.link_rule, key_of(group.primary_record_id)]
                 for group in result.groups if scope.intersection(group.record_ids)),
                key=repr,
            ),
            "items": sorted(
                ([item.rule, sorted(map(keyed, item.members), key=repr), item.reasons,
                  item.date_start, item.date_end]
                 for item in result.items
                 if scope.intersection(record for member in item.members for record in member)),
                key=repr,
            ),
        }

    material = {
        "state": decision.state,
        "pairs": sorted(_pair_keys(pair) for pair in decision.pairs),
        "rules": rules.fingerprint(),
        "records": sorted(
            ([key_of(record.id), record_material(record)]
             for record in records if record.id in scope),
            key=repr,
        ),
        "documents": sorted(
            (_without(asdict(by_id[document_id]), "id")
             for document_id in {record.document_id for record in records if record.id in scope}),
            key=repr,
        ),
        "other_decisions": sorted(
            [item.relation, item.confirmation,
             sorted((keyed(item.left), keyed(item.right)), key=repr)]
            for item in others
            if scope.intersection((*item.left, *item.right))
        ),
        "with_decision": view(now),
        "without_decision": view(after),
    }
    active_corrections = load_active_corrections(conn, decision.account_id)
    touching_corrections = [
        correction for correction in active_corrections if correction.bound_record_ids & scope
    ]
    changes_corrected_values = False
    if touching_corrections:
        corrected_record_ids = set().union(
            *(correction.bound_record_ids for correction in touching_corrections)
        )

        def correction_view(result):
            group_by_record_id = {
                record_id: index
                for index, group in enumerate(result.groups) for record_id in group.record_ids
            }
            effects = effective_field_corrections(active_corrections, group_by_record_id)
            return sorted(
                [keyed(result.groups[index].record_ids), field, effect.state, effect.applied_value]
                for (index, field), effect in effects.items()
                if corrected_record_ids.intersection(result.groups[index].record_ids)
            )

        material["corrections"] = {
            "bound": sorted(
                [correction.field, correction.corrected_value,
                 keyed(correction.bound_record_ids)]
                for correction in touching_corrections
            ),
            "with_decision": correction_view(now),
            "without_decision": correction_view(after),
        }
        changes_corrected_values = (
            material["corrections"]["with_decision"] != material["corrections"]["without_decision"]
        )
    changes_classifications = False
    active_classifications = load_active_classifications(conn, decision.account_id)
    touching_classifications = [
        classification for classification in active_classifications
        if classification.bound_record_ids & scope
    ]
    if touching_classifications:
        classified_record_ids = set().union(
            *(classification.bound_record_ids for classification in touching_classifications)
        )
        amount_by_record_id = {record.id: record.amount_cents for record in records}

        def classification_view(result):
            group_by_record_id = {
                record_id: index
                for index, group in enumerate(result.groups) for record_id in group.record_ids
            }
            # Each group's amount as totals would use it: the primary source's (D-030), or a
            # corrected amount applying there (D-049).
            amounts = {
                index: amount_by_record_id[group.primary_record_id]
                for index, group in enumerate(result.groups)
            }
            for (index, field), effect in effective_field_corrections(
                active_corrections, group_by_record_id
            ).items():
                if field == "amount" and effect.state == FIELD_APPLIED:
                    amounts[index] = effect.applied_value
            effects = effective_classifications(active_classifications, group_by_record_id,
                                                amounts)
            return sorted(
                [keyed(result.groups[index].record_ids), effect.state, effect.applied_value]
                for index, effect in effects.items()
                if classified_record_ids.intersection(result.groups[index].record_ids)
            )

        material["classifications"] = {
            "bound": sorted(
                [classification.corrected_value, keyed(classification.bound_record_ids)]
                for classification in touching_classifications
            ),
            "with_decision": classification_view(now),
            "without_decision": classification_view(after),
        }
        changes_classifications = (
            material["classifications"]["with_decision"]
            != material["classifications"]["without_decision"]
        )
    return UndoOutlook(decision_revision(material), len(now.groups), len(after.groups),
                       changes_corrected_values, changes_classifications)


def decision_revision(material: dict) -> str:
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"d{DECISION_REVISION_VERSION}-{digest}"


def _pair_keys(pair: BoundPair) -> list:
    """A stored pair's relation never changes, so it is not needed here."""
    return sorted(
        [[(record.content_sha256, record.row) for record in side]
         for side in (pair.left, pair.right)]
    )


def record_material(record) -> dict:
    """A record's values as tokens cover them, marking one completed by hand only when it is, so
    that a ledger without completions keeps its digests (D-050)."""
    fields = _without(asdict(record), "id", "document_id")
    if not fields["completed_by_hand"]:
        del fields["completed_by_hand"]
    return fields


def _without(fields: dict, *names: str) -> dict:
    return {key: value for key, value in fields.items() if key not in names}
