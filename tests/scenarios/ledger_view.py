"""A view of a ledger that ignores generated IDs and display order (A16).

Two ledgers with equal views hold the same financial outcome, the same source
associations and the same review relationships.
"""

import json

from personal_finance.reconcile.apply import load_constraints
from personal_finance.reports.review_evidence import load_review_evidence, review_revision
from personal_finance.reports.totals import account_movement


def _record_keys(conn):
    return {
        record_id: (digest, index)
        for record_id, digest, index in conn.execute(
            """SELECT record.id, document.content_sha256, record.record_index
               FROM source_record record
               JOIN source_document document ON document.id = record.source_document_id"""
        )
    }


def active_constraints(conn):
    """Each active stated pair as its relation and two sets of stable record keys, in no
    particular order."""
    keys = _record_keys(conn)
    return sorted(
        [
            constraint.relation,
            constraint.confirmation,
            sorted(
                sorted(keys[record] for record in side)
                for side in (constraint.left, constraint.right)
            ),
        ]
        for (account,) in conn.execute("SELECT id FROM account").fetchall()
        for constraint in load_constraints(conn, account)
    )


def semantic_view(conn):
    keys = _record_keys(conn)
    members = {}
    rules = {}
    for transaction_id, record_id, rule in conn.execute(
        "SELECT transaction_id, source_record_id, link_rule FROM transaction_source"
    ):
        members.setdefault(transaction_id, set()).add(keys[record_id])
        rules[keys[record_id]] = rule
    members = {key: frozenset(value) for key, value in members.items()}

    transactions = frozenset(
        (members[row[0]], keys[row[1]], *row[2:])
        for row in conn.execute(
            """SELECT id, primary_source_record_id, external_id, transaction_date,
                      posting_date, amount_cents, description, settlement_status
               FROM ledger_transaction"""
        )
    )

    issues = {}
    for issue, kind, rule, status, evidence, transaction_id, record_id in conn.execute(
        """SELECT issue.id, kind, rule, status, evidence_json, subject.transaction_id,
                  subject.source_record_id
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id"""
    ):
        reasons = tuple(json.loads(evidence).get("reasons", ()))
        entry = issues.setdefault(issue, (kind, rule, status, reasons, set()))
        entry[4].add(members[transaction_id] if transaction_id else frozenset({keys[record_id]}))
    relationships = sorted(
        (kind, rule, status, reasons, sorted(map(sorted, subjects)))
        for kind, rule, status, reasons, subjects in issues.values()
    )
    return {
        "movement": account_movement(conn),
        "transactions": transactions,
        "link_rules": rules,
        "review": relationships,
        "constraints": active_constraints(conn),
        "revisions": sorted(review_revision(load_review_evidence(conn, issue)) for issue in issues),
    }
