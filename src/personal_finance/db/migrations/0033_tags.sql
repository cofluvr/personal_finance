-- Tags, free labels a person gives a transaction, and the statements that give them. Rules are in
-- docs/decisions-m12-m21.md D-073 point 5. Tags enter no total: they filter search and exports.

-- Append-only, as categories are (D-063): no rename, merge or delete, so a tag keeps meaning what
-- it meant. Names are compared exactly, and hold no comma.
CREATE TABLE tag (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE CHECK (trim(name) = name AND name <> ''
                                            AND instr(name, ',') = 0),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER tag_no_update BEFORE UPDATE ON tag
BEGIN SELECT RAISE(ABORT, 'tag is append-only'); END;
CREATE TRIGGER tag_no_delete BEFORE DELETE ON tag
BEGIN SELECT RAISE(ABORT, 'tag is append-only'); END;
CREATE TRIGGER tag_no_replace BEFORE INSERT ON tag
WHEN EXISTS (SELECT 1 FROM tag WHERE id = NEW.id OR name = NEW.name)
BEGIN SELECT RAISE(ABORT, 'tag is append-only'); END;

-- One statement of a transaction's whole set of tags, anchored on the records of its transaction
-- when it was made, as a categorization is (D-063). Its value is canonical: the tag IDs in
-- ascending order, joined by commas, or empty for a statement that the transaction has none. Two
-- statements agree exactly when their values are equal (D-065's multi-part value).
CREATE TABLE tag_statement (
    id                          TEXT PRIMARY KEY,
    account_id                  TEXT NOT NULL REFERENCES account (id),
    tags                        TEXT NOT NULL CHECK (tags NOT GLOB '*[^0-9,]*'
                                                     AND tags NOT GLOB ',*'
                                                     AND tags NOT GLOB '*,'
                                                     AND tags NOT GLOB '*,,*'),
    target_transaction_id       TEXT NOT NULL,
    target_revision             TEXT NOT NULL,
    supersedes_tag_statement_id TEXT REFERENCES tag_statement (id),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX tag_statement_account ON tag_statement (account_id);

CREATE TABLE tag_statement_record (
    tag_statement_id  TEXT NOT NULL REFERENCES tag_statement (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (tag_statement_id, source_record_id)
) STRICT;

CREATE INDEX tag_statement_record_source ON tag_statement_record (source_record_id);

-- A statement is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE tag_statement_event (
    id                INTEGER PRIMARY KEY,
    tag_statement_id  TEXT NOT NULL REFERENCES tag_statement (id),
    event             TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (tag_statement_id, event)
) STRICT;

CREATE TRIGGER tag_statement_supersedes_same_account
BEFORE INSERT ON tag_statement
WHEN NEW.supersedes_tag_statement_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM tag_statement old
                 WHERE old.id = NEW.supersedes_tag_statement_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a tag statement can only supersede one of its own account'); END;

CREATE TRIGGER tag_statement_no_update BEFORE UPDATE ON tag_statement
BEGIN SELECT RAISE(ABORT, 'tag_statement is append-only'); END;
CREATE TRIGGER tag_statement_no_delete BEFORE DELETE ON tag_statement
BEGIN SELECT RAISE(ABORT, 'tag_statement is append-only'); END;
CREATE TRIGGER tag_statement_no_replace BEFORE INSERT ON tag_statement
WHEN EXISTS (SELECT 1 FROM tag_statement WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'tag_statement is append-only'); END;

CREATE TRIGGER tag_statement_record_no_update BEFORE UPDATE ON tag_statement_record
BEGIN SELECT RAISE(ABORT, 'tag_statement_record is append-only'); END;
CREATE TRIGGER tag_statement_record_no_delete BEFORE DELETE ON tag_statement_record
BEGIN SELECT RAISE(ABORT, 'tag_statement_record is append-only'); END;
CREATE TRIGGER tag_statement_record_no_replace BEFORE INSERT ON tag_statement_record
WHEN EXISTS (SELECT 1 FROM tag_statement_record
             WHERE tag_statement_id = NEW.tag_statement_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'tag_statement_record is append-only'); END;

CREATE TRIGGER tag_statement_event_no_update BEFORE UPDATE ON tag_statement_event
BEGIN SELECT RAISE(ABORT, 'tag_statement_event is append-only'); END;
CREATE TRIGGER tag_statement_event_no_delete BEFORE DELETE ON tag_statement_event
BEGIN SELECT RAISE(ABORT, 'tag_statement_event is append-only'); END;
CREATE TRIGGER tag_statement_event_no_replace BEFORE INSERT ON tag_statement_event
WHEN EXISTS (SELECT 1 FROM tag_statement_event
             WHERE id = NEW.id
                OR (tag_statement_id = NEW.tag_statement_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'tag_statement_event is append-only'); END;

-- Derived, never edited by hand: the outcome of active tag statements on each live transaction
-- they reach, the applied value canonical as above, empty for none. Tags fit any transaction, so
-- there is no misfit state. Rewritten wherever transaction_category is. A retired transaction
-- takes its row with it.
CREATE TABLE transaction_tag (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed')),
    tags            TEXT,
    CHECK ((state = 'applied') = (tags IS NOT NULL))
) STRICT;
