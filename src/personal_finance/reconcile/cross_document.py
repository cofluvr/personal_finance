"""Derives one account's logical transactions from its stored evidence.

derive() is a pure function: it reads no database and depends only on the set of
documents and the rules, ordered by content hash and row number, never by import
order or generated ID. Import order therefore cannot change the outcome. Applying
the result is a separate step. Rules are in decisions.md D-006, D-007 and D-026 to
D-031.

Reliable-ID matching and ID-less matching run on separate rows and neither one
feeds the other. Description similarity only ever creates review items.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.rules import MatchingRules

LINK_NEW = "new_record"
LINK_EXTERNAL_ID = "reliable_external_id"

RULE_EXTERNAL_ID = "cross_document_external_id"

GUARANTEE_NONE = "none"
GUARANTEE_STABLE_UNIQUE = "stable_unique"

_STATUS_RANK = {"posted": 0, "unknown": 1, "pending": 2}


@dataclass(frozen=True)
class Document:
    id: str
    content_sha256: str
    coverage_kind: str = "unknown"
    coverage_start: str | None = None
    coverage_end: str | None = None
    date_basis: str | None = None
    evidence: str | None = None
    generated_on: str | None = None
    id_namespace: str | None = None
    id_guarantee: str = GUARANTEE_NONE
    # Whether pending rows fall inside this document's coverage claim.
    pending_covered: bool = False


@dataclass(frozen=True)
class Record:
    id: str
    document_id: str
    row_index: int
    amount_cents: int
    transaction_date: str | None = None
    posting_date: str | None = None
    description: str | None = None
    external_id: str | None = None
    settlement_status: str = "unknown"


@dataclass(frozen=True)
class UnresolvedRecord:
    document_id: str
    amount_cents: int | None = None
    transaction_date: str | None = None
    posting_date: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TransactionGroup:
    """The records that form one logical transaction."""

    record_ids: tuple[str, ...]
    link_rule: str
    primary_record_id: str


@dataclass(frozen=True)
class ReviewItem:
    """Possible duplicates. Each member is the record IDs of one transaction."""

    rule: str
    members: tuple[tuple[str, ...], ...]
    reasons: tuple[str, ...]
    date_start: str
    date_end: str


@dataclass(frozen=True)
class Derivation:
    groups: tuple[TransactionGroup, ...]
    items: tuple[ReviewItem, ...]
    # Why a record was kept out of a match, for records with a recorded cause.
    separation_reasons: dict[str, str]
    # Work done finding candidates, so tests can measure it.
    candidate_steps: int = 0


class _DisjointSet:
    def __init__(self, size: int):
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        self._parent[self.find(left)] = self.find(right)

    def components(self) -> list[list[int]]:
        found = defaultdict(list)
        for item in range(len(self._parent)):
            found[self.find(item)].append(item)
        return list(found.values())


def derive(
    documents: list[Document],
    records: list[Record],
    unresolved: list[UnresolvedRecord],
    rules: MatchingRules,
) -> Derivation:
    by_id = {document.id: document for document in documents}
    ordered = sorted(records, key=lambda row: _record_key(row, by_id))

    id_merges, id_conflicts, separation = _match_reliable_ids(ordered, by_id)
    merged = {row.id for merge in id_merges for row in merge}
    units = [(merge, LINK_EXTERNAL_ID) for merge in id_merges]
    units += [([row], LINK_NEW) for row in ordered if row.id not in merged]

    groups = tuple(_group(rows, rule, by_id) for rows, rule in units)
    items = tuple(_id_item(conflict) for conflict in id_conflicts)
    return Derivation(groups, items, separation)


def _record_key(row: Record, documents) -> tuple[str, int]:
    return documents[row.document_id].content_sha256, row.row_index


def _has_reliable_id(row: Record, documents) -> bool:
    document = documents[row.document_id]
    return bool(
        row.external_id and document.id_namespace and document.id_guarantee != GUARANTEE_NONE
    )


def _match_reliable_ids(rows, documents):
    """Same ID in one namespace. Coverage and descriptions play no part here."""
    by_identifier = defaultdict(list)
    for row in rows:
        if _has_reliable_id(row, documents):
            by_identifier[documents[row.document_id].id_namespace, row.external_id].append(row)

    merges, conflicts, separation = [], [], {}
    for members in by_identifier.values():
        per_document = Counter(row.document_id for row in members)
        if len(per_document) < 2:
            continue

        units, reasons = [], set()
        for row in members:
            if per_document[row.document_id] > 1:
                units.append([row])
                separation[row.id] = "external_id_repeated"
                reasons.add("external_id_repeated")

        single = [row for row in members if per_document[row.document_id] == 1]
        for component in _compatible_components(single):
            if _all_compatible(component):
                units.append(component)
                continue
            units.extend([row] for row in component)
            separation.update((row.id, "external_id_conflict") for row in component)
            reasons.add("external_id_conflict")

        merges.extend(unit for unit in units if len(unit) > 1)
        if len(units) > 1:
            conflicts.append((units, reasons or {"external_id_conflict"}))
    return merges, conflicts, separation


def _compatible_components(rows):
    joined = _DisjointSet(len(rows))
    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if _compatible(rows[left], rows[right]):
                joined.union(left, right)
    return [[rows[index] for index in component] for component in joined.components()]


def _all_compatible(rows) -> bool:
    return all(
        _compatible(left, right)
        for position, left in enumerate(rows)
        for right in rows[position + 1 :]
    )


def _compatible(left: Record, right: Record) -> bool:
    """Compare material fields (D-006). A date missing from one side is no conflict."""
    return (
        left.amount_cents == right.amount_cents
        and _status_class(left) == _status_class(right)
        and _dates_agree(left.transaction_date, right.transaction_date)
        and _dates_agree(left.posting_date, right.posting_date)
    )


def _status_class(row: Record) -> str:
    """Unknown does not conflict with posted, for comparison only. It stays unknown."""
    return "pending" if row.settlement_status == "pending" else "not_pending"


def _dates_agree(left: str | None, right: str | None) -> bool:
    return left is None or right is None or left == right


def _group(rows, rule, documents) -> TransactionGroup:
    primary = min(rows, key=lambda row: _primary_rank(row, documents))
    return TransactionGroup(tuple(sorted(row.id for row in rows)), rule, primary.id)


def _primary_rank(row: Record, documents):
    """Depends only on the record itself, so import order cannot affect the choice."""
    dates = (row.transaction_date is not None) + (row.posting_date is not None)
    return (
        _STATUS_RANK[row.settlement_status],
        -dates,
        not _has_reliable_id(row, documents),
        not row.description,
        _record_key(row, documents),
    )


def _id_item(conflict) -> ReviewItem:
    units, reasons = conflict
    rows = [row for unit in units for row in unit]
    return _item(RULE_EXTERNAL_ID, units, reasons, _dates_of(rows))


def _item(rule, units, reasons, dates) -> ReviewItem:
    members = tuple(sorted(tuple(sorted(row.id for row in unit)) for unit in units))
    return ReviewItem(rule, members, tuple(sorted(reasons)), min(dates), max(dates))


def _dates_of(rows) -> list[str]:
    return [
        value for row in rows for value in (row.transaction_date, row.posting_date) if value
    ]
