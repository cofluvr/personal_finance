-- Stored identity decisions, and the decision_conflict review kind. Rules are in
-- docs/decisions.md D-042 to D-045.

-- A decision is anchored on source records, because a merge deletes a retired transaction
-- row. review_issue_id has no foreign key: an item is removed when a decision closes it.
CREATE TABLE decision (
    id                TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES account (id),
    review_issue_id   TEXT NOT NULL,
    item_revision     TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX decision_account ON decision (account_id);

-- One row per bound record pair. A stated pair of transactions is the rows sharing a
-- pair_number: its two sides are the left and right records, and the transaction IDs are
-- snapshots from decision time. same_event is reserved for confirmation and unused here.
CREATE TABLE decision_constraint (
    id                     INTEGER PRIMARY KEY,
    decision_id            TEXT NOT NULL REFERENCES decision (id),
    relation               TEXT NOT NULL CHECK (relation IN ('different_event', 'same_event')),
    pair_number            INTEGER NOT NULL CHECK (pair_number >= 1),
    left_transaction_id    TEXT NOT NULL,
    right_transaction_id   TEXT NOT NULL,
    left_record_id         TEXT NOT NULL REFERENCES source_record (id),
    right_record_id        TEXT NOT NULL REFERENCES source_record (id),
    UNIQUE (decision_id, pair_number, left_record_id, right_record_id),
    CHECK (left_transaction_id <> right_transaction_id),
    CHECK (left_record_id <> right_record_id)
) STRICT;

CREATE INDEX decision_constraint_left ON decision_constraint (left_record_id);
CREATE INDEX decision_constraint_right ON decision_constraint (right_record_id);

-- A decision is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE decision_event (
    id                 INTEGER PRIMARY KEY,
    decision_id        TEXT NOT NULL REFERENCES decision (id),
    event              TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    rules_fingerprint  TEXT NOT NULL CHECK (length(rules_fingerprint) = 64),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (decision_id, event)
) STRICT;

CREATE TRIGGER decision_no_update BEFORE UPDATE ON decision
BEGIN SELECT RAISE(ABORT, 'decision is append-only'); END;
CREATE TRIGGER decision_no_delete BEFORE DELETE ON decision
BEGIN SELECT RAISE(ABORT, 'decision is append-only'); END;
CREATE TRIGGER decision_no_replace BEFORE INSERT ON decision
WHEN EXISTS (SELECT 1 FROM decision WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'decision is append-only'); END;

CREATE TRIGGER decision_constraint_no_update BEFORE UPDATE ON decision_constraint
BEGIN SELECT RAISE(ABORT, 'decision_constraint is append-only'); END;
CREATE TRIGGER decision_constraint_no_delete BEFORE DELETE ON decision_constraint
BEGIN SELECT RAISE(ABORT, 'decision_constraint is append-only'); END;
CREATE TRIGGER decision_constraint_no_replace BEFORE INSERT ON decision_constraint
WHEN EXISTS (SELECT 1 FROM decision_constraint
             WHERE id = NEW.id
                OR (decision_id = NEW.decision_id AND pair_number = NEW.pair_number
                    AND left_record_id = NEW.left_record_id
                    AND right_record_id = NEW.right_record_id))
BEGIN SELECT RAISE(ABORT, 'decision_constraint is append-only'); END;

CREATE TRIGGER decision_event_no_update BEFORE UPDATE ON decision_event
BEGIN SELECT RAISE(ABORT, 'decision_event is append-only'); END;
CREATE TRIGGER decision_event_no_delete BEFORE DELETE ON decision_event
BEGIN SELECT RAISE(ABORT, 'decision_event is append-only'); END;
CREATE TRIGGER decision_event_no_replace BEFORE INSERT ON decision_event
WHEN EXISTS (SELECT 1 FROM decision_event
             WHERE id = NEW.id OR (decision_id = NEW.decision_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'decision_event is append-only'); END;

-- The decision behind a move, when one caused it.
ALTER TABLE transaction_link_history ADD COLUMN decision_id TEXT REFERENCES decision (id);

-- Widening a CHECK needs review_issue rebuilt. Its subjects move out and back, because
-- dropping the table while they reference it fails the foreign keys at commit, even with
-- defer_foreign_keys.
CREATE TABLE review_issue_subject_moved AS
SELECT rowid AS moved_rowid, review_issue_id, transaction_id, source_record_id
FROM review_issue_subject;
DELETE FROM review_issue_subject;

CREATE TABLE review_issue_rebuilt (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('possible_duplicate', 'unresolved_record',
                                                 'decision_conflict')),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    rule           TEXT NOT NULL,
    evidence_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_json)),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at    TEXT,
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
) STRICT;

INSERT INTO review_issue_rebuilt (id, kind, status, rule, evidence_json, created_at, resolved_at)
SELECT id, kind, status, rule, evidence_json, created_at, resolved_at FROM review_issue;

DROP TABLE review_issue;
ALTER TABLE review_issue_rebuilt RENAME TO review_issue;

INSERT INTO review_issue_subject (rowid, review_issue_id, transaction_id, source_record_id)
SELECT moved_rowid, review_issue_id, transaction_id, source_record_id
FROM review_issue_subject_moved;
DROP TABLE review_issue_subject_moved;
