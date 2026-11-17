-- Fund consumption stated by a person on one transaction, and the tax reserve's releases. Rules are
-- in docs/decisions-m12-m21.md D-070 points 5 to 7.

-- One consumption: "this spending transaction is paid from this fund", anchored on the records of
-- its transaction when it was made, as a categorization is (D-063). target_transaction_id is a
-- snapshot and has no foreign key. Two consumptions agree exactly when they name the same fund.
CREATE TABLE fund_consumption (
    id                         TEXT PRIMARY KEY,
    account_id                 TEXT NOT NULL REFERENCES account (id),
    fund_id                    TEXT NOT NULL REFERENCES fund (id),
    target_transaction_id      TEXT NOT NULL,
    target_revision            TEXT NOT NULL,
    supersedes_consumption_id  TEXT REFERENCES fund_consumption (id),
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX fund_consumption_account ON fund_consumption (account_id);

CREATE TABLE fund_consumption_record (
    consumption_id    TEXT NOT NULL REFERENCES fund_consumption (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (consumption_id, source_record_id)
) STRICT;

CREATE INDEX fund_consumption_record_source ON fund_consumption_record (source_record_id);

-- A consumption is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE fund_consumption_event (
    id              INTEGER PRIMARY KEY,
    consumption_id  TEXT NOT NULL REFERENCES fund_consumption (id),
    event           TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (consumption_id, event)
) STRICT;

-- Only a goal, a reserve or the tax reserve is consumed (point 5).
CREATE TRIGGER fund_consumption_fund_kind BEFORE INSERT ON fund_consumption
WHEN NOT EXISTS (SELECT 1 FROM fund WHERE fund.id = NEW.fund_id
                 AND fund.kind IN ('goal', 'reserve', 'tax'))
BEGIN SELECT RAISE(ABORT, 'only a goal, a reserve or the tax reserve can be consumed'); END;

CREATE TRIGGER fund_consumption_supersedes_same_account BEFORE INSERT ON fund_consumption
WHEN NEW.supersedes_consumption_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM fund_consumption old
                 WHERE old.id = NEW.supersedes_consumption_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a consumption can only supersede one of its own account'); END;

-- A release of the tax reserve found too large (point 6): an amount on a date, active from 'made'
-- until 'undone'.
CREATE TABLE tax_reserve_release (
    id            TEXT PRIMARY KEY,
    fund_id       TEXT NOT NULL REFERENCES fund (id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents > 0),
    released_on   TEXT NOT NULL CHECK (date(released_on) IS released_on),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER tax_reserve_release_fund_kind BEFORE INSERT ON tax_reserve_release
WHEN NOT EXISTS (SELECT 1 FROM fund WHERE fund.id = NEW.fund_id AND fund.kind = 'tax')
BEGIN SELECT RAISE(ABORT, 'only the tax reserve is released'); END;

CREATE TABLE tax_reserve_release_event (
    id          INTEGER PRIMARY KEY,
    release_id  TEXT NOT NULL REFERENCES tax_reserve_release (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (release_id, event)
) STRICT;

CREATE TRIGGER fund_consumption_no_update BEFORE UPDATE ON fund_consumption
BEGIN SELECT RAISE(ABORT, 'fund_consumption is append-only'); END;
CREATE TRIGGER fund_consumption_no_delete BEFORE DELETE ON fund_consumption
BEGIN SELECT RAISE(ABORT, 'fund_consumption is append-only'); END;
CREATE TRIGGER fund_consumption_no_replace BEFORE INSERT ON fund_consumption
WHEN EXISTS (SELECT 1 FROM fund_consumption WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'fund_consumption is append-only'); END;

CREATE TRIGGER fund_consumption_record_no_update BEFORE UPDATE ON fund_consumption_record
BEGIN SELECT RAISE(ABORT, 'fund_consumption_record is append-only'); END;
CREATE TRIGGER fund_consumption_record_no_delete BEFORE DELETE ON fund_consumption_record
BEGIN SELECT RAISE(ABORT, 'fund_consumption_record is append-only'); END;
CREATE TRIGGER fund_consumption_record_no_replace BEFORE INSERT ON fund_consumption_record
WHEN EXISTS (SELECT 1 FROM fund_consumption_record
             WHERE consumption_id = NEW.consumption_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'fund_consumption_record is append-only'); END;

CREATE TRIGGER fund_consumption_event_no_update BEFORE UPDATE ON fund_consumption_event
BEGIN SELECT RAISE(ABORT, 'fund_consumption_event is append-only'); END;
CREATE TRIGGER fund_consumption_event_no_delete BEFORE DELETE ON fund_consumption_event
BEGIN SELECT RAISE(ABORT, 'fund_consumption_event is append-only'); END;
CREATE TRIGGER fund_consumption_event_no_replace BEFORE INSERT ON fund_consumption_event
WHEN EXISTS (SELECT 1 FROM fund_consumption_event
             WHERE id = NEW.id
                OR (consumption_id = NEW.consumption_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'fund_consumption_event is append-only'); END;

CREATE TRIGGER tax_reserve_release_no_update BEFORE UPDATE ON tax_reserve_release
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release is append-only'); END;
CREATE TRIGGER tax_reserve_release_no_delete BEFORE DELETE ON tax_reserve_release
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release is append-only'); END;
CREATE TRIGGER tax_reserve_release_no_replace BEFORE INSERT ON tax_reserve_release
WHEN EXISTS (SELECT 1 FROM tax_reserve_release WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release is append-only'); END;

CREATE TRIGGER tax_reserve_release_event_no_update BEFORE UPDATE ON tax_reserve_release_event
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release_event is append-only'); END;
CREATE TRIGGER tax_reserve_release_event_no_delete BEFORE DELETE ON tax_reserve_release_event
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release_event is append-only'); END;
CREATE TRIGGER tax_reserve_release_event_no_replace BEFORE INSERT ON tax_reserve_release_event
WHEN EXISTS (SELECT 1 FROM tax_reserve_release_event
             WHERE id = NEW.id OR (release_id = NEW.release_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'tax_reserve_release_event is append-only'); END;

-- Derived, never edited by hand: the outcome of active consumptions on each live transaction they
-- reach. not_spending is a single agreeing consumption on a transaction no longer in D-056's
-- spending group. The consumed amount is not stored: it turns on the fund's assignments, and is
-- computed where it is read (point 5). Rewritten wherever transaction_category is. A retired
-- transaction takes its row with it.
CREATE TABLE transaction_fund_consumption (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                   'not_spending')),
    fund_id         TEXT REFERENCES fund (id),
    CHECK ((state = 'applied') = (fund_id IS NOT NULL))
) STRICT;
