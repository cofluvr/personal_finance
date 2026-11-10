-- Categories stated by a person on spending. Rules are in docs/decisions.md D-063.

-- One stated category, anchored on the records of its transaction when it was made, as a
-- classification is (D-053). target_transaction_id is a snapshot and has no foreign key.
-- Uncategorized is never stored: it is the absence of a categorization that applies.
CREATE TABLE category_assignment (
    id                        TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL REFERENCES account (id),
    category_id               INTEGER NOT NULL REFERENCES category (id),
    target_transaction_id     TEXT NOT NULL,
    target_revision           TEXT NOT NULL,
    supersedes_assignment_id  TEXT REFERENCES category_assignment (id),
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX category_assignment_account ON category_assignment (account_id);

CREATE TABLE category_assignment_record (
    assignment_id     TEXT NOT NULL REFERENCES category_assignment (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (assignment_id, source_record_id)
) STRICT;

CREATE INDEX category_assignment_record_source ON category_assignment_record (source_record_id);

-- A categorization is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE category_assignment_event (
    id             INTEGER PRIMARY KEY,
    assignment_id  TEXT NOT NULL REFERENCES category_assignment (id),
    event          TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assignment_id, event)
) STRICT;

CREATE TRIGGER category_assignment_supersedes_same_account BEFORE INSERT ON category_assignment
WHEN NEW.supersedes_assignment_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM category_assignment old
                 WHERE old.id = NEW.supersedes_assignment_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a categorization can only supersede one of its own account'); END;

CREATE TRIGGER category_assignment_no_update BEFORE UPDATE ON category_assignment
BEGIN SELECT RAISE(ABORT, 'category_assignment is append-only'); END;
CREATE TRIGGER category_assignment_no_delete BEFORE DELETE ON category_assignment
BEGIN SELECT RAISE(ABORT, 'category_assignment is append-only'); END;
CREATE TRIGGER category_assignment_no_replace BEFORE INSERT ON category_assignment
WHEN EXISTS (SELECT 1 FROM category_assignment WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'category_assignment is append-only'); END;

CREATE TRIGGER category_assignment_record_no_update BEFORE UPDATE ON category_assignment_record
BEGIN SELECT RAISE(ABORT, 'category_assignment_record is append-only'); END;
CREATE TRIGGER category_assignment_record_no_delete BEFORE DELETE ON category_assignment_record
BEGIN SELECT RAISE(ABORT, 'category_assignment_record is append-only'); END;
CREATE TRIGGER category_assignment_record_no_replace BEFORE INSERT ON category_assignment_record
WHEN EXISTS (SELECT 1 FROM category_assignment_record
             WHERE assignment_id = NEW.assignment_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'category_assignment_record is append-only'); END;

CREATE TRIGGER category_assignment_event_no_update BEFORE UPDATE ON category_assignment_event
BEGIN SELECT RAISE(ABORT, 'category_assignment_event is append-only'); END;
CREATE TRIGGER category_assignment_event_no_delete BEFORE DELETE ON category_assignment_event
BEGIN SELECT RAISE(ABORT, 'category_assignment_event is append-only'); END;
CREATE TRIGGER category_assignment_event_no_replace BEFORE INSERT ON category_assignment_event
WHEN EXISTS (SELECT 1 FROM category_assignment_event
             WHERE id = NEW.id
                OR (assignment_id = NEW.assignment_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'category_assignment_event is append-only'); END;

-- Derived, never edited by hand: the category of each categorized live transaction, or why none
-- applies. A transaction with no row is uncategorized. Every reconcile, correction,
-- classification, transfer and categorization rewrites the rows of every categorized account. A
-- retired transaction takes its row with it.
CREATE TABLE transaction_category (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                   'not_spending')),
    category_id     INTEGER REFERENCES category (id),
    CHECK ((state = 'applied') = (category_id IS NOT NULL))
) STRICT;
