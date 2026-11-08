-- One-sided transfers, stated by a person. Rules are in docs/decisions.md D-055.

-- One transaction stated to move money between its account and a counterpart account whose side is
-- not in the ledger. It is anchored on the records of its transaction when stated, as a match is
-- (D-054). target_transaction_id is a snapshot and has no foreign key.
CREATE TABLE one_sided_transfer (
    id                      TEXT PRIMARY KEY,
    account_id              TEXT NOT NULL REFERENCES account (id),
    counterpart_account_id  TEXT NOT NULL REFERENCES account (id),
    target_transaction_id   TEXT NOT NULL,
    target_revision         TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (account_id <> counterpart_account_id)
) STRICT;

CREATE INDEX one_sided_transfer_account ON one_sided_transfer (account_id);
CREATE INDEX one_sided_transfer_counterpart ON one_sided_transfer (counterpart_account_id);

CREATE TABLE one_sided_transfer_record (
    one_sided_transfer_id  TEXT NOT NULL REFERENCES one_sided_transfer (id),
    source_record_id       TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (one_sided_transfer_id, source_record_id)
) STRICT;

CREATE INDEX one_sided_transfer_record_source ON one_sided_transfer_record (source_record_id);

-- A one-sided transfer is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE one_sided_transfer_event (
    id                     INTEGER PRIMARY KEY,
    one_sided_transfer_id  TEXT NOT NULL REFERENCES one_sided_transfer (id),
    event                  TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (one_sided_transfer_id, event)
) STRICT;

CREATE TRIGGER one_sided_transfer_record_of_its_account BEFORE INSERT ON one_sided_transfer_record
WHEN NOT EXISTS (SELECT 1 FROM one_sided_transfer statement
                 JOIN source_record record ON record.account_id = statement.account_id
                 WHERE statement.id = NEW.one_sided_transfer_id
                   AND record.id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'a one-sided transfer binds records of its own account only'); END;

CREATE TRIGGER one_sided_transfer_no_update BEFORE UPDATE ON one_sided_transfer
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer is append-only'); END;
CREATE TRIGGER one_sided_transfer_no_delete BEFORE DELETE ON one_sided_transfer
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer is append-only'); END;
CREATE TRIGGER one_sided_transfer_no_replace BEFORE INSERT ON one_sided_transfer
WHEN EXISTS (SELECT 1 FROM one_sided_transfer WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer is append-only'); END;

CREATE TRIGGER one_sided_transfer_record_no_update BEFORE UPDATE ON one_sided_transfer_record
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_record is append-only'); END;
CREATE TRIGGER one_sided_transfer_record_no_delete BEFORE DELETE ON one_sided_transfer_record
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_record is append-only'); END;
CREATE TRIGGER one_sided_transfer_record_no_replace BEFORE INSERT ON one_sided_transfer_record
WHEN EXISTS (SELECT 1 FROM one_sided_transfer_record
             WHERE one_sided_transfer_id = NEW.one_sided_transfer_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_record is append-only'); END;

CREATE TRIGGER one_sided_transfer_event_no_update BEFORE UPDATE ON one_sided_transfer_event
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_event is append-only'); END;
CREATE TRIGGER one_sided_transfer_event_no_delete BEFORE DELETE ON one_sided_transfer_event
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_event is append-only'); END;
CREATE TRIGGER one_sided_transfer_event_no_replace BEFORE INSERT ON one_sided_transfer_event
WHEN EXISTS (SELECT 1 FROM one_sided_transfer_event
             WHERE id = NEW.id
                OR (one_sided_transfer_id = NEW.one_sided_transfer_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'one_sided_transfer_event is append-only'); END;

-- Derived, never edited by hand: the outcome of each active one-sided transfer. An applied one
-- names its transaction, and no transaction holds two applied ones. Rewritten with
-- transfer_match_effect for the whole ledger. A retired transaction takes its row with it until
-- that rewrite.
CREATE TABLE one_sided_transfer_effect (
    one_sided_transfer_id  TEXT PRIMARY KEY REFERENCES one_sided_transfer (id),
    state                  TEXT NOT NULL CHECK (state IN ('applied', 'basis_changed', 'conflict',
                                                          'type_differs', 'counterpart_found',
                                                          'counterpart_covered')),
    transaction_id         TEXT REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    CHECK ((state = 'applied') = (transaction_id IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX one_sided_transfer_effect_transaction
    ON one_sided_transfer_effect (transaction_id);
