-- Value corrections. Rules are in docs/decisions.md D-049.

-- One corrected field, anchored on the records of its transaction when it was made, because a merge
-- deletes a retired transaction row. target_transaction_id is a snapshot and has no foreign key.
CREATE TABLE value_correction (
    id                        TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL REFERENCES account (id),
    field                     TEXT NOT NULL CHECK (field IN ('amount', 'transaction_date',
                                                             'posting_date', 'description')),
    corrected_amount_cents    INTEGER,
    corrected_text            TEXT,
    target_transaction_id     TEXT NOT NULL,
    target_revision           TEXT NOT NULL,
    supersedes_correction_id  TEXT REFERENCES value_correction (id),
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((field = 'amount') = (corrected_amount_cents IS NOT NULL)),
    CHECK ((field = 'amount') = (corrected_text IS NULL)),
    CHECK (field NOT IN ('transaction_date', 'posting_date')
           OR date(corrected_text) IS corrected_text),
    CHECK (field <> 'description' OR length(trim(corrected_text)) > 0)
) STRICT;

CREATE INDEX value_correction_account ON value_correction (account_id);

CREATE TABLE value_correction_record (
    correction_id     TEXT NOT NULL REFERENCES value_correction (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (correction_id, source_record_id)
) STRICT;

CREATE INDEX value_correction_record_source ON value_correction_record (source_record_id);

-- A correction is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE value_correction_event (
    id                 INTEGER PRIMARY KEY,
    correction_id      TEXT NOT NULL REFERENCES value_correction (id),
    event              TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (correction_id, event)
) STRICT;

CREATE TRIGGER value_correction_supersedes_same_field BEFORE INSERT ON value_correction
WHEN NEW.supersedes_correction_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM value_correction old
                 WHERE old.id = NEW.supersedes_correction_id AND old.account_id = NEW.account_id
                   AND old.field = NEW.field)
BEGIN SELECT RAISE(ABORT, 'a correction can only supersede one of its own account and field'); END;

CREATE TRIGGER value_correction_no_update BEFORE UPDATE ON value_correction
BEGIN SELECT RAISE(ABORT, 'value_correction is append-only'); END;
CREATE TRIGGER value_correction_no_delete BEFORE DELETE ON value_correction
BEGIN SELECT RAISE(ABORT, 'value_correction is append-only'); END;
CREATE TRIGGER value_correction_no_replace BEFORE INSERT ON value_correction
WHEN EXISTS (SELECT 1 FROM value_correction WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'value_correction is append-only'); END;

CREATE TRIGGER value_correction_record_no_update BEFORE UPDATE ON value_correction_record
BEGIN SELECT RAISE(ABORT, 'value_correction_record is append-only'); END;
CREATE TRIGGER value_correction_record_no_delete BEFORE DELETE ON value_correction_record
BEGIN SELECT RAISE(ABORT, 'value_correction_record is append-only'); END;
CREATE TRIGGER value_correction_record_no_replace BEFORE INSERT ON value_correction_record
WHEN EXISTS (SELECT 1 FROM value_correction_record
             WHERE correction_id = NEW.correction_id AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'value_correction_record is append-only'); END;

CREATE TRIGGER value_correction_event_no_update BEFORE UPDATE ON value_correction_event
BEGIN SELECT RAISE(ABORT, 'value_correction_event is append-only'); END;
CREATE TRIGGER value_correction_event_no_delete BEFORE DELETE ON value_correction_event
BEGIN SELECT RAISE(ABORT, 'value_correction_event is append-only'); END;
CREATE TRIGGER value_correction_event_no_replace BEFORE INSERT ON value_correction_event
WHEN EXISTS (SELECT 1 FROM value_correction_event
             WHERE id = NEW.id OR (correction_id = NEW.correction_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'value_correction_event is append-only'); END;

-- Derived, never edited by hand: each corrected field of a live transaction and its state. Every
-- reconcile and correction rewrites an account's rows. A retired transaction takes its rows with it.
CREATE TABLE transaction_correction (
    transaction_id          TEXT NOT NULL REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    field                   TEXT NOT NULL CHECK (field IN ('amount', 'transaction_date',
                                                           'posting_date', 'description')),
    state                   TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed')),
    corrected_amount_cents  INTEGER,
    corrected_text          TEXT,
    PRIMARY KEY (transaction_id, field),
    CHECK ((state = 'applied') = (corrected_amount_cents IS NOT NULL OR corrected_text IS NOT NULL))
) STRICT;
