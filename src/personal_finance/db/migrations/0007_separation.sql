-- Separating machine-made merges. Rules are in docs/decisions.md D-047.

-- A decision now targets a review item or, for a separation, one transaction. Both are
-- snapshots with no foreign key, as review_issue_id was: either can be removed since.
ALTER TABLE decision RENAME COLUMN review_issue_id TO target_id;
ALTER TABLE decision RENAME COLUMN item_revision TO target_revision;
ALTER TABLE decision ADD COLUMN target_kind TEXT NOT NULL DEFAULT 'item'
    CHECK (target_kind IN ('item', 'transaction'));

-- A separation's two sides start in one transaction, which the old check refused. Parts number
-- the groups of a separation and are NULL for every other decision. Nothing references this
-- table, so it is rebuilt directly. Dropping it fires none of its triggers.
CREATE TABLE decision_constraint_rebuilt (
    id                     INTEGER PRIMARY KEY,
    decision_id            TEXT NOT NULL REFERENCES decision (id),
    relation               TEXT NOT NULL CHECK (relation IN ('different_event', 'same_event')),
    pair_number            INTEGER NOT NULL CHECK (pair_number >= 1),
    left_transaction_id    TEXT NOT NULL,
    right_transaction_id   TEXT NOT NULL,
    left_record_id         TEXT NOT NULL REFERENCES source_record (id),
    right_record_id        TEXT NOT NULL REFERENCES source_record (id),
    left_part              INTEGER CHECK (left_part >= 1),
    right_part             INTEGER CHECK (right_part >= 1),
    UNIQUE (decision_id, pair_number, left_record_id, right_record_id),
    CHECK (left_record_id <> right_record_id),
    CHECK ((left_part IS NULL) = (right_part IS NULL)),
    CHECK (left_part IS NOT NULL OR left_transaction_id <> right_transaction_id),
    CHECK (left_part IS NULL OR (relation = 'same_event') = (left_part = right_part))
) STRICT;

INSERT INTO decision_constraint_rebuilt (id, decision_id, relation, pair_number,
                                         left_transaction_id, right_transaction_id,
                                         left_record_id, right_record_id)
SELECT id, decision_id, relation, pair_number, left_transaction_id, right_transaction_id,
       left_record_id, right_record_id
FROM decision_constraint;

DROP TABLE decision_constraint;
ALTER TABLE decision_constraint_rebuilt RENAME TO decision_constraint;

CREATE INDEX decision_constraint_left ON decision_constraint (left_record_id);
CREATE INDEX decision_constraint_right ON decision_constraint (right_record_id);

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
