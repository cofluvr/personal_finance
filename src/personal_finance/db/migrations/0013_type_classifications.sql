-- Financial types stated by a person. Rules are in docs/decisions.md D-053.

-- One stated type, anchored on the records of its transaction when it was made, as a correction is
-- (D-049). target_transaction_id is a snapshot and has no foreign key. Unclassified is never
-- stored: it is the absence of a classification that applies.
CREATE TABLE type_classification (
    id                            TEXT PRIMARY KEY,
    account_id                    TEXT NOT NULL REFERENCES account (id),
    financial_type                TEXT NOT NULL CHECK (financial_type IN (
                                      'purchase', 'refund', 'income', 'fee', 'interest',
                                      'transfer', 'card_payment', 'loan_payment',
                                      'investment_contribution')),
    target_transaction_id         TEXT NOT NULL,
    target_revision               TEXT NOT NULL,
    supersedes_classification_id  TEXT REFERENCES type_classification (id),
    created_at                    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX type_classification_account ON type_classification (account_id);

CREATE TABLE type_classification_record (
    classification_id  TEXT NOT NULL REFERENCES type_classification (id),
    source_record_id   TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (classification_id, source_record_id)
) STRICT;

CREATE INDEX type_classification_record_source ON type_classification_record (source_record_id);

-- A classification is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE type_classification_event (
    id                 INTEGER PRIMARY KEY,
    classification_id  TEXT NOT NULL REFERENCES type_classification (id),
    event              TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (classification_id, event)
) STRICT;

CREATE TRIGGER type_classification_supersedes_same_account BEFORE INSERT ON type_classification
WHEN NEW.supersedes_classification_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM type_classification old
                 WHERE old.id = NEW.supersedes_classification_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a classification can only supersede one of its own account'); END;

CREATE TRIGGER type_classification_no_update BEFORE UPDATE ON type_classification
BEGIN SELECT RAISE(ABORT, 'type_classification is append-only'); END;
CREATE TRIGGER type_classification_no_delete BEFORE DELETE ON type_classification
BEGIN SELECT RAISE(ABORT, 'type_classification is append-only'); END;
CREATE TRIGGER type_classification_no_replace BEFORE INSERT ON type_classification
WHEN EXISTS (SELECT 1 FROM type_classification WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'type_classification is append-only'); END;

CREATE TRIGGER type_classification_record_no_update BEFORE UPDATE ON type_classification_record
BEGIN SELECT RAISE(ABORT, 'type_classification_record is append-only'); END;
CREATE TRIGGER type_classification_record_no_delete BEFORE DELETE ON type_classification_record
BEGIN SELECT RAISE(ABORT, 'type_classification_record is append-only'); END;
CREATE TRIGGER type_classification_record_no_replace BEFORE INSERT ON type_classification_record
WHEN EXISTS (SELECT 1 FROM type_classification_record
             WHERE classification_id = NEW.classification_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'type_classification_record is append-only'); END;

CREATE TRIGGER type_classification_event_no_update BEFORE UPDATE ON type_classification_event
BEGIN SELECT RAISE(ABORT, 'type_classification_event is append-only'); END;
CREATE TRIGGER type_classification_event_no_delete BEFORE DELETE ON type_classification_event
BEGIN SELECT RAISE(ABORT, 'type_classification_event is append-only'); END;
CREATE TRIGGER type_classification_event_no_replace BEFORE INSERT ON type_classification_event
WHEN EXISTS (SELECT 1 FROM type_classification_event
             WHERE id = NEW.id
                OR (classification_id = NEW.classification_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'type_classification_event is append-only'); END;

-- Derived, never edited by hand: the type of each classified live transaction, or why none
-- applies. A transaction with no row is unclassified. Every reconcile, correction and
-- classification rewrites an account's rows. A retired transaction takes its row with it.
CREATE TABLE transaction_classification (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                   'against_direction')),
    financial_type  TEXT,
    CHECK ((state = 'applied') = (financial_type IS NOT NULL))
) STRICT;
