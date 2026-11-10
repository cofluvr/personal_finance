"""What one review item rests on, for explicit inspection. See decisions.md D-037 and D-040.

Everything here reads the ledger and nothing writes to it. Amounts and descriptions are
loaded because a person asked to see this one item, so nothing routine may call this.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass

from personal_finance.ingest.coverage import effective_end
from personal_finance.reconcile.apply import declared_coverage, load_constraints, stale_accounts
from personal_finance.reconcile.category_effects import load_active_categorizations
from personal_finance.reconcile.category_rule_effects import (
    load_active_rules,
    load_spending_facts,
    matching_rules,
)
from personal_finance.reconcile.classification_effects import load_active_classifications
from personal_finance.reconcile.correction_effects import load_active_corrections
from personal_finance.reconcile.household_effects import attributed_transactions, load_household
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfer_effects import INFLOW, OUTFLOW

# Bump whenever the material evidence changes, so an old token can never appear current. Version
# 4 adds corrections (D-049), version 5 completed values (D-050), version 6 declared coverage
# (D-051), version 7 classifications (D-053), version 8 transfer matches (D-054), version 9
# one-sided transfers (D-055), version 10 categorizations (D-063), and version 11 the category rules'
# outcome (D-064).
REVISION_VERSION = 11
# The same, for one transaction's evidence, which a separation, correction, classification,
# transfer match, one-sided transfer or categorization names (D-047, D-049, D-050, D-051, D-053,
# D-054, D-055, D-063). Version 8 adds categorizations, and version 9 the category rules' outcome
# (D-064).
TRANSACTION_REVISION_VERSION = 9

# Fields left out of a revision. Random IDs and names say where evidence is stored or how
# it is labelled, not what it says. Records are identified by document hash and row
# instead. A stale account is a warning about the rules, and any effect of reconciling
# reaches the token through the evidence itself. The household attribution an account's default
# gives is the same for every transaction of the account, so no decision or correction changes
# which applies, and it joins h1 and a1 instead (D-065 point 6).
IMMATERIAL_FIELDS = frozenset(
    {"issue_id", "transaction_id", "record_id", "file_name", "account_stale", "account_id",
     "account_name", "decision_id", "correction_id", "classification_id", "match_id",
     "counterpart_transaction_id", "one_sided_transfer_id", "categorization_id", "rule_id",
     "household"}
)
# Fields left out while empty, so that evidence holding none keeps the digest it had before they
# existed (D-049).
OMITTED_WHILE_EMPTY = frozenset({"corrections", "completion", "declared", "classifications",
                                 "transfers", "one_sided_transfers", "categorizations",
                                 "category_rules"})


@dataclass(frozen=True)
class ParsedValues:
    """What the parser read from a row. Never altered by a merge or a decision."""

    status: str
    reason_code: str | None
    transaction_date: str | None
    posting_date: str | None
    amount_cents: int | None
    description: str | None
    external_id: str | None
    settlement_status: str


@dataclass(frozen=True)
class CompletedValues:
    """What a person supplied for an unresolved record, each None where it supplied nothing
    because the parse had a value (D-050). Kept apart from what the parser read."""

    amount_cents: int | None
    transaction_date: str | None
    posting_date: str | None
    description: str | None


@dataclass(frozen=True)
class RecordEvidence:
    record_id: str
    content_sha256: str
    file_name: str
    row: int
    cells: tuple[str, ...]
    parsed: ParsedValues
    link_rule: str | None
    # Set only for a record completed by hand.
    completion: CompletedValues | None = None


@dataclass(frozen=True)
class DecidedRecord:
    content_sha256: str
    file_name: str
    row: int


@dataclass(frozen=True)
class CorrectionEvidence:
    """An active correction binding a record of one transaction (D-049)."""

    correction_id: str
    field: str
    # Integer cents for an amount, text for the other fields.
    corrected_value: int | str
    # This field's state on this transaction: applied, conflict or basis_changed.
    field_state: str
    bound_records: tuple[DecidedRecord, ...]


@dataclass(frozen=True)
class ClassificationEvidence:
    """An active classification binding a record of one transaction (D-053)."""

    classification_id: str
    financial_type: str
    # The outcome on this transaction: applied, conflict, basis_changed or against_direction.
    state: str
    bound_records: tuple[DecidedRecord, ...]


@dataclass(frozen=True)
class CategorizationEvidence:
    """An active categorization binding a record of one transaction (D-063)."""

    categorization_id: str
    # The category by its name, which is unique and never changes, because its ID says where it
    # is stored.
    category: str
    # The outcome on this transaction: applied, conflict, basis_changed or not_spending.
    state: str
    bound_records: tuple[DecidedRecord, ...]


@dataclass(frozen=True)
class CategoryRuleEvidence:
    """An active category rule matching a transaction no person's categorization reaches
    (D-064)."""

    rule_id: str
    # What the rule says, by names, which are unique and never change.
    category: str
    description_contains: str
    financial_type: str | None
    from_date: str | None
    # Whether it reaches every account, rather than only this transaction's.
    every_account: bool
    # The rules' outcome on this transaction: applied or rule_conflict.
    state: str


@dataclass(frozen=True)
class HouseholdEvidence:
    """Who a transaction's effective amount belongs to, where an account's default reaches it
    (D-065)."""

    # A member's name, shared, or unattributed.
    kind: str
    # (member name, cents) in member order. Empty when unattributed.
    parts: tuple[tuple[str, int], ...]
    # Why it is unattributed, else None.
    reason: str | None


@dataclass(frozen=True)
class TransferEvidence:
    """An active transfer match binding a record of one transaction (D-054)."""

    match_id: str
    # This transaction's side: outflow or inflow.
    side: str
    # The match's outcome: applied, basis_changed, conflict, amounts_differ or type_differs.
    state: str
    bound_records: tuple[DecidedRecord, ...]
    counterpart_bound_records: tuple[DecidedRecord, ...]
    # The other side's transaction while the match applies, else None.
    counterpart_transaction_id: str | None


@dataclass(frozen=True)
class OneSidedTransferEvidence:
    """An active one-sided transfer binding a record of one transaction (D-055)."""

    one_sided_transfer_id: str
    # The counterpart by its name, which is unique, because account IDs are random and so
    # immaterial. Another counterpart is another statement.
    counterpart_account: str
    # The outcome: applied, basis_changed, conflict, type_differs, counterpart_found or
    # counterpart_covered.
    state: str
    bound_records: tuple[DecidedRecord, ...]


@dataclass(frozen=True)
class TransactionEvidence:
    """A logical transaction as it stands now, with every record supporting it.

    Its values are the primary source's (D-030). Corrections are kept apart from them.
    """

    transaction_id: str
    transaction_date: str | None
    posting_date: str | None
    amount_cents: int
    description: str | None
    external_id: str | None
    settlement_status: str
    # Document hash and row of the source supplying these values. None if not recorded.
    primary_source: tuple[str, int] | None
    records: tuple[RecordEvidence, ...]
    corrections: tuple[CorrectionEvidence, ...] = ()
    classifications: tuple[ClassificationEvidence, ...] = ()
    transfers: tuple[TransferEvidence, ...] = ()
    one_sided_transfers: tuple[OneSidedTransferEvidence, ...] = ()
    categorizations: tuple[CategorizationEvidence, ...] = ()
    category_rules: tuple[CategoryRuleEvidence, ...] = ()
    household: HouseholdEvidence | None = None


@dataclass(frozen=True)
class DeclaredCoverageEvidence:
    """Coverage a person declared for a document after import, which matching uses instead of the
    claim at import (D-051)."""

    coverage_kind: str
    coverage_start: str | None
    coverage_end: str | None
    date_basis: str | None


@dataclass(frozen=True)
class DocumentEvidence:
    content_sha256: str
    file_name: str
    layout_id: str
    parser_version: str
    generated_on: str | None
    coverage_kind: str
    coverage_start: str | None
    coverage_end: str | None
    date_basis: str | None
    coverage_evidence: str | None
    # What matching relies on, which can end earlier than the claim (D-027), from the declared
    # coverage when there is one (D-051).
    effective_end: str | None
    # Whether pending rows fall inside a complete claim. None without one.
    pending_covered: bool | None
    id_namespace: str | None
    id_guarantee: str
    declared: DeclaredCoverageEvidence | None = None


@dataclass(frozen=True)
class DecidedPair:
    """One stated pair of an active decision, as records on two sides."""

    decision_id: str
    # different_event or same_event, from version 3 (D-046).
    relation: str
    left: tuple[DecidedRecord, ...]
    right: tuple[DecidedRecord, ...]


@dataclass(frozen=True)
class ReviewEvidence:
    issue_id: str
    kind: str
    rule: str
    status: str
    reasons: tuple[str, ...]
    date_start: str | None
    date_end: str | None
    transactions: tuple[TransactionEvidence, ...]
    # Records with no transaction, which is what an unresolved item is about.
    unresolved: tuple[RecordEvidence, ...]
    documents: tuple[DocumentEvidence, ...]
    account_stale: bool
    account_id: str
    account_name: str
    # Active decisions with a side in this item (D-043).
    decided: tuple[DecidedPair, ...]

    @property
    def records(self) -> tuple[RecordEvidence, ...]:
        linked = (record for entry in self.transactions for record in entry.records)
        return (*linked, *self.unresolved)


@dataclass(frozen=True)
class MergeEvidence:
    """One transaction and every record supporting it, for separating it (D-047)."""

    transaction: TransactionEvidence
    documents: tuple[DocumentEvidence, ...]
    account_stale: bool
    account_id: str
    account_name: str
    # Active decisions with a side in this transaction.
    decided: tuple[DecidedPair, ...]


def review_revision(item: ReviewEvidence) -> str:
    """Identify the material evidence of an item (D-040).

    Equal evidence gives an equal token in any ledger and any import order, so a repeat
    import that changes nothing cannot change it. It detects change and proves nothing
    else, so a shortened digest is enough.
    """
    return f"r{REVISION_VERSION}-{_digest(item)}"


def transaction_revision(merge: MergeEvidence) -> str:
    """Identify one transaction's material evidence, under the rules of review_revision."""
    return f"t{TRANSACTION_REVISION_VERSION}-{_digest(merge)}"


def _digest(evidence) -> str:
    material = _without_immaterial(asdict(evidence))
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _without_immaterial(value):
    if isinstance(value, dict):
        return {
            key: _without_immaterial(entry)
            for key, entry in value.items()
            if key not in IMMATERIAL_FIELDS
            and not (key in OMITTED_WHILE_EMPTY and not entry)
        }
    if isinstance(value, (list, tuple)):
        return [_without_immaterial(entry) for entry in value]
    return value


@dataclass(frozen=True)
class AlikeRecord:
    """A record no active decision binds, alike in every parsed value to one that a decision
    binds in the same item."""

    record: RecordEvidence
    decided: RecordEvidence
    decision_ids: tuple[str, ...]


def alike_decided_records(item: ReviewEvidence) -> Iterator[AlikeRecord]:
    """Records in an item that look like a re-export of a decided record (D-048).

    Evidence only, as fingerprints are (D-009): it binds nothing. It reads nothing but the
    item's own evidence, which its revision already covers, so the revision is unchanged.
    Lazy, because a group of lookalikes holds quadratically many.
    """
    bound = defaultdict(set)
    for pair in item.decided:
        for record in (*pair.left, *pair.right):
            bound[_decided_key(record)].add(pair.decision_id)

    # Records of transactions only: an item holding one never holds an unresolved record.
    records = sorted((record for entry in item.transactions for record in entry.records),
                     key=_record_key)
    by_values = defaultdict(list)
    for record in records:
        if _record_key(record) in bound:
            by_values[_parsed_values(record)].append(record)
    return (
        AlikeRecord(record, other, tuple(sorted(bound[_record_key(other)])))
        for record in records if _record_key(record) not in bound
        for other in by_values.get(_parsed_values(record), ())
        if other.content_sha256 != record.content_sha256
    )


def _parsed_values(record: RecordEvidence) -> tuple:
    parsed = record.parsed
    return (parsed.transaction_date, parsed.posting_date, parsed.amount_cents, parsed.description,
            parsed.external_id, parsed.settlement_status)


def rows_sharing_a_document(item: ReviewEvidence) -> dict[str, tuple[int, ...]]:
    """Row numbers by document hash, for documents with several records in this item."""
    rows = {}
    for record in item.records:
        rows.setdefault(record.content_sha256, []).append(record.row)
    return {key: tuple(sorted(value)) for key, value in rows.items() if len(value) > 1}


def load_review_evidence(conn: sqlite3.Connection, issue_id: str) -> ReviewEvidence | None:
    issue = conn.execute(
        "SELECT kind, rule, status, evidence_json FROM review_issue WHERE id = ?", (issue_id,)
    ).fetchone()
    if issue is None:
        return None
    kind, rule, status, evidence = issue
    details = json.loads(evidence)

    linked, unresolved, documents, accounts = {}, [], set(), set()
    for row in conn.execute(_RECORDS, (issue_id,)):
        transaction_id, record, document, account_id = _record_of(row)
        if transaction_id is None:
            unresolved.append(record)
        else:
            linked.setdefault(transaction_id, []).append(record)
        documents.add(document)
        accounts.add(account_id)

    account_id = next(iter(accounts))
    corrections_by_transaction = _corrections_by_transaction(conn, account_id, linked)
    classifications_by_transaction = _classifications_by_transaction(conn, account_id, linked)
    held = {record.record_id for records in linked.values() for record in records}
    held.update(record.record_id for record in unresolved)
    return ReviewEvidence(
        issue_id,
        kind,
        rule,
        status,
        tuple(details.get("reasons", ())),
        details.get("date_start"),
        details.get("date_end"),
        _transactions(conn, issue_id, linked, corrections_by_transaction,
                      classifications_by_transaction, _transfers_by_transaction(conn, linked),
                      _one_sided_by_transaction(conn, linked),
                      _categorizations_by_transaction(conn, account_id, linked),
                      _category_rules_by_transaction(conn, linked),
                      _household_by_transaction(conn, linked)),
        tuple(sorted(unresolved, key=_record_key)),
        _documents(conn, account_id, documents),
        bool(accounts & set(stale_accounts(conn, DEFAULT_RULES))),
        account_id,
        conn.execute("SELECT display_name FROM account WHERE id = ?", (account_id,)).fetchone()[0],
        _decided_pairs(conn, account_id, held),
    )


def load_merge_evidence(conn: sqlite3.Connection, transaction_id: str) -> MergeEvidence | None:
    """Everything one transaction rests on. Amounts and descriptions are loaded, so only an
    explicit inspection or a decision on this transaction may call this."""
    linked, documents, accounts = [], set(), set()
    for row in conn.execute(_MERGE_RECORDS, (transaction_id,)):
        _, record, document, account_id = _record_of(row)
        linked.append(record)
        documents.add(document)
        accounts.add(account_id)
    if not linked:
        return None

    (account_id,) = accounts
    row = conn.execute(_TRANSACTION + " WHERE entry.id = ?", (transaction_id,)).fetchone()
    linked_by_transaction = {transaction_id: linked}
    return MergeEvidence(
        _transaction_entry(row, linked_by_transaction,
                           _corrections_by_transaction(conn, account_id, linked_by_transaction),
                           _classifications_by_transaction(conn, account_id,
                                                           linked_by_transaction),
                           _transfers_by_transaction(conn, linked_by_transaction),
                           _one_sided_by_transaction(conn, linked_by_transaction),
                           _categorizations_by_transaction(conn, account_id,
                                                           linked_by_transaction),
                           _category_rules_by_transaction(conn, linked_by_transaction),
                           _household_by_transaction(conn, linked_by_transaction)),
        _documents(conn, account_id, documents),
        account_id in stale_accounts(conn, DEFAULT_RULES, account_id),
        account_id,
        conn.execute("SELECT display_name FROM account WHERE id = ?", (account_id,)).fetchone()[0],
        _decided_pairs(conn, account_id, {record.record_id for record in linked}),
    )


def _record_of(row):
    """A record row of _RECORDS or _MERGE_RECORDS, as its transaction, record, document and
    account."""
    (transaction_id, link_rule, record_id, account_id, index, raw_json, file_name, digest,
     *rest) = row
    completed, *supplied, document_id = rest[20:]
    record = RecordEvidence(
        record_id, digest, file_name, index, tuple(json.loads(raw_json)),
        ParsedValues(*rest[:8]), link_rule,
        CompletedValues(*supplied) if completed else None,
    )
    return transaction_id, record, (document_id, digest, file_name, tuple(rest[8:20])), account_id


def _documents(conn, account_id, raw_documents) -> tuple["DocumentEvidence", ...]:
    """Each document once, by hash, with its declared coverage (D-051)."""
    declared = declared_coverage(conn, account_id)
    return tuple(
        _document(digest, file_name, values, declared.get(document_id))
        for document_id, digest, file_name, values in sorted(set(raw_documents), key=lambda raw: raw[1])
    )


def _decided_pairs(conn, account_id, held) -> tuple[DecidedPair, ...]:
    pairs = [
        DecidedPair(
            constraint.decision_id,
            constraint.relation,
            _decided_records(conn, constraint.left),
            _decided_records(conn, constraint.right),
        )
        for constraint in load_constraints(conn, account_id)
        if held.intersection((*constraint.left, *constraint.right))
    ]
    return tuple(sorted((_ordered_sides(pair) for pair in pairs), key=_pair_key))


def _decided_records(conn, record_ids) -> tuple[DecidedRecord, ...]:
    found = [
        DecidedRecord(
            *conn.execute(
                """SELECT document.content_sha256, document.file_name, record.record_index
                   FROM source_record record
                   JOIN source_document document ON document.id = record.source_document_id
                   WHERE record.id = ?""",
                (record_id,),
            ).fetchone()
        )
        for record_id in record_ids
    ]
    return tuple(sorted(found, key=_decided_key))


def _decided_key(record: DecidedRecord) -> tuple[str, int]:
    return record.content_sha256, record.row


def _ordered_sides(pair: DecidedPair) -> DecidedPair:
    """Which side is left depends on generated IDs, so a revision must not see it."""
    left, right = sorted((pair.left, pair.right), key=lambda side: list(map(_decided_key, side)))
    return DecidedPair(pair.decision_id, pair.relation, left, right)


def _pair_key(pair: DecidedPair):
    return [pair.relation, *(list(map(_decided_key, side)) for side in (pair.left, pair.right))]


def _record_key(record: RecordEvidence) -> tuple[str, int]:
    return record.content_sha256, record.row


_TRANSACTION = """
    SELECT entry.id, entry.transaction_date, entry.posting_date, entry.amount_cents,
           entry.description, entry.external_id, entry.settlement_status,
           entry.primary_source_record_id
    FROM ledger_transaction entry"""


def _transactions(conn, issue_id, linked, corrections_by_transaction,
                  classifications_by_transaction, transfers_by_transaction,
                  one_sided_by_transaction, categorizations_by_transaction,
                  category_rules_by_transaction,
                  household_by_transaction) -> tuple[TransactionEvidence, ...]:
    entries = [
        _transaction_entry(row, linked, corrections_by_transaction, classifications_by_transaction,
                           transfers_by_transaction, one_sided_by_transaction,
                           categorizations_by_transaction, category_rules_by_transaction,
                           household_by_transaction)
        for row in conn.execute(
            _TRANSACTION + """
            JOIN review_issue_subject subject ON subject.transaction_id = entry.id
            WHERE subject.review_issue_id = ?""",
            (issue_id,),
        )
    ]
    return tuple(sorted(entries, key=_transaction_order))


def _transaction_entry(row, linked, corrections_by_transaction, classifications_by_transaction,
                       transfers_by_transaction, one_sided_by_transaction,
                       categorizations_by_transaction, category_rules_by_transaction,
                       household_by_transaction) -> TransactionEvidence:
    transaction_id, *values, primary_id = row
    records = tuple(sorted(linked.get(transaction_id, ()), key=_record_key))
    primary = next(
        (_record_key(record) for record in records if record.record_id == primary_id), None
    )
    return TransactionEvidence(transaction_id, *values, primary, records,
                               corrections_by_transaction.get(transaction_id, ()),
                               classifications_by_transaction.get(transaction_id, ()),
                               transfers_by_transaction.get(transaction_id, ()),
                               one_sided_by_transaction.get(transaction_id, ()),
                               categorizations_by_transaction.get(transaction_id, ()),
                               category_rules_by_transaction.get(transaction_id, ()),
                               household_by_transaction.get(transaction_id))


def _household_by_transaction(conn, linked) -> dict[str, HouseholdEvidence]:
    """The attribution of each transaction an account's default reaches."""
    household = load_household(conn)
    if not household.defaults:
        return {}
    return {
        entry.transaction_id: HouseholdEvidence(
            entry.attribution.kind,
            tuple((household.name_of(member_id), cents)
                  for member_id, cents in entry.attribution.parts),
            entry.attribution.reason)
        for entry in attributed_transactions(conn, household, transaction_ids=list(linked))
        if entry.account_id in household.defaults
    }


def _corrections_by_transaction(conn, account_id, linked) -> dict[str, tuple]:
    """Active corrections binding each transaction's records, with the field's state there."""
    active_corrections = load_active_corrections(conn, account_id)
    if not active_corrections:
        return {}
    field_state_by_transaction_and_field = {
        (transaction_id, field): state
        for transaction_id, field, state in conn.execute(
            """SELECT fix.transaction_id, fix.field, fix.state FROM transaction_correction fix
               JOIN ledger_transaction entry ON entry.id = fix.transaction_id
               WHERE entry.account_id = ?""",
            (account_id,),
        )
    }
    found = {}
    for transaction_id, records in linked.items():
        record_ids = {record.record_id for record in records}
        touching = [
            CorrectionEvidence(
                correction.correction_id, correction.field, correction.corrected_value,
                field_state_by_transaction_and_field[transaction_id, correction.field],
                _decided_records(conn, correction.bound_record_ids),
            )
            for correction in active_corrections if correction.bound_record_ids & record_ids
        ]
        if touching:
            found[transaction_id] = tuple(sorted(touching, key=_correction_order))
    return found


def _classifications_by_transaction(conn, account_id, linked) -> dict[str, tuple]:
    """Active classifications binding each transaction's records, with the outcome there."""
    active_classifications = load_active_classifications(conn, account_id)
    if not active_classifications:
        return {}
    state_by_transaction = dict(conn.execute(
        """SELECT kind.transaction_id, kind.state FROM transaction_classification kind
           JOIN ledger_transaction entry ON entry.id = kind.transaction_id
           WHERE entry.account_id = ?""",
        (account_id,),
    ))
    found = {}
    for transaction_id, records in linked.items():
        record_ids = {record.record_id for record in records}
        touching = [
            ClassificationEvidence(
                classification.correction_id, classification.corrected_value,
                state_by_transaction[transaction_id],
                _decided_records(conn, classification.bound_record_ids),
            )
            for classification in active_classifications
            if classification.bound_record_ids & record_ids
        ]
        if touching:
            found[transaction_id] = tuple(sorted(
                touching, key=lambda classification: (
                    classification.financial_type,
                    [_decided_key(record) for record in classification.bound_records],
                ),
            ))
    return found


def _categorizations_by_transaction(conn, account_id, linked) -> dict[str, tuple]:
    """Active categorizations binding each transaction's records, with the outcome there."""
    active_categorizations = load_active_categorizations(conn, account_id)
    if not active_categorizations:
        return {}
    state_by_transaction = dict(conn.execute(
        """SELECT derived.transaction_id, derived.state FROM transaction_category derived
           JOIN ledger_transaction entry ON entry.id = derived.transaction_id
           WHERE entry.account_id = ?""",
        (account_id,),
    ))
    name_by_category = dict(conn.execute("SELECT id, name FROM category"))
    found = {}
    for transaction_id, records in linked.items():
        record_ids = {record.record_id for record in records}
        touching = [
            CategorizationEvidence(
                categorization.correction_id, name_by_category[categorization.corrected_value],
                state_by_transaction[transaction_id],
                _decided_records(conn, categorization.bound_record_ids),
            )
            for categorization in active_categorizations
            if categorization.bound_record_ids & record_ids
        ]
        if touching:
            found[transaction_id] = tuple(sorted(
                touching, key=lambda categorization: (
                    categorization.category,
                    [_decided_key(record) for record in categorization.bound_records],
                ),
            ))
    return found


def _category_rules_by_transaction(conn, linked) -> dict[str, tuple]:
    """The active rules matching each transaction a rule's outcome reaches, with that outcome."""
    state_by_transaction = dict(conn.execute(
        """SELECT transaction_id, state FROM transaction_rule_category
           WHERE transaction_id IN (SELECT value FROM json_each(?))""",
        (json.dumps(sorted(linked)),),
    ))
    if not state_by_transaction:
        return {}
    rules = load_active_rules(conn)
    rule_by_id = {rule.rule_id: rule for rule in rules}
    name_by_category = dict(conn.execute("SELECT id, name FROM category"))
    matched = matching_rules(load_spending_facts(conn, state_by_transaction), rules)
    return {
        transaction_id: tuple(sorted(
            (CategoryRuleEvidence(
                rule_id, name_by_category[rule_by_id[rule_id].definition.category_id],
                rule_by_id[rule_id].definition.description_contains,
                rule_by_id[rule_id].definition.financial_type,
                rule_by_id[rule_id].definition.from_date,
                rule_by_id[rule_id].definition.account_id is None, state)
             for rule_id in matched[transaction_id]),
            key=lambda rule: (rule.category, rule.description_contains, rule.financial_type or "",
                              rule.from_date or "", rule.every_account),
        ))
        for transaction_id, state in state_by_transaction.items()
    }


def _transfers_by_transaction(conn, linked) -> dict[str, tuple]:
    """Active transfer matches binding each transaction's records, with their outcome."""
    transaction_by_record_id = {
        record.record_id: transaction_id
        for transaction_id, records in linked.items() for record in records
    }
    record_ids_by_match_and_side = defaultdict(set)
    touched_matches = set()
    for match_id, side, record_id in conn.execute(
        """SELECT bound.match_id, bound.side, bound.source_record_id
           FROM transfer_match_record bound
           WHERE bound.match_id IN (
                   SELECT mine.match_id FROM transfer_match_record mine
                   JOIN transaction_source link ON link.source_record_id = mine.source_record_id
                   WHERE link.transaction_id IN (SELECT value FROM json_each(?)))
             AND NOT EXISTS (SELECT 1 FROM transfer_match_event undone
                             WHERE undone.match_id = bound.match_id AND undone.event = 'undone')""",
        (json.dumps(sorted(linked)),),
    ):
        record_ids_by_match_and_side[match_id, side].add(record_id)
        if record_id in transaction_by_record_id:
            touched_matches.add((match_id, side, transaction_by_record_id[record_id]))
    if not touched_matches:
        return {}
    effect_by_match = {
        match_id: (state, outflow, inflow)
        for match_id, state, outflow, inflow in conn.execute(
            """SELECT match_id, state, outflow_transaction_id, inflow_transaction_id
               FROM transfer_match_effect"""
        )
    }
    found = defaultdict(list)
    for match_id, side, transaction_id in touched_matches:
        state, outflow, inflow = effect_by_match[match_id]
        other = INFLOW if side == OUTFLOW else OUTFLOW
        found[transaction_id].append(TransferEvidence(
            match_id, side, state,
            _decided_records(conn, record_ids_by_match_and_side[match_id, side]),
            _decided_records(conn, record_ids_by_match_and_side[match_id, other]),
            inflow if side == OUTFLOW else outflow,
        ))
    return {
        transaction_id: tuple(sorted(transfers, key=lambda transfer: (
            transfer.side, [_decided_key(record) for record in transfer.bound_records],
            [_decided_key(record) for record in transfer.counterpart_bound_records],
        )))
        for transaction_id, transfers in found.items()
    }


def _one_sided_by_transaction(conn, linked) -> dict[str, tuple]:
    """Active one-sided transfers binding each transaction's records, with their outcome."""
    transaction_by_record_id = {
        record.record_id: transaction_id
        for transaction_id, records in linked.items() for record in records
    }
    counterpart_by_statement, record_ids_by_statement = {}, defaultdict(set)
    for statement_id, counterpart, record_id in conn.execute(
        """SELECT statement.id, counterpart.display_name, bound.source_record_id
           FROM one_sided_transfer statement
           JOIN account counterpart ON counterpart.id = statement.counterpart_account_id
           JOIN one_sided_transfer_record bound ON bound.one_sided_transfer_id = statement.id
           WHERE statement.id IN (
                   SELECT mine.one_sided_transfer_id FROM one_sided_transfer_record mine
                   JOIN transaction_source link ON link.source_record_id = mine.source_record_id
                   WHERE link.transaction_id IN (SELECT value FROM json_each(?)))
             AND NOT EXISTS (SELECT 1 FROM one_sided_transfer_event undone
                             WHERE undone.one_sided_transfer_id = statement.id
                               AND undone.event = 'undone')""",
        (json.dumps(sorted(linked)),),
    ):
        counterpart_by_statement[statement_id] = counterpart
        record_ids_by_statement[statement_id].add(record_id)
    if not counterpart_by_statement:
        return {}
    state_by_statement = dict(conn.execute(
        "SELECT one_sided_transfer_id, state FROM one_sided_transfer_effect"))
    found = defaultdict(list)
    for statement_id, record_ids in record_ids_by_statement.items():
        evidence = OneSidedTransferEvidence(
            statement_id, counterpart_by_statement[statement_id], state_by_statement[statement_id],
            _decided_records(conn, record_ids),
        )
        for transaction_id in {transaction_by_record_id[record] for record in record_ids
                               if record in transaction_by_record_id}:
            found[transaction_id].append(evidence)
    return {
        transaction_id: tuple(sorted(statements, key=lambda statement: (
            statement.counterpart_account,
            [_decided_key(record) for record in statement.bound_records],
        )))
        for transaction_id, statements in found.items()
    }


def _correction_order(correction: CorrectionEvidence):
    """Never by generated ID, so that a revision cannot depend on it."""
    return (correction.field, repr(correction.corrected_value),
            [_decided_key(record) for record in correction.bound_records])


def _transaction_order(entry: TransactionEvidence):
    """By date, then by source, so that the order never depends on generated IDs."""
    day = entry.transaction_date or entry.posting_date
    return day, [_record_key(record) for record in entry.records]


def _document(digest, file_name, values, declaration) -> DocumentEvidence:
    (layout_id, generated_on, parser_version, namespace, guarantee, pending_transaction,
     pending_posting, kind, start, end, basis, evidence) = values
    # The claim at import stays as stored, and matching uses the declaration in effect (D-051).
    used = (kind, end, basis, evidence)
    if declaration is not None:
        used = (declaration.kind, declaration.end, declaration.date_basis, declaration.evidence)
    used_kind, used_end, used_basis, used_evidence = used
    complete = used_kind == "complete"
    pending = pending_transaction if used_basis == "transaction" else pending_posting
    return DocumentEvidence(
        digest, file_name, layout_id, parser_version, generated_on, kind, start, end, basis,
        evidence,
        effective_end(used_end, used_evidence, generated_on) if complete else None,
        bool(pending) if complete else None,
        namespace,
        guarantee,
        None if declaration is None else DeclaredCoverageEvidence(
            declaration.kind, declaration.start, declaration.end, declaration.date_basis
        ),
    )


_RECORD_FIELDS = """
    link.link_rule, record.id, record.account_id,
    record.record_index, record.raw_json, document.file_name, document.content_sha256,
    parse.status, parse.reason_code, parse.transaction_date, parse.posting_date,
    parse.amount_cents, parse.description, parse.external_id, parse.settlement_status,
    document.layout_id, document.generated_on, meaning.parser_version,
    meaning.external_id_namespace, meaning.external_id_guarantee,
    meaning.pending_in_transaction_basis, meaning.pending_in_posting_basis,
    coverage.coverage_kind, coverage.coverage_start, coverage.coverage_end,
    coverage.date_basis, coverage.evidence,
    completion.id IS NOT NULL, completion.completed_amount_cents,
    completion.completed_transaction_date, completion.completed_posting_date,
    completion.completed_description, document.id"""

# What a record row needs once its source_record is joined.
_RECORD_DETAILS = """
    JOIN source_document document ON document.id = record.source_document_id
    JOIN document_interpretation meaning ON meaning.source_document_id = document.id
    JOIN record_parse parse ON parse.source_record_id = record.id
                           AND parse.parser_version = meaning.parser_version
    JOIN document_coverage coverage ON coverage.source_document_id = document.id
                                   AND coverage.account_id = record.account_id
    LEFT JOIN record_resolution completion
        ON completion.source_record_id = record.id AND completion.kind = 'completed'
       AND NOT EXISTS (SELECT 1 FROM record_resolution_event undone
                       WHERE undone.resolution_id = completion.id AND undone.event = 'undone')"""

_MERGE_RECORDS = f"""
    SELECT link.transaction_id, {_RECORD_FIELDS}
    FROM transaction_source link
    JOIN source_record record ON record.id = link.source_record_id
    {_RECORD_DETAILS}
    WHERE link.transaction_id = ?"""

# A transaction subject brings every record it holds, and a record subject brings itself.
_RECORDS = f"""
    SELECT subject.transaction_id, {_RECORD_FIELDS}
    FROM review_issue_subject subject
    LEFT JOIN transaction_source link ON link.transaction_id = subject.transaction_id
    JOIN source_record record
        ON record.id = COALESCE(link.source_record_id, subject.source_record_id)
    {_RECORD_DETAILS}
    WHERE subject.review_issue_id = ?"""
