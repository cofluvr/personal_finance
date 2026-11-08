"""Applies a derivation to one account. See decisions.md D-029, D-033 and D-042 to D-045.

Every function here runs inside the caller's database transaction, so an import and
its reconciliation commit together or not at all. Source evidence is only read.
Issues that are not open machine-made candidates are never reopened or rewritten:
their subjects only follow their records.
"""

import json
import sqlite3
import uuid
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.cross_document import (
    RULE_CANDIDATES,
    RULE_DECISION,
    RULE_EXTERNAL_ID,
    Constraint,
    Derivation,
    Document,
    Record,
    UnresolvedRecord,
    derive,
)
from personal_finance.reconcile.correction_effects import write_correction_effects
from personal_finance.reconcile.rules import DEFAULT_RULES, RULES_VERSION, MatchingRules
from personal_finance.reconcile.supersession import (
    STATE_ACTIVE,
    STATE_SUPERSEDED,
    STATE_UNDONE,
    supersession_chain_states,
)

MANAGED_RULES = (RULE_CANDIDATES, RULE_EXTERNAL_ID, RULE_DECISION)
KIND_DUPLICATE = "possible_duplicate"
KIND_CONFLICT = "decision_conflict"



@dataclass(frozen=True)
class ReconcileResult:
    derivation: Derivation
    moved_records: int


def stale_accounts(
    conn: sqlite3.Connection, rules: MatchingRules, account_id: str | None = None
) -> list[str]:
    """Accounts needing reconciliation. This is the only definition of current (D-033).

    An account with live transactions is current only if it was last reconciled under
    this exact configuration and every transaction records its primary source. An account
    with no transactions has nothing to reconcile, so it is never stale.
    """
    rows = conn.execute(
        """SELECT account.id
           FROM account
           LEFT JOIN account_reconciliation marker ON marker.account_id = account.id
           WHERE (:account IS NULL OR account.id = :account)
             AND EXISTS (SELECT 1 FROM ledger_transaction entry
                         WHERE entry.account_id = account.id)
             AND (marker.rules_fingerprint IS NULL
                  OR marker.rules_fingerprint <> :fingerprint
                  OR EXISTS (SELECT 1 FROM ledger_transaction entry
                             WHERE entry.account_id = account.id
                               AND entry.primary_source_record_id IS NULL))
           ORDER BY account.id""",
        {"account": account_id, "fingerprint": rules.fingerprint()},
    )
    return [row[0] for row in rows]


def is_current(conn: sqlite3.Connection, account_id: str, rules: MatchingRules) -> bool:
    return not stale_accounts(conn, rules, account_id)


def reconcile_account(
    conn: sqlite3.Connection,
    account_id: str,
    rules: MatchingRules = DEFAULT_RULES,
    trigger_document_id: str | None = None,
    decision_id: str | None = None,
) -> ReconcileResult:
    """Bring one account in line with its evidence. The caller holds the transaction.

    decision_id names the decision being made or undone, when that is why this is running.
    """
    documents, records, unresolved, import_order = load_evidence(conn, account_id)
    constraints = load_constraints(conn, account_id)
    derivation = derive(documents, records, unresolved, rules, constraints)

    state = _State(conn, account_id, records, derivation, import_order, rules, trigger_document_id,
                   decision_id)
    state.write_transactions()
    moved = state.write_links(_last_fingerprint(conn, account_id))
    state.write_review_items()
    state.repoint_other_issues()
    state.retire_unused_transactions()
    # After memberships are final, since corrections follow their records (D-049).
    write_correction_effects(conn, account_id)
    _write_marker(conn, account_id, rules)
    return ReconcileResult(derivation, moved)


def _last_fingerprint(conn, account_id) -> str | None:
    row = conn.execute(
        "SELECT rules_fingerprint FROM account_reconciliation WHERE account_id = ?", (account_id,)
    ).fetchone()
    return row[0] if row else None


def _write_marker(conn, account_id, rules) -> None:
    conn.execute(
        """INSERT INTO account_reconciliation (account_id, rules_version, rules_fingerprint,
                                               rules_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (account_id) DO UPDATE SET
               rules_version = excluded.rules_version,
               rules_fingerprint = excluded.rules_fingerprint,
               rules_json = excluded.rules_json,
               reconciled_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        (account_id, RULES_VERSION, rules.fingerprint(), rules.to_json()),
    )


def decision_states(conn, account_id, without: str | None = None) -> dict[str, str]:
    """Every decision of an account as active, undone or superseded (D-046, D-048).

    A decision is superseded while any decision superseding it has not been undone, whether
    that one is active or superseded in turn, so only the newest of a chain is active. without
    is treated as undone, to see what undoing it would leave.
    """
    return supersession_chain_states(_decision_chain_rows(conn, account_id), without)[0]


def superseded_by(conn, account_id) -> dict[str, str]:
    """For each superseded decision, the decision superseding it now."""
    return supersession_chain_states(_decision_chain_rows(conn, account_id))[1]


def _decision_chain_rows(conn, account_id):
    return conn.execute(
        """SELECT decision.id, decision.supersedes_decision_id,
                  EXISTS (SELECT 1 FROM decision_event undone
                          WHERE undone.decision_id = decision.id AND undone.event = 'undone')
           FROM decision WHERE decision.account_id = ?""",
        (account_id,),
    ).fetchall()


def load_constraints(conn, account_id, without: str | None = None) -> tuple[Constraint, ...]:
    """The stated pairs of active decisions. Undone and superseded ones stay on record, unused.

    without leaves one decision out as if undone, restoring anything it superseded.
    """
    active = {
        decision for decision, state in decision_states(conn, account_id, without).items()
        if state == STATE_ACTIVE
    }
    sides = defaultdict(lambda: (set(), set()))
    kinds = {}
    for decision_id, kind, pair_number, relation, left, right in conn.execute(
        """SELECT pair.decision_id, decision.kind, pair.pair_number, pair.relation,
                  pair.left_record_id, pair.right_record_id
           FROM decision_constraint pair
           JOIN decision ON decision.id = pair.decision_id
           WHERE decision.account_id = ?""",
        (account_id,),
    ):
        if decision_id in active:
            sides[decision_id, pair_number][0].add(left)
            sides[decision_id, pair_number][1].add(right)
            kinds[decision_id, pair_number] = relation, kind == "confirm"
    return tuple(
        Constraint(decision_id, tuple(sorted(left)), tuple(sorted(right)),
                   *kinds[decision_id, number])
        for (decision_id, number), (left, right) in sorted(sides.items())
    )


def load_evidence(conn, account_id):
    """Read stored interpretation only, never the current Python layouts (D-026)."""
    documents, imported = [], {}
    for row in conn.execute(
        """SELECT document.id, document.content_sha256, document.generated_on,
                  document.imported_at, coverage.coverage_kind, coverage.coverage_start,
                  coverage.coverage_end, coverage.date_basis, coverage.evidence,
                  meaning.external_id_namespace, meaning.external_id_guarantee,
                  meaning.pending_in_transaction_basis, meaning.pending_in_posting_basis
           FROM document_coverage coverage
           JOIN source_document document ON document.id = coverage.source_document_id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           WHERE coverage.account_id = ?""",
        (account_id,),
    ):
        (document_id, digest, generated_on, imported_at, kind, start, end, basis, evidence,
         namespace, guarantee, pending_transaction, pending_posting) = row
        pending = pending_transaction if basis == "transaction" else pending_posting
        documents.append(
            Document(document_id, digest, kind, start, end, basis, evidence, generated_on,
                     namespace, guarantee, bool(pending))
        )
        imported[document_id] = (imported_at, digest)

    records, unresolved, import_order = [], [], {}
    for row in conn.execute(
        """SELECT record.id, record.source_document_id, record.record_index, parse.status,
                  parse.amount_cents, parse.transaction_date, parse.posting_date,
                  parse.description, parse.external_id, parse.settlement_status
           FROM source_record record
           JOIN document_interpretation meaning
               ON meaning.source_document_id = record.source_document_id
           JOIN record_parse parse
               ON parse.source_record_id = record.id
              AND parse.parser_version = meaning.parser_version
           WHERE record.account_id = ?""",
        (account_id,),
    ):
        record_id, document_id, index, status, *values = row
        if status == "parsed":
            records.append(Record(record_id, document_id, index, *values))
            import_order[record_id] = (*imported[document_id], index)
        else:
            unresolved.append(UnresolvedRecord(document_id, *values[:4]))
    return documents, records, unresolved, import_order


class _State:
    """The account as stored, and the changes that bring it in line."""

    def __init__(self, conn, account_id, records, derivation, import_order, rules, trigger,
                 decision_id):
        self.conn = conn
        self.account_id = account_id
        self.derivation = derivation
        self.rules = rules
        self.trigger_document_id = trigger
        self.decision_id = decision_id
        # Why records moved into or out of a transaction, for its identity history.
        self.moved_in = {}
        self.moved_out = {}
        self.records = {record.id: record for record in records}

        self.links = {}
        self.old_members = defaultdict(set)
        for record_id, transaction_id, rule, document_id, created_at in conn.execute(
            """SELECT source_record_id, transaction_id, link_rule, source_document_id, created_at
               FROM transaction_source WHERE account_id = ?""",
            (account_id,),
        ):
            self.links[record_id] = (transaction_id, rule, document_id, created_at)
            self.old_members[transaction_id].add(record_id)

        origins = dict(
            conn.execute(
                """SELECT origin.source_record_id, origin.original_transaction_id
                   FROM source_record_origin origin
                   JOIN source_record record ON record.id = origin.source_record_id
                   WHERE record.account_id = ?""",
                (account_id,),
            )
        )

        self.target = {}
        self.target_rule = {}
        self.new_members = {}
        self.primary = {}
        self.first_record = {}
        for group in derivation.groups:
            first = min(group.record_ids, key=import_order.__getitem__)
            public_id = origins[first]
            self.first_record[public_id] = first
            self.primary[public_id] = self.records[group.primary_record_id]
            self.new_members[public_id] = set(group.record_ids)
            for record_id in group.record_ids:
                self.target[record_id] = public_id
                self.target_rule[record_id] = group.link_rule

    def write_transactions(self) -> None:
        stored = {
            row[0]: row[1:]
            for row in self.conn.execute(
                """SELECT id, external_id, transaction_date, posting_date, amount_cents,
                          description, settlement_status, primary_source_record_id, created_at
                   FROM ledger_transaction WHERE account_id = ?""",
                (self.account_id,),
            )
        }
        self.stored_created_at = {key: value[-1] for key, value in stored.items()}
        self.revived = {}
        for transaction_id, record in self.primary.items():
            values = (record.external_id, record.transaction_date, record.posting_date,
                      record.amount_cents, record.description, record.settlement_status,
                      record.id)
            if transaction_id not in stored:
                created_at = self._created_at_of_retired(transaction_id)
                self.revived[transaction_id] = created_at
                self.conn.execute(
                    """INSERT INTO ledger_transaction (id, account_id, external_id,
                                                       transaction_date, posting_date,
                                                       amount_cents, description,
                                                       settlement_status,
                                                       primary_source_record_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (transaction_id, self.account_id, *values, created_at),
                )
            elif stored[transaction_id][:-1] != values:
                self.conn.execute(
                    """UPDATE ledger_transaction
                       SET external_id = ?, transaction_date = ?, posting_date = ?,
                           amount_cents = ?, description = ?, settlement_status = ?,
                           primary_source_record_id = ?
                       WHERE id = ?""",
                    (*values, transaction_id),
                )

    def _created_at_of_retired(self, transaction_id) -> str:
        """The retired row's timestamp, or for a row retired before migration 0004, when
        its first record was linked, which is the same import."""
        row = self.conn.execute(
            """SELECT transaction_created_at FROM transaction_identity_history
               WHERE transaction_id = ? AND event = 'retired' ORDER BY id DESC LIMIT 1""",
            (transaction_id,),
        ).fetchone()
        return row[0] if row else self.links[self.first_record[transaction_id]][3]

    def _record_identity_event(self, transaction_id, event, created_at, reason) -> None:
        self.conn.execute(
            """INSERT INTO transaction_identity_history (transaction_id, event,
                                                         transaction_created_at, reason,
                                                         rules_fingerprint, trigger_document_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (transaction_id, event, created_at, reason, self.rules.fingerprint(),
             self.trigger_document_id),
        )

    def write_links(self, last_fingerprint) -> int:
        moved = [
            record_id for record_id, link in self.links.items()
            if self.target[record_id] != link[0]
        ]
        # Removing first lets records swap places without breaking the per-document rule.
        self.conn.executemany(
            "DELETE FROM transaction_source WHERE source_record_id = ?",
            [(record_id,) for record_id in moved],
        )
        for record_id in moved:
            old_id, _, document_id, created_at = self.links[record_id]
            new_id = self.target[record_id]
            self.conn.execute(
                """INSERT INTO transaction_source (transaction_id, source_record_id,
                                                   source_document_id, account_id, link_rule,
                                                   created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_id, record_id, document_id, self.account_id, self.target_rule[record_id],
                 created_at),
            )
            action, reason = self._describe_move(record_id, old_id, new_id, last_fingerprint)
            self.moved_in.setdefault(new_id, reason)
            self.moved_out.setdefault(old_id, reason)
            self.conn.execute(
                """INSERT INTO transaction_link_history (source_record_id, from_transaction_id,
                                                         to_transaction_id, action, reason,
                                                         rules_fingerprint, trigger_document_id,
                                                         decision_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, old_id, new_id, action, reason, self.rules.fingerprint(),
                 self.trigger_document_id,
                 self.decision_id or self.derivation.withheld_by.get(record_id)),
            )

        for record_id, link in self.links.items():
            if self.target[record_id] == link[0] and self.target_rule[record_id] != link[1]:
                self.conn.execute(
                    "UPDATE transaction_source SET link_rule = ? WHERE source_record_id = ?",
                    (self.target_rule[record_id], record_id),
                )
        for transaction_id, created_at in self.revived.items():
            reason = self.moved_in[transaction_id]
            self._record_identity_event(transaction_id, "revived", created_at, reason)
        return len(moved)

    def _describe_move(self, record_id, old_id, new_id, last_fingerprint):
        left_behind = self.old_members[old_id] - self.new_members[new_id]
        if not left_behind:
            return "merged", self.target_rule[record_id]
        reason = self.derivation.separation_reasons.get(record_id)
        if reason is None:
            changed = last_fingerprint not in (None, self.rules.fingerprint())
            reason = "matching_rules_changed" if changed else "evidence_changed"
        return "split", reason

    def write_review_items(self) -> None:
        managed = self._managed_issues()
        settled = self._settled_groups()
        wanted = [
            item for item in self.derivation.items
            if (item.rule, _record_set(item)) not in settled
        ]

        claims = {}
        unmatched = []
        by_key = {(rule, records): issue for issue, (rule, records) in managed.items()}
        for item in wanted:
            issue = by_key.get((item.rule, _record_set(item)))
            if issue is None:
                unmatched.append(item)
            else:
                claims[issue] = item

        holders = defaultdict(set)
        for issue, (rule, records) in managed.items():
            if issue not in claims:
                for record_id in records:
                    holders[rule, record_id].add(issue)

        for item in sorted(unmatched, key=lambda entry: (entry.rule, entry.members)):
            overlap = defaultdict(int)
            for record_id in _record_set(item):
                for issue in holders[item.rule, record_id]:
                    if issue not in claims:
                        overlap[issue] += 1
            if overlap:
                best = min(overlap, key=lambda issue: (-overlap[issue], issue))
                claims[best] = item
            else:
                self._insert_issue(item)

        for issue, item in claims.items():
            self._update_issue(issue, item)
        for issue in managed:
            if issue not in claims:
                self.conn.execute(
                    "DELETE FROM review_issue_subject WHERE review_issue_id = ?", (issue,)
                )
                self.conn.execute("DELETE FROM review_issue WHERE id = ?", (issue,))

    def _issue_subjects(self, status):
        marks = ",".join("?" * len(MANAGED_RULES))
        rules, records = {}, defaultdict(set)
        for issue, rule, transaction_id in self.conn.execute(
            f"""SELECT issue.id, issue.rule, subject.transaction_id
                FROM review_issue issue
                JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
                JOIN ledger_transaction entry ON entry.id = subject.transaction_id
                WHERE issue.kind IN (?, ?) AND issue.status = ?
                  AND issue.rule IN ({marks}) AND entry.account_id = ?""",
            (KIND_DUPLICATE, KIND_CONFLICT, status, *MANAGED_RULES, self.account_id),
        ):
            rules[issue] = rule
            records[issue].update(self.old_members[transaction_id])
        return {issue: (rules[issue], frozenset(records[issue])) for issue in rules}

    def _managed_issues(self):
        return self._issue_subjects("open")

    def _settled_groups(self):
        """A group someone has decided is never raised again in the same form."""
        return set(self._issue_subjects("resolved").values())

    def _subjects_of(self, item):
        return {self.target[member[0]] for member in item.members}

    def _insert_issue(self, item) -> None:
        issue = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO review_issue (id, kind, rule, evidence_json) VALUES (?, ?, ?, ?)",
            (issue, KIND_CONFLICT if item.rule == RULE_DECISION else KIND_DUPLICATE, item.rule,
             _evidence(item)),
        )
        self.conn.executemany(
            "INSERT INTO review_issue_subject (review_issue_id, transaction_id) VALUES (?, ?)",
            [(issue, subject) for subject in self._subjects_of(item)],
        )

    def _update_issue(self, issue, item) -> None:
        stored = {
            row[0]
            for row in self.conn.execute(
                "SELECT transaction_id FROM review_issue_subject WHERE review_issue_id = ?", (issue,)
            )
        }
        wanted = self._subjects_of(item)
        self.conn.executemany(
            "DELETE FROM review_issue_subject WHERE review_issue_id = ? AND transaction_id = ?",
            [(issue, subject) for subject in stored - wanted],
        )
        self.conn.executemany(
            "INSERT INTO review_issue_subject (review_issue_id, transaction_id) VALUES (?, ?)",
            [(issue, subject) for subject in wanted - stored],
        )
        evidence = _evidence(item)
        self.conn.execute(
            "UPDATE review_issue SET evidence_json = ? WHERE id = ? AND evidence_json <> ?",
            (evidence, issue, evidence),
        )

    def repoint_other_issues(self) -> None:
        """Keep same-document and decided issues attached to the records they concern."""
        changed = {
            transaction_id
            for transaction_id, members in self.old_members.items()
            if self.new_members.get(transaction_id) != members
        }
        if not changed:
            return

        marks = ",".join("?" * len(MANAGED_RULES))
        subjects = self.conn.execute(
            f"""SELECT subject.review_issue_id, subject.transaction_id, issue.evidence_json
                FROM review_issue_subject subject
                JOIN review_issue issue ON issue.id = subject.review_issue_id
                WHERE subject.transaction_id IS NOT NULL
                  AND NOT (issue.status = 'open' AND issue.rule IN ({marks}))""",
            MANAGED_RULES,
        ).fetchall()
        for issue, transaction_id, evidence in subjects:
            if transaction_id not in changed:
                continue
            document_id = json.loads(evidence).get("source_document_id")
            targets = {
                self.target[record_id]
                for record_id in self.old_members[transaction_id]
                if document_id is None or self.links[record_id][2] == document_id
            }
            if targets == {transaction_id}:
                continue
            self.conn.execute(
                "DELETE FROM review_issue_subject WHERE review_issue_id = ? AND transaction_id = ?",
                (issue, transaction_id),
            )
            self.conn.executemany(
                """INSERT OR IGNORE INTO review_issue_subject (review_issue_id, transaction_id)
                   VALUES (?, ?)""",
                [(issue, target) for target in targets],
            )

    def retire_unused_transactions(self) -> None:
        for transaction_id, created_at in self.stored_created_at.items():
            if transaction_id not in self.primary:
                reason = self.moved_out[transaction_id]
                self._record_identity_event(transaction_id, "retired", created_at, reason)
                self.conn.execute("DELETE FROM ledger_transaction WHERE id = ?", (transaction_id,))


def _record_set(item) -> frozenset[str]:
    return frozenset(record_id for member in item.members for record_id in member)


def _evidence(item) -> str:
    return json.dumps(
        {"reasons": item.reasons, "date_start": item.date_start, "date_end": item.date_end},
        sort_keys=True,
    )
