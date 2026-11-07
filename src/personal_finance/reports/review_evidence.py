"""What one review item rests on, for explicit inspection. See decisions.md D-037 and D-040.

Everything here reads the ledger and nothing writes to it. Amounts and descriptions are
loaded because a person asked to see this one item, so nothing routine may call this.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from personal_finance.ingest.coverage import effective_end
from personal_finance.reconcile.apply import load_constraints, stale_accounts
from personal_finance.reconcile.rules import DEFAULT_RULES

# Bump whenever the material evidence changes, so an old token can never appear current.
REVISION_VERSION = 2

# Fields left out of a revision. Random IDs and names say where evidence is stored or how
# it is labelled, not what it says. Records are identified by document hash and row
# instead. A stale account is a warning about the rules, and any effect of reconciling
# reaches the token through the evidence itself.
IMMATERIAL_FIELDS = frozenset(
    {"issue_id", "transaction_id", "record_id", "file_name", "account_stale", "account_id",
     "account_name", "decision_id"}
)


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
class RecordEvidence:
    record_id: str
    content_sha256: str
    file_name: str
    row: int
    cells: tuple[str, ...]
    parsed: ParsedValues
    link_rule: str | None


@dataclass(frozen=True)
class TransactionEvidence:
    """A logical transaction as it stands now, with every record supporting it."""

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
    # What matching relies on, which can end earlier than the claim (D-027).
    effective_end: str | None
    # Whether pending rows fall inside a complete claim. None without one.
    pending_covered: bool | None
    id_namespace: str | None
    id_guarantee: str


@dataclass(frozen=True)
class DecidedRecord:
    content_sha256: str
    file_name: str
    row: int


@dataclass(frozen=True)
class DecidedPair:
    """One stated pair of an active decision, as records on two sides."""

    decision_id: str
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


def review_revision(item: ReviewEvidence) -> str:
    """Identify the material evidence of an item (D-040).

    Equal evidence gives an equal token in any ledger and any import order, so a repeat
    import that changes nothing cannot change it. It detects change and proves nothing
    else, so a shortened digest is enough.
    """
    material = _without_immaterial(asdict(item))
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return f"r{REVISION_VERSION}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _without_immaterial(value):
    if isinstance(value, dict):
        return {
            key: _without_immaterial(entry)
            for key, entry in value.items()
            if key not in IMMATERIAL_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_without_immaterial(entry) for entry in value]
    return value


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

    linked, unresolved, documents, accounts = {}, [], {}, set()
    for row in conn.execute(_RECORDS, (issue_id,)):
        (transaction_id, link_rule, record_id, account_id, index, raw_json, file_name, digest,
         *rest) = row
        record = RecordEvidence(
            record_id, digest, file_name, index, tuple(json.loads(raw_json)),
            ParsedValues(*rest[:8]), link_rule,
        )
        if transaction_id is None:
            unresolved.append(record)
        else:
            linked.setdefault(transaction_id, []).append(record)
        documents[digest] = _document(digest, file_name, rest[8:])
        accounts.add(account_id)

    account_id = next(iter(accounts))
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
        _transactions(conn, issue_id, linked),
        tuple(sorted(unresolved, key=_record_key)),
        tuple(documents[digest] for digest in sorted(documents)),
        bool(accounts & set(stale_accounts(conn, DEFAULT_RULES))),
        account_id,
        conn.execute("SELECT display_name FROM account WHERE id = ?", (account_id,)).fetchone()[0],
        _decided_pairs(conn, account_id, held),
    )


def _decided_pairs(conn, account_id, held) -> tuple[DecidedPair, ...]:
    pairs = [
        DecidedPair(
            constraint.decision_id,
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
    return DecidedPair(pair.decision_id, left, right)


def _pair_key(pair: DecidedPair):
    return [list(map(_decided_key, side)) for side in (pair.left, pair.right)]


def _record_key(record: RecordEvidence) -> tuple[str, int]:
    return record.content_sha256, record.row


def _transactions(conn, issue_id, linked) -> tuple[TransactionEvidence, ...]:
    entries = []
    for transaction_id, *values, primary_id in conn.execute(
        """SELECT entry.id, entry.transaction_date, entry.posting_date, entry.amount_cents,
                  entry.description, entry.external_id, entry.settlement_status,
                  entry.primary_source_record_id
           FROM review_issue_subject subject
           JOIN ledger_transaction entry ON entry.id = subject.transaction_id
           WHERE subject.review_issue_id = ?""",
        (issue_id,),
    ):
        records = tuple(sorted(linked.get(transaction_id, ()), key=_record_key))
        primary = next(
            (_record_key(record) for record in records if record.record_id == primary_id), None
        )
        entries.append(TransactionEvidence(transaction_id, *values, primary, records))
    return tuple(sorted(entries, key=_transaction_order))


def _transaction_order(entry: TransactionEvidence):
    """By date, then by source, so that the order never depends on generated IDs."""
    day = entry.transaction_date or entry.posting_date
    return day, [_record_key(record) for record in entry.records]


def _document(digest, file_name, values) -> DocumentEvidence:
    (layout_id, generated_on, parser_version, namespace, guarantee, pending_transaction,
     pending_posting, kind, start, end, basis, evidence) = values
    complete = kind == "complete"
    pending = pending_transaction if basis == "transaction" else pending_posting
    return DocumentEvidence(
        digest, file_name, layout_id, parser_version, generated_on, kind, start, end, basis,
        evidence,
        effective_end(end, evidence, generated_on) if complete else None,
        bool(pending) if complete else None,
        namespace,
        guarantee,
    )


# A transaction subject brings every record it holds, and a record subject brings itself.
_RECORDS = """
    SELECT subject.transaction_id, link.link_rule, record.id, record.account_id,
           record.record_index, record.raw_json, document.file_name, document.content_sha256,
           parse.status, parse.reason_code, parse.transaction_date, parse.posting_date,
           parse.amount_cents, parse.description, parse.external_id, parse.settlement_status,
           document.layout_id, document.generated_on, meaning.parser_version,
           meaning.external_id_namespace, meaning.external_id_guarantee,
           meaning.pending_in_transaction_basis, meaning.pending_in_posting_basis,
           coverage.coverage_kind, coverage.coverage_start, coverage.coverage_end,
           coverage.date_basis, coverage.evidence
    FROM review_issue_subject subject
    LEFT JOIN transaction_source link ON link.transaction_id = subject.transaction_id
    JOIN source_record record
        ON record.id = COALESCE(link.source_record_id, subject.source_record_id)
    JOIN source_document document ON document.id = record.source_document_id
    JOIN document_interpretation meaning ON meaning.source_document_id = document.id
    JOIN record_parse parse ON parse.source_record_id = record.id
                           AND parse.parser_version = meaning.parser_version
    JOIN document_coverage coverage ON coverage.source_document_id = document.id
                                   AND coverage.account_id = record.account_id
    WHERE subject.review_issue_id = ?"""
