-- Balance observations, stated by a person. Rules are in docs/decisions.md D-057.

-- A posted balance at the end of one day, in the ledger's sign convention (D-003): what a credit
-- card or loan owes is stored negative. Amounts and dates only, with no free text. Never
-- transaction evidence: derivation never reads it, and no account becomes stale by it.
CREATE TABLE balance_observation (
    id             TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES account (id),
    observed_on    TEXT NOT NULL CHECK (date(observed_on) IS observed_on),
    balance_cents  INTEGER NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX balance_observation_account_day ON balance_observation (account_id, observed_on);

-- An observation is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE balance_observation_event (
    id                      INTEGER PRIMARY KEY,
    balance_observation_id  TEXT NOT NULL REFERENCES balance_observation (id),
    event                   TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (balance_observation_id, event)
) STRICT;

CREATE TRIGGER balance_observation_one_active_per_day BEFORE INSERT ON balance_observation_event
WHEN NEW.event = 'made' AND EXISTS (
    SELECT 1 FROM balance_observation made
    JOIN balance_observation other ON other.account_id = made.account_id
                                  AND other.observed_on = made.observed_on
                                  AND other.id <> made.id
    JOIN balance_observation_event other_made ON other_made.balance_observation_id = other.id
                                             AND other_made.event = 'made'
    WHERE made.id = NEW.balance_observation_id
      AND NOT EXISTS (SELECT 1 FROM balance_observation_event undone
                      WHERE undone.balance_observation_id = other.id AND undone.event = 'undone'))
BEGIN SELECT RAISE(ABORT, 'an account holds one active balance observation per day'); END;

CREATE TRIGGER balance_observation_no_update BEFORE UPDATE ON balance_observation
BEGIN SELECT RAISE(ABORT, 'balance_observation is append-only'); END;
CREATE TRIGGER balance_observation_no_delete BEFORE DELETE ON balance_observation
BEGIN SELECT RAISE(ABORT, 'balance_observation is append-only'); END;
CREATE TRIGGER balance_observation_no_replace BEFORE INSERT ON balance_observation
WHEN EXISTS (SELECT 1 FROM balance_observation WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'balance_observation is append-only'); END;

CREATE TRIGGER balance_observation_event_no_update BEFORE UPDATE ON balance_observation_event
BEGIN SELECT RAISE(ABORT, 'balance_observation_event is append-only'); END;
CREATE TRIGGER balance_observation_event_no_delete BEFORE DELETE ON balance_observation_event
BEGIN SELECT RAISE(ABORT, 'balance_observation_event is append-only'); END;
CREATE TRIGGER balance_observation_event_no_replace BEFORE INSERT ON balance_observation_event
WHEN EXISTS (SELECT 1 FROM balance_observation_event
             WHERE id = NEW.id
                OR (balance_observation_id = NEW.balance_observation_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'balance_observation_event is append-only'); END;
