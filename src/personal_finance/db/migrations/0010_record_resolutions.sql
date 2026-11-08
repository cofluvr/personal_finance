-- Resolving incomplete records. Rules are in docs/decisions.md D-050.

-- One resolution of one unresolved source record: completed with the values its parse lacks, or
-- dismissed as adding no transaction. The record and its parse are never changed.
CREATE TABLE record_resolution (
    id                          TEXT PRIMARY KEY,
    account_id                  TEXT NOT NULL REFERENCES account (id),
    source_record_id            TEXT NOT NULL REFERENCES source_record (id),
    kind                        TEXT NOT NULL CHECK (kind IN ('completed', 'dismissed')),
    completed_amount_cents      INTEGER,
    completed_transaction_date  TEXT CHECK (completed_transaction_date IS NULL
                                            OR date(completed_transaction_date)
                                               IS completed_transaction_date),
    completed_posting_date      TEXT CHECK (completed_posting_date IS NULL
                                            OR date(completed_posting_date) IS completed_posting_date),
    completed_description       TEXT CHECK (completed_description IS NULL
                                            OR length(trim(completed_description)) > 0),
    target_issue_id             TEXT NOT NULL,
    target_revision             TEXT NOT NULL,
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (kind = 'completed' OR (completed_amount_cents IS NULL
                                  AND completed_transaction_date IS NULL
                                  AND completed_posting_date IS NULL
                                  AND completed_description IS NULL))
) STRICT;

CREATE INDEX record_resolution_account ON record_resolution (account_id);
CREATE INDEX record_resolution_record ON record_resolution (source_record_id);

-- A resolution is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE record_resolution_event (
    id             INTEGER PRIMARY KEY,
    resolution_id  TEXT NOT NULL REFERENCES record_resolution (id),
    event          TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (resolution_id, event)
) STRICT;

CREATE TRIGGER record_resolution_no_update BEFORE UPDATE ON record_resolution
BEGIN SELECT RAISE(ABORT, 'record_resolution is append-only'); END;
CREATE TRIGGER record_resolution_no_delete BEFORE DELETE ON record_resolution
BEGIN SELECT RAISE(ABORT, 'record_resolution is append-only'); END;
CREATE TRIGGER record_resolution_no_replace BEFORE INSERT ON record_resolution
WHEN EXISTS (SELECT 1 FROM record_resolution WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'record_resolution is append-only'); END;

CREATE TRIGGER record_resolution_event_no_update BEFORE UPDATE ON record_resolution_event
BEGIN SELECT RAISE(ABORT, 'record_resolution_event is append-only'); END;
CREATE TRIGGER record_resolution_event_no_delete BEFORE DELETE ON record_resolution_event
BEGIN SELECT RAISE(ABORT, 'record_resolution_event is append-only'); END;
CREATE TRIGGER record_resolution_event_no_replace BEFORE INSERT ON record_resolution_event
WHEN EXISTS (SELECT 1 FROM record_resolution_event
             WHERE id = NEW.id OR (resolution_id = NEW.resolution_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'record_resolution_event is append-only'); END;
