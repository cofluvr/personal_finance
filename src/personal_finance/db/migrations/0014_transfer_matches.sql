-- Transfers across accounts, matched by a person. Rules are in docs/decisions.md D-054.

-- One stated transfer between two transactions of two accounts. Each side is anchored on the
-- records of its transaction when the match was made, as a classification is (D-053).
-- target_transaction_id is a snapshot and has no foreign key.
CREATE TABLE transfer_match (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE transfer_match_side (
    match_id               TEXT NOT NULL REFERENCES transfer_match (id),
    side                   TEXT NOT NULL CHECK (side IN ('outflow', 'inflow')),
    account_id             TEXT NOT NULL REFERENCES account (id),
    target_transaction_id  TEXT NOT NULL,
    target_revision        TEXT NOT NULL,
    PRIMARY KEY (match_id, side)
) STRICT;

CREATE INDEX transfer_match_side_account ON transfer_match_side (account_id);

CREATE TABLE transfer_match_record (
    match_id          TEXT NOT NULL,
    side              TEXT NOT NULL,
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (match_id, source_record_id),
    FOREIGN KEY (match_id, side) REFERENCES transfer_match_side (match_id, side)
) STRICT;

CREATE INDEX transfer_match_record_source ON transfer_match_record (source_record_id);

-- A match is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE transfer_match_event (
    id          INTEGER PRIMARY KEY,
    match_id    TEXT NOT NULL REFERENCES transfer_match (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (match_id, event)
) STRICT;

CREATE TRIGGER transfer_match_side_two_accounts BEFORE INSERT ON transfer_match_side
WHEN EXISTS (SELECT 1 FROM transfer_match_side other
             WHERE other.match_id = NEW.match_id AND other.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a transfer match joins two accounts'); END;

CREATE TRIGGER transfer_match_record_of_its_account BEFORE INSERT ON transfer_match_record
WHEN NOT EXISTS (SELECT 1 FROM transfer_match_side side
                 JOIN source_record record ON record.account_id = side.account_id
                 WHERE side.match_id = NEW.match_id AND side.side = NEW.side
                   AND record.id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'a transfer match binds records of its side''s account only'); END;

CREATE TRIGGER transfer_match_no_update BEFORE UPDATE ON transfer_match
BEGIN SELECT RAISE(ABORT, 'transfer_match is append-only'); END;
CREATE TRIGGER transfer_match_no_delete BEFORE DELETE ON transfer_match
BEGIN SELECT RAISE(ABORT, 'transfer_match is append-only'); END;
CREATE TRIGGER transfer_match_no_replace BEFORE INSERT ON transfer_match
WHEN EXISTS (SELECT 1 FROM transfer_match WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'transfer_match is append-only'); END;

CREATE TRIGGER transfer_match_side_no_update BEFORE UPDATE ON transfer_match_side
BEGIN SELECT RAISE(ABORT, 'transfer_match_side is append-only'); END;
CREATE TRIGGER transfer_match_side_no_delete BEFORE DELETE ON transfer_match_side
BEGIN SELECT RAISE(ABORT, 'transfer_match_side is append-only'); END;
CREATE TRIGGER transfer_match_side_no_replace BEFORE INSERT ON transfer_match_side
WHEN EXISTS (SELECT 1 FROM transfer_match_side
             WHERE match_id = NEW.match_id AND side = NEW.side)
BEGIN SELECT RAISE(ABORT, 'transfer_match_side is append-only'); END;

CREATE TRIGGER transfer_match_record_no_update BEFORE UPDATE ON transfer_match_record
BEGIN SELECT RAISE(ABORT, 'transfer_match_record is append-only'); END;
CREATE TRIGGER transfer_match_record_no_delete BEFORE DELETE ON transfer_match_record
BEGIN SELECT RAISE(ABORT, 'transfer_match_record is append-only'); END;
CREATE TRIGGER transfer_match_record_no_replace BEFORE INSERT ON transfer_match_record
WHEN EXISTS (SELECT 1 FROM transfer_match_record
             WHERE match_id = NEW.match_id AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'transfer_match_record is append-only'); END;

CREATE TRIGGER transfer_match_event_no_update BEFORE UPDATE ON transfer_match_event
BEGIN SELECT RAISE(ABORT, 'transfer_match_event is append-only'); END;
CREATE TRIGGER transfer_match_event_no_delete BEFORE DELETE ON transfer_match_event
BEGIN SELECT RAISE(ABORT, 'transfer_match_event is append-only'); END;
CREATE TRIGGER transfer_match_event_no_replace BEFORE INSERT ON transfer_match_event
WHEN EXISTS (SELECT 1 FROM transfer_match_event
             WHERE id = NEW.id OR (match_id = NEW.match_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'transfer_match_event is append-only'); END;

-- Derived, never edited by hand: the outcome of each active match. An applied match names the two
-- transactions it joins, and no transaction is a side of two applied matches. Every write that
-- rewrites classifications rewrites these rows for the whole ledger. A retired transaction takes
-- its row with it until that rewrite.
CREATE TABLE transfer_match_effect (
    match_id                TEXT PRIMARY KEY REFERENCES transfer_match (id),
    state                   TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                           'amounts_differ', 'type_differs')),
    outflow_transaction_id  TEXT REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    inflow_transaction_id   TEXT REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    CHECK ((state = 'applied') = (outflow_transaction_id IS NOT NULL)),
    CHECK ((state = 'applied') = (inflow_transaction_id IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX transfer_match_effect_outflow ON transfer_match_effect (outflow_transaction_id);
CREATE UNIQUE INDEX transfer_match_effect_inflow ON transfer_match_effect (inflow_transaction_id);

-- A card, loan or investment payment may now be money in on the account it pays. A transaction
-- left unclassified as against its direction on such an account may now fit, so clearing the
-- account's marker makes it stale until reconcile rewrites its classifications (D-035, D-054).
DELETE FROM account_reconciliation
WHERE account_id IN (
    SELECT entry.account_id
    FROM transaction_classification kind
    JOIN ledger_transaction entry ON entry.id = kind.transaction_id
    JOIN account ON account.id = entry.account_id
    WHERE kind.state = 'against_direction'
      AND account.account_type IN ('credit_card', 'loan', 'investment', 'retirement')
);
