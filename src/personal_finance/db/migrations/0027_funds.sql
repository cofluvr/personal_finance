-- Funds stated by a person, their dated terms, their assignments to accounts, and the priority
-- list. Rules are in docs/decisions-m12-m21.md D-067 G2, G4 and G7, and D-070 points 1 to 4.

-- One fund: a goal, the emergency fund, a reserve or the tax reserve. Its name and kind never
-- change: a change of terms is a new fund_terms row, and anything else is undo then add.
CREATE TABLE fund (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL CHECK (trim(name) <> ''),
    kind        TEXT NOT NULL CHECK (kind IN ('goal', 'emergency', 'reserve', 'tax')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

-- A fund's dated terms. A later row takes over from effective_from, so a month before it keeps
-- its terms (G7). shape says which columns hold the terms:
--   monthly    amount_cents a month (a goal)
--   percent    basis_points of baseline income (a goal) or of tax-eligible income (the tax fund)
--   target_by  amount_cents by the end of by_month (a goal)
--   minimum    amount_cents held (the emergency fund)
--   months     month_count months of fixed commitments held (the emergency fund)
--   due        amount_cents by due_date (a reserve)
--   recurring  amount_cents by each date of an annual or every-N-months cadence (a reserve)
CREATE TABLE fund_terms (
    id               INTEGER PRIMARY KEY,
    fund_id          TEXT NOT NULL REFERENCES fund (id),
    effective_from   TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    shape            TEXT NOT NULL CHECK (shape IN ('monthly', 'percent', 'target_by', 'minimum',
                                                    'months', 'due', 'recurring')),
    amount_cents     INTEGER CHECK (amount_cents IS NULL OR amount_cents > 0),
    basis_points     INTEGER CHECK (basis_points IS NULL OR basis_points BETWEEN 1 AND 10000),
    by_month         TEXT CHECK (by_month IS NULL OR (by_month GLOB
                                                      '[0-9][0-9][0-9][0-9]-[0-1][0-9]'
                                                      AND substr(by_month, 6, 2)
                                                          BETWEEN '01' AND '12')),
    month_count      INTEGER CHECK (month_count IS NULL OR month_count BETWEEN 1 AND 120),
    due_date         TEXT CHECK (due_date IS NULL OR date(due_date) IS due_date),
    cadence          TEXT CHECK (cadence IS NULL OR cadence IN ('annual', 'every_months')),
    first_day        INTEGER CHECK (first_day IS NULL OR first_day BETWEEN 1 AND 31),
    interval_months  INTEGER CHECK (interval_months IS NULL OR interval_months >= 2),
    anchor           TEXT CHECK (anchor IS NULL OR date(anchor) IS anchor),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (fund_id, effective_from),
    CHECK ((amount_cents IS NOT NULL) = (shape IN ('monthly', 'target_by', 'minimum', 'due',
                                                   'recurring'))),
    CHECK ((basis_points IS NOT NULL) = (shape = 'percent')),
    CHECK ((by_month IS NOT NULL) = (shape = 'target_by')),
    CHECK ((month_count IS NOT NULL) = (shape = 'months')),
    CHECK ((due_date IS NOT NULL) = (shape = 'due')),
    CHECK ((cadence IS NOT NULL) = (shape = 'recurring')),
    CHECK ((first_day IS NOT NULL) = (shape = 'recurring')),
    CHECK ((anchor IS NOT NULL) = (shape = 'recurring')),
    CHECK ((interval_months IS NOT NULL) = (cadence IS 'every_months'))
) STRICT;

-- Each kind takes its own shapes only.
CREATE TRIGGER fund_terms_shape_of_kind BEFORE INSERT ON fund_terms
WHEN NOT EXISTS (
    SELECT 1 FROM fund WHERE fund.id = NEW.fund_id AND (
        (fund.kind = 'goal' AND NEW.shape IN ('monthly', 'percent', 'target_by'))
        OR (fund.kind = 'emergency' AND NEW.shape IN ('minimum', 'months'))
        OR (fund.kind = 'reserve' AND NEW.shape IN ('due', 'recurring'))
        OR (fund.kind = 'tax' AND NEW.shape = 'percent')))
BEGIN SELECT RAISE(ABORT, 'fund_terms shape does not belong to its fund''s kind'); END;

-- A fund is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE fund_event (
    id          INTEGER PRIMARY KEY,
    fund_id     TEXT NOT NULL REFERENCES fund (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (fund_id, event)
) STRICT;

-- "amount_cents of this account's balance belongs to this fund" (point 2). At most one is active
-- per fund and account, from 'made' until 'undone': changing one is undo then assign.
CREATE TABLE fund_assignment (
    id            TEXT PRIMARY KEY,
    fund_id       TEXT NOT NULL REFERENCES fund (id),
    account_id    TEXT NOT NULL REFERENCES account (id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents > 0),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE fund_assignment_event (
    id             INTEGER PRIMARY KEY,
    assignment_id  TEXT NOT NULL REFERENCES fund_assignment (id),
    event          TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assignment_id, event)
) STRICT;

-- One priority list (point 4): the list made last applies, replacing every earlier one, which
-- stays on record. A list may be empty, so the event row is the list itself.
CREATE TABLE fund_priority_event (
    id          INTEGER PRIMARY KEY,
    list_id     TEXT NOT NULL UNIQUE,
    event       TEXT NOT NULL CHECK (event = 'made'),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE fund_priority (
    list_id   TEXT NOT NULL REFERENCES fund_priority_event (list_id),
    position  INTEGER NOT NULL CHECK (position >= 1),
    fund_id   TEXT NOT NULL REFERENCES fund (id),
    PRIMARY KEY (list_id, position),
    UNIQUE (list_id, fund_id)
) STRICT;

CREATE TRIGGER fund_no_update BEFORE UPDATE ON fund
BEGIN SELECT RAISE(ABORT, 'fund is append-only'); END;
CREATE TRIGGER fund_no_delete BEFORE DELETE ON fund
BEGIN SELECT RAISE(ABORT, 'fund is append-only'); END;
CREATE TRIGGER fund_no_replace BEFORE INSERT ON fund
WHEN EXISTS (SELECT 1 FROM fund WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'fund is append-only'); END;

CREATE TRIGGER fund_terms_no_update BEFORE UPDATE ON fund_terms
BEGIN SELECT RAISE(ABORT, 'fund_terms is append-only'); END;
CREATE TRIGGER fund_terms_no_delete BEFORE DELETE ON fund_terms
BEGIN SELECT RAISE(ABORT, 'fund_terms is append-only'); END;
CREATE TRIGGER fund_terms_no_replace BEFORE INSERT ON fund_terms
WHEN EXISTS (SELECT 1 FROM fund_terms
             WHERE id = NEW.id OR (fund_id = NEW.fund_id AND effective_from = NEW.effective_from))
BEGIN SELECT RAISE(ABORT, 'fund_terms is append-only'); END;

CREATE TRIGGER fund_event_no_update BEFORE UPDATE ON fund_event
BEGIN SELECT RAISE(ABORT, 'fund_event is append-only'); END;
CREATE TRIGGER fund_event_no_delete BEFORE DELETE ON fund_event
BEGIN SELECT RAISE(ABORT, 'fund_event is append-only'); END;
CREATE TRIGGER fund_event_no_replace BEFORE INSERT ON fund_event
WHEN EXISTS (SELECT 1 FROM fund_event
             WHERE id = NEW.id OR (fund_id = NEW.fund_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'fund_event is append-only'); END;

CREATE TRIGGER fund_assignment_no_update BEFORE UPDATE ON fund_assignment
BEGIN SELECT RAISE(ABORT, 'fund_assignment is append-only'); END;
CREATE TRIGGER fund_assignment_no_delete BEFORE DELETE ON fund_assignment
BEGIN SELECT RAISE(ABORT, 'fund_assignment is append-only'); END;
CREATE TRIGGER fund_assignment_no_replace BEFORE INSERT ON fund_assignment
WHEN EXISTS (SELECT 1 FROM fund_assignment WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'fund_assignment is append-only'); END;

CREATE TRIGGER fund_assignment_event_no_update BEFORE UPDATE ON fund_assignment_event
BEGIN SELECT RAISE(ABORT, 'fund_assignment_event is append-only'); END;
CREATE TRIGGER fund_assignment_event_no_delete BEFORE DELETE ON fund_assignment_event
BEGIN SELECT RAISE(ABORT, 'fund_assignment_event is append-only'); END;
CREATE TRIGGER fund_assignment_event_no_replace BEFORE INSERT ON fund_assignment_event
WHEN EXISTS (SELECT 1 FROM fund_assignment_event
             WHERE id = NEW.id OR (assignment_id = NEW.assignment_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'fund_assignment_event is append-only'); END;

CREATE TRIGGER fund_priority_event_no_update BEFORE UPDATE ON fund_priority_event
BEGIN SELECT RAISE(ABORT, 'fund_priority_event is append-only'); END;
CREATE TRIGGER fund_priority_event_no_delete BEFORE DELETE ON fund_priority_event
BEGIN SELECT RAISE(ABORT, 'fund_priority_event is append-only'); END;
CREATE TRIGGER fund_priority_event_no_replace BEFORE INSERT ON fund_priority_event
WHEN EXISTS (SELECT 1 FROM fund_priority_event WHERE id = NEW.id OR list_id = NEW.list_id)
BEGIN SELECT RAISE(ABORT, 'fund_priority_event is append-only'); END;

CREATE TRIGGER fund_priority_no_update BEFORE UPDATE ON fund_priority
BEGIN SELECT RAISE(ABORT, 'fund_priority is append-only'); END;
CREATE TRIGGER fund_priority_no_delete BEFORE DELETE ON fund_priority
BEGIN SELECT RAISE(ABORT, 'fund_priority is append-only'); END;
CREATE TRIGGER fund_priority_no_replace BEFORE INSERT ON fund_priority
WHEN EXISTS (SELECT 1 FROM fund_priority
             WHERE (list_id = NEW.list_id AND position = NEW.position)
                OR (list_id = NEW.list_id AND fund_id = NEW.fund_id))
BEGIN SELECT RAISE(ABORT, 'fund_priority is append-only'); END;
