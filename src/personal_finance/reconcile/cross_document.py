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
from datetime import date
from itertools import combinations

from personal_finance.ingest.coverage import effective_end
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reconcile.similarity import block_key, fold, parse_description, similar

LINK_NEW = "new_record"
LINK_EXTERNAL_ID = "reliable_external_id"
LINK_EXACT = "exact_coverage_pair"

RULE_EXTERNAL_ID = "cross_document_external_id"
RULE_CANDIDATES = "cross_document_candidates"

GUARANTEE_NONE = "none"
GUARANTEE_STABLE_UNIQUE = "stable_unique"

_STATUS_RANK = {"posted": 0, "unknown": 1, "pending": 2}

# How the source supplying a transaction's displayed values is chosen, in order (D-030).
PRIMARY_CRITERIA = (
    "settlement status (posted, then unknown, then pending)",
    "more dates present",
    "has a description",
    "lowest document hash, then row number",
)


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
    id_less = [row for row in ordered if not _has_reliable_id(row, by_id)]
    exact_merges, exact_reasons = _match_exact(id_less, by_id, unresolved, rules)

    merged = {row.id for merge in id_merges + exact_merges for row in merge}
    units = [(merge, LINK_EXTERNAL_ID) for merge in id_merges]
    units += [(merge, LINK_EXACT) for merge in exact_merges]
    units += [([row], LINK_NEW) for row in ordered if row.id not in merged]

    groups = tuple(_group(rows, rule, by_id) for rows, rule in units)
    candidates = [_Unit.of(rows, by_id) for rows, _ in units]
    joined, steps = _link_candidates(candidates, rules)
    items = [_id_item(conflict) for conflict in id_conflicts]
    items += _candidate_items(candidates, joined, exact_reasons, rules)
    return Derivation(groups, tuple(items), separation, steps)


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


def _match_exact(rows, documents, unresolved, rules):
    """Pair identical rows one-for-one where coverage justifies it (D-006, D-007).

    Rows in one bucket are interchangeable, so the k-th row of each document pairs
    with the k-th of the others. A document therefore contributes at most one row to
    a transaction, and two rows against three gives exactly three transactions.
    """
    buckets = defaultdict(lambda: defaultdict(list))
    for row in rows:
        text = fold(row.description)
        if text:
            key = (row.transaction_date, row.posting_date, row.amount_cents, text, _status_class(row))
            buckets[key][row.document_id].append(row)

    blockers = _index_unresolved(unresolved)
    merges, reasons = [], defaultdict(set)
    for key, by_document in buckets.items():
        if len(by_document) < 2:
            continue

        names = sorted(by_document, key=lambda name: documents[name].content_sha256)
        trusted = set()
        for position, left in enumerate(names):
            for right in names[position + 1 :]:
                gap = _coverage_gap(documents[left], documents[right], key, blockers, rules)
                if gap is None:
                    trusted.add((left, right))
                    continue
                for row in by_document[left] + by_document[right]:
                    reasons[row.id].add(gap)

        for slot in range(max(len(members) for members in by_document.values())):
            present = [name for name in names if slot < len(by_document[name])]
            joined = _DisjointSet(len(present))
            for one, left in enumerate(present):
                for other in range(one + 1, len(present)):
                    if (left, present[other]) in trusted:
                        joined.union(one, other)
            for component in joined.components():
                if len(component) > 1:
                    merges.append([by_document[present[index]][slot] for index in component])
    return merges, reasons


def _coverage_gap(left, right, key, blockers, rules) -> str | None:
    """Why two documents cannot support a confident match on this key, if they cannot."""
    transaction_date, posting_date, amount, text, status = key
    if "unknown" in (left.coverage_kind, right.coverage_kind):
        return "coverage_unknown"
    if left.coverage_kind != "complete" or right.coverage_kind != "complete":
        return "coverage_partial"
    if left.date_basis != right.date_basis:
        return "different_basis"

    day = transaction_date if left.date_basis == "transaction" else posting_date
    if day is None or not (_claims(left, day) and _claims(right, day)):
        return "date_outside_coverage"
    if status == "pending" and not (left.pending_covered and right.pending_covered):
        return "pending_not_covered"

    last_safe = min(_effective_end(left), _effective_end(right))
    if day > last_safe:
        return "boundary_date"
    if max(left.coverage_start, right.coverage_start) == last_safe:
        return "single_day_overlap"

    dates = {value for value in (transaction_date, posting_date) if value}
    for document in (left, right):
        if _unresolved_could_affect(document.id, dates, amount, text, blockers, rules):
            return "unresolved_row"
    return None


def _claims(document: Document, day: str) -> bool:
    return document.coverage_start <= day <= document.coverage_end


def _effective_end(document: Document) -> str:
    return effective_end(document.coverage_end, document.evidence, document.generated_on)


def _index_unresolved(unresolved):
    """Map document to dated rows, with None holding rows of unknown date."""
    index = defaultdict(lambda: defaultdict(list))
    for row in unresolved:
        dates = {value for value in (row.transaction_date, row.posting_date) if value}
        for value in dates or {None}:
            index[row.document_id][value].append(row)
    return index


def _unresolved_could_affect(document_id, dates, amount, text, blockers, rules) -> bool:
    """An unresolved row matters only if nothing known about it rules it out (D-024)."""
    by_date = blockers.get(document_id)
    if not by_date:
        return False

    description = parse_description(text, rules)
    for value in (None, *dates):
        for row in by_date.get(value, ()):
            if row.amount_cents is not None and row.amount_cents != amount:
                continue
            if not fold(row.description):
                return True
            if similar(parse_description(row.description, rules), description, rules):
                return True
    return False


@dataclass(frozen=True)
class _Unit:
    """One logical transaction, as candidate discovery sees it."""

    rows: tuple[Record, ...]
    amount_cents: int
    days: tuple[int, ...]
    descriptions: frozenset[str]
    # Units in one lane can never be candidates for each other.
    lane: tuple[frozenset[str], frozenset[str]]

    @classmethod
    def of(cls, rows, documents):
        days = {date.fromisoformat(value).toordinal() for value in _dates_of(rows)}
        unique_namespaces = {
            documents[row.document_id].id_namespace
            for row in rows
            if _has_reliable_id(row, documents)
            and documents[row.document_id].id_guarantee == GUARANTEE_STABLE_UNIQUE
        }
        return cls(
            tuple(rows),
            rows[0].amount_cents,
            tuple(sorted(days)),
            frozenset(text for text in map(fold, (row.description for row in rows)) if text),
            (frozenset(row.document_id for row in rows), frozenset(unique_namespaces)),
        )


def _lanes_can_link(left, right) -> bool:
    """Not if they share a document, or IDs that prove the rows distinct (D-026)."""
    return left[0].isdisjoint(right[0]) and left[1].isdisjoint(right[1])


def _link_candidates(units, rules):
    """Join units linked by amount, date window and description, without listing pairs.

    Units are bucketed by amount, then by description. Within a lane rows are sorted
    by date, so every row within the window of a given row is one contiguous range,
    and that range only needs joining once. No pair is ever stored. Cost grows with
    rows per lane, lanes that overlap and the distinct descriptions sharing a block.
    """
    by_amount = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for index, unit in enumerate(units):
        for text in unit.descriptions:
            lanes = by_amount[unit.amount_cents][text]
            lanes[unit.lane].update((day, index) for day in unit.days)

    joined = _DisjointSet(len(units))
    steps = 0
    for descriptions in by_amount.values():
        sorted_lanes = {
            text: {lane: sorted(entries) for lane, entries in lanes.items()}
            for text, lanes in descriptions.items()
        }
        for text, lanes in sorted_lanes.items():
            for left, right in combinations(lanes, 2):
                if _lanes_can_link(left, right):
                    steps += _join_lanes(lanes[left], lanes[right], rules, joined)
        for one, other in _similar_descriptions(sorted_lanes, rules):
            for left, left_entries in sorted_lanes[one].items():
                for right, right_entries in sorted_lanes[other].items():
                    if _lanes_can_link(left, right):
                        steps += _join_lanes(left_entries, right_entries, rules, joined)
    return joined, steps


def _similar_descriptions(texts, rules):
    """Pairs of different descriptions that are similar, compared only within a block."""
    blocks = defaultdict(list)
    for text in texts:
        parsed = parse_description(text, rules)
        key = block_key(parsed, rules)
        if key is not None:
            blocks[key].append(parsed)
    for members in blocks.values():
        for left, right in combinations(members, 2):
            if similar(left, right, rules):
                yield left.folded, right.folded


def _join_lanes(left, right, rules, joined) -> int:
    window = rules.date_window_days
    low = high = 0
    linked_through = 0
    steps = 0
    for day, unit in left:
        steps += 1
        while low < len(right) and right[low][0] < day - window:
            low += 1
        high = max(high, low)
        while high < len(right) and right[high][0] <= day + window:
            high += 1
        if low == high:
            continue
        joined.union(unit, right[low][1])
        for position in range(max(low, linked_through), high - 1):
            joined.union(right[position][1], right[position + 1][1])
            steps += 1
        linked_through = max(linked_through, high - 1)
    return steps


def _candidate_items(units, joined, exact_reasons, rules) -> list[ReviewItem]:
    items = []
    for component in joined.components():
        if len(component) < 2:
            continue
        members = [units[index] for index in component]
        for part in _bounded_parts(members, rules):
            rows = [row for unit in part for row in unit.rows]
            reasons = {reason for row in rows for reason in exact_reasons.get(row.id, ())}
            items.append(
                _item(
                    RULE_CANDIDATES,
                    [unit.rows for unit in part],
                    reasons or {"similar_description"},
                    _dates_of(rows),
                )
            )
    return items


def _bounded_parts(members, rules) -> list[list[_Unit]]:
    """Divide a long run into calendar blocks without separating any linked pair (D-031).

    Each block is extended by the date window. If two units are linked, the earlier
    date falls in some block and the later date within that block's extension, so
    both appear in that block's part.
    """
    span = rules.max_group_span_days
    first = min(unit.days[0] for unit in members)
    last = max(unit.days[-1] for unit in members)
    if last - first + 1 <= span:
        return [members]

    parts = []
    for block in range(first // span, last // span + 1):
        start = block * span
        end = start + span - 1 + rules.date_window_days
        part = [unit for unit in members if any(start <= day <= end for day in unit.days)]
        if any(_lanes_can_link(a.lane, b.lane) for a, b in _lane_pairs(part)):
            parts.append(part)
    return _without_contained(parts)


def _lane_pairs(part):
    """One representative pair for each pair of lanes in the part."""
    by_lane = {unit.lane: unit for unit in part}
    return combinations(by_lane.values(), 2)


def _without_contained(parts):
    keys = [frozenset(id(unit) for unit in part) for part in parts]
    return [
        part
        for position, part in enumerate(parts)
        if not any(
            keys[position] < other or (keys[position] == other and earlier < position)
            for earlier, other in enumerate(keys)
        )
    ]


def _group(rows, rule, documents) -> TransactionGroup:
    primary = min(rows, key=lambda row: _primary_rank(row, documents))
    return TransactionGroup(tuple(sorted(row.id for row in rows)), rule, primary.id)


def _primary_rank(row: Record, documents):
    return primary_rank(
        row.settlement_status,
        row.transaction_date,
        row.posting_date,
        row.description,
        documents[row.document_id].content_sha256,
        row.row_index,
    )


def primary_rank(status, transaction_date, posting_date, description, content_sha256, row_index):
    """Order sources for display, lowest first, one term per entry of PRIMARY_CRITERIA.

    Depends only on the record itself, so import order cannot affect the choice.
    """
    dates = (transaction_date is not None) + (posting_date is not None)
    return (_STATUS_RANK[status], -dates, not description, (content_sha256, row_index))


def deciding_criterion(chosen, other) -> str:
    """The first criterion on which a chosen source beat another."""
    return next(
        text for mine, theirs, text in zip(chosen, other, PRIMARY_CRITERIA) if mine != theirs
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
