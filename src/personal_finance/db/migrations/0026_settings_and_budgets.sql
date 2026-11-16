-- Ledger settings and budget plans stated by a person. Rules are in docs/decisions-m12-m21.md
-- D-067 G2, G4 and G7, and D-069 points 1, 2 and 6.

-- The keys a setting may have, seeded here and by later migrations only, so a new setting is
-- always a migration and never free text.
CREATE TABLE ledger_setting_key (
    setting_key  TEXT PRIMARY KEY CHECK (setting_key GLOB '[a-z]*' AND trim(setting_key) <> '')
) STRICT;

INSERT INTO ledger_setting_key (setting_key) VALUES ('household_timezone');

-- One value of a key. At most one is active per key, from its 'made' event until its 'undone'
-- event: changing a value is undo then set.
CREATE TABLE ledger_setting (
    id            TEXT PRIMARY KEY,
    setting_key   TEXT NOT NULL REFERENCES ledger_setting_key (setting_key),
    value         TEXT NOT NULL CHECK (trim(value) <> ''),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE ledger_setting_event (
    id          INTEGER PRIMARY KEY,
    setting_id  TEXT NOT NULL REFERENCES ledger_setting (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (setting_id, event)
) STRICT;

-- A budget plan: from a month on, the household's discretionary allowance, optionally split
-- among members by exact amounts and capped by category. It applies until a later active plan
-- takes over (point 2). A plan superseding another replaces it, D-048's chain.
-- corrected_closed_month marks a plan made with --correct-closed-month.
CREATE TABLE budget_plan (
    id                      TEXT PRIMARY KEY,
    effective_from          TEXT NOT NULL CHECK (effective_from GLOB
                                                 '[0-9][0-9][0-9][0-9]-[0-1][0-9]'
                                                 AND substr(effective_from, 6, 2)
                                                     BETWEEN '01' AND '12'),
    allowance_cents         INTEGER NOT NULL CHECK (allowance_cents >= 0),
    supersedes_id           TEXT REFERENCES budget_plan (id),
    corrected_closed_month  INTEGER NOT NULL CHECK (corrected_closed_month IN (0, 1)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE budget_plan_member_part (
    plan_id       TEXT NOT NULL REFERENCES budget_plan (id),
    member_id     INTEGER NOT NULL REFERENCES household_member (id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    PRIMARY KEY (plan_id, member_id)
) STRICT;

CREATE TABLE budget_plan_category (
    plan_id       TEXT NOT NULL REFERENCES budget_plan (id),
    category_id   INTEGER NOT NULL REFERENCES category (id),
    amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
    PRIMARY KEY (plan_id, category_id)
) STRICT;

CREATE TABLE budget_plan_event (
    id          INTEGER PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES budget_plan (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (plan_id, event)
) STRICT;

CREATE TRIGGER ledger_setting_key_no_update BEFORE UPDATE ON ledger_setting_key
BEGIN SELECT RAISE(ABORT, 'ledger_setting_key is append-only'); END;
CREATE TRIGGER ledger_setting_key_no_delete BEFORE DELETE ON ledger_setting_key
BEGIN SELECT RAISE(ABORT, 'ledger_setting_key is append-only'); END;
CREATE TRIGGER ledger_setting_key_no_replace BEFORE INSERT ON ledger_setting_key
WHEN EXISTS (SELECT 1 FROM ledger_setting_key WHERE setting_key = NEW.setting_key)
BEGIN SELECT RAISE(ABORT, 'ledger_setting_key is append-only'); END;

CREATE TRIGGER ledger_setting_no_update BEFORE UPDATE ON ledger_setting
BEGIN SELECT RAISE(ABORT, 'ledger_setting is append-only'); END;
CREATE TRIGGER ledger_setting_no_delete BEFORE DELETE ON ledger_setting
BEGIN SELECT RAISE(ABORT, 'ledger_setting is append-only'); END;
CREATE TRIGGER ledger_setting_no_replace BEFORE INSERT ON ledger_setting
WHEN EXISTS (SELECT 1 FROM ledger_setting WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'ledger_setting is append-only'); END;

CREATE TRIGGER ledger_setting_event_no_update BEFORE UPDATE ON ledger_setting_event
BEGIN SELECT RAISE(ABORT, 'ledger_setting_event is append-only'); END;
CREATE TRIGGER ledger_setting_event_no_delete BEFORE DELETE ON ledger_setting_event
BEGIN SELECT RAISE(ABORT, 'ledger_setting_event is append-only'); END;
CREATE TRIGGER ledger_setting_event_no_replace BEFORE INSERT ON ledger_setting_event
WHEN EXISTS (SELECT 1 FROM ledger_setting_event WHERE id = NEW.id OR (setting_id = NEW.setting_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'ledger_setting_event is append-only'); END;

CREATE TRIGGER budget_plan_no_update BEFORE UPDATE ON budget_plan
BEGIN SELECT RAISE(ABORT, 'budget_plan is append-only'); END;
CREATE TRIGGER budget_plan_no_delete BEFORE DELETE ON budget_plan
BEGIN SELECT RAISE(ABORT, 'budget_plan is append-only'); END;
CREATE TRIGGER budget_plan_no_replace BEFORE INSERT ON budget_plan
WHEN EXISTS (SELECT 1 FROM budget_plan WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'budget_plan is append-only'); END;

CREATE TRIGGER budget_plan_member_part_no_update BEFORE UPDATE ON budget_plan_member_part
BEGIN SELECT RAISE(ABORT, 'budget_plan_member_part is append-only'); END;
CREATE TRIGGER budget_plan_member_part_no_delete BEFORE DELETE ON budget_plan_member_part
BEGIN SELECT RAISE(ABORT, 'budget_plan_member_part is append-only'); END;
CREATE TRIGGER budget_plan_member_part_no_replace BEFORE INSERT ON budget_plan_member_part
WHEN EXISTS (SELECT 1 FROM budget_plan_member_part WHERE plan_id = NEW.plan_id
             AND member_id = NEW.member_id)
BEGIN SELECT RAISE(ABORT, 'budget_plan_member_part is append-only'); END;

CREATE TRIGGER budget_plan_category_no_update BEFORE UPDATE ON budget_plan_category
BEGIN SELECT RAISE(ABORT, 'budget_plan_category is append-only'); END;
CREATE TRIGGER budget_plan_category_no_delete BEFORE DELETE ON budget_plan_category
BEGIN SELECT RAISE(ABORT, 'budget_plan_category is append-only'); END;
CREATE TRIGGER budget_plan_category_no_replace BEFORE INSERT ON budget_plan_category
WHEN EXISTS (SELECT 1 FROM budget_plan_category WHERE plan_id = NEW.plan_id
             AND category_id = NEW.category_id)
BEGIN SELECT RAISE(ABORT, 'budget_plan_category is append-only'); END;

CREATE TRIGGER budget_plan_event_no_update BEFORE UPDATE ON budget_plan_event
BEGIN SELECT RAISE(ABORT, 'budget_plan_event is append-only'); END;
CREATE TRIGGER budget_plan_event_no_delete BEFORE DELETE ON budget_plan_event
BEGIN SELECT RAISE(ABORT, 'budget_plan_event is append-only'); END;
CREATE TRIGGER budget_plan_event_no_replace BEFORE INSERT ON budget_plan_event
WHEN EXISTS (SELECT 1 FROM budget_plan_event WHERE id = NEW.id OR (plan_id = NEW.plan_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'budget_plan_event is append-only'); END;
