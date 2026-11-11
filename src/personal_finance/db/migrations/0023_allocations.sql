-- Allocations stated by a person on one transaction, dividing its effective amount among household
-- members. Rules are in docs/decisions.md D-065.

-- One allocation, anchored on the records of its transaction when it was made, as a categorization
-- is (D-063). target_transaction_id is a snapshot and has no foreign key. Its value is canonical:
-- the kind, a colon, then its parts as member=value sorted by member ID, joined by commas, so two
-- allocations agree exactly when their values are equal. The parts below say the same, checked when
-- the allocation is made.
CREATE TABLE allocation_statement (
    id                        TEXT PRIMARY KEY,
    account_id                TEXT NOT NULL REFERENCES account (id),
    allocation                TEXT NOT NULL
                              CHECK (allocation GLOB 'member:*' OR allocation = 'shared:'
                                     OR allocation GLOB 'percent:*' OR allocation GLOB 'amount:*'),
    target_transaction_id     TEXT NOT NULL,
    target_revision           TEXT NOT NULL,
    supersedes_allocation_id  TEXT REFERENCES allocation_statement (id),
    created_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX allocation_statement_account ON allocation_statement (account_id);

-- Each part: basis points for member and percent, magnitudes in cents for amount. shared has none,
-- since the household share active when read divides it.
CREATE TABLE allocation_statement_part (
    allocation_id  TEXT NOT NULL REFERENCES allocation_statement (id),
    member_id      INTEGER NOT NULL REFERENCES household_member (id),
    value          INTEGER NOT NULL CHECK (value > 0),
    PRIMARY KEY (allocation_id, member_id)
) STRICT;

CREATE TABLE allocation_statement_record (
    allocation_id     TEXT NOT NULL REFERENCES allocation_statement (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (allocation_id, source_record_id)
) STRICT;

CREATE INDEX allocation_statement_record_source ON allocation_statement_record (source_record_id);

-- An allocation is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE allocation_statement_event (
    id             INTEGER PRIMARY KEY,
    allocation_id  TEXT NOT NULL REFERENCES allocation_statement (id),
    event          TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (allocation_id, event)
) STRICT;

-- When made, the parts must say what the canonical value says, and fit its kind: one member at
-- 10,000, none for shared, two or more percentages summing to 10,000, or one or more amounts.
CREATE TRIGGER allocation_statement_parts_fit BEFORE INSERT ON allocation_statement_event
WHEN NEW.event = 'made'
 AND (SELECT statement.allocation IS NOT (
                 substr(statement.allocation, 1, instr(statement.allocation, ':'))
                 || COALESCE((SELECT group_concat(part.member_id || '=' || part.value, ','
                                                  ORDER BY part.member_id)
                              FROM allocation_statement_part part
                              WHERE part.allocation_id = statement.id), ''))
             OR CASE substr(statement.allocation, 1, instr(statement.allocation, ':'))
                    WHEN 'member:' THEN (SELECT COUNT(*) <> 1 OR SUM(value) <> 10000
                                         FROM allocation_statement_part
                                         WHERE allocation_id = statement.id)
                    WHEN 'shared:' THEN 0
                    WHEN 'percent:' THEN (SELECT COUNT(*) < 2 OR SUM(value) <> 10000
                                          FROM allocation_statement_part
                                          WHERE allocation_id = statement.id)
                    ELSE (SELECT COUNT(*) < 1 FROM allocation_statement_part
                          WHERE allocation_id = statement.id)
                END
      FROM allocation_statement statement WHERE statement.id = NEW.allocation_id)
BEGIN SELECT RAISE(ABORT, 'an allocation''s parts must match its value and fit its kind'); END;

CREATE TRIGGER allocation_statement_part_before_made BEFORE INSERT ON allocation_statement_part
WHEN EXISTS (SELECT 1 FROM allocation_statement_event WHERE allocation_id = NEW.allocation_id)
BEGIN SELECT RAISE(ABORT, 'allocation_statement_part is append-only'); END;

CREATE TRIGGER allocation_statement_supersedes_same_account BEFORE INSERT ON allocation_statement
WHEN NEW.supersedes_allocation_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM allocation_statement old
                 WHERE old.id = NEW.supersedes_allocation_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'an allocation can only supersede one of its own account'); END;

CREATE TRIGGER allocation_statement_no_update BEFORE UPDATE ON allocation_statement
BEGIN SELECT RAISE(ABORT, 'allocation_statement is append-only'); END;
CREATE TRIGGER allocation_statement_no_delete BEFORE DELETE ON allocation_statement
BEGIN SELECT RAISE(ABORT, 'allocation_statement is append-only'); END;
CREATE TRIGGER allocation_statement_no_replace BEFORE INSERT ON allocation_statement
WHEN EXISTS (SELECT 1 FROM allocation_statement WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'allocation_statement is append-only'); END;

CREATE TRIGGER allocation_statement_part_no_update BEFORE UPDATE ON allocation_statement_part
BEGIN SELECT RAISE(ABORT, 'allocation_statement_part is append-only'); END;
CREATE TRIGGER allocation_statement_part_no_delete BEFORE DELETE ON allocation_statement_part
BEGIN SELECT RAISE(ABORT, 'allocation_statement_part is append-only'); END;
CREATE TRIGGER allocation_statement_part_no_replace BEFORE INSERT ON allocation_statement_part
WHEN EXISTS (SELECT 1 FROM allocation_statement_part
             WHERE allocation_id = NEW.allocation_id AND member_id = NEW.member_id)
BEGIN SELECT RAISE(ABORT, 'allocation_statement_part is append-only'); END;

CREATE TRIGGER allocation_statement_record_no_update BEFORE UPDATE ON allocation_statement_record
BEGIN SELECT RAISE(ABORT, 'allocation_statement_record is append-only'); END;
CREATE TRIGGER allocation_statement_record_no_delete BEFORE DELETE ON allocation_statement_record
BEGIN SELECT RAISE(ABORT, 'allocation_statement_record is append-only'); END;
CREATE TRIGGER allocation_statement_record_no_replace BEFORE INSERT ON allocation_statement_record
WHEN EXISTS (SELECT 1 FROM allocation_statement_record
             WHERE allocation_id = NEW.allocation_id
               AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'allocation_statement_record is append-only'); END;

CREATE TRIGGER allocation_statement_event_no_update BEFORE UPDATE ON allocation_statement_event
BEGIN SELECT RAISE(ABORT, 'allocation_statement_event is append-only'); END;
CREATE TRIGGER allocation_statement_event_no_delete BEFORE DELETE ON allocation_statement_event
BEGIN SELECT RAISE(ABORT, 'allocation_statement_event is append-only'); END;
CREATE TRIGGER allocation_statement_event_no_replace BEFORE INSERT ON allocation_statement_event
WHEN EXISTS (SELECT 1 FROM allocation_statement_event
             WHERE id = NEW.id
                OR (allocation_id = NEW.allocation_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'allocation_statement_event is append-only'); END;

-- Derived, never edited by hand: the outcome of active allocations on each live transaction they
-- reach, the applied value canonical as above. A transaction with no row is one no allocation
-- reaches, so the account's default applies. Rewritten wherever transaction_category is. A retired
-- transaction takes its row with it.
CREATE TABLE transaction_allocation (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                   'amount_differs')),
    allocation      TEXT,
    CHECK ((state = 'applied') = (allocation IS NOT NULL))
) STRICT;
