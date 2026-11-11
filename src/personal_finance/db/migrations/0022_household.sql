-- Household members, the household share and each account's attribution. Rules are in
-- docs/decisions.md D-065.

-- Append-only: no rename or removal, so every attribution keeps meaning what it meant. Members are
-- ordered by ID, the order added, which decides who takes a leftover cent. shared and unattributed
-- are what an attribution can be besides a member, so no member takes either name.
CREATE TABLE household_member (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
                CHECK (trim(name) <> '' AND name NOT IN ('shared', 'unattributed')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER household_member_no_update BEFORE UPDATE ON household_member
BEGIN SELECT RAISE(ABORT, 'household_member is append-only'); END;
CREATE TRIGGER household_member_no_delete BEFORE DELETE ON household_member
BEGIN SELECT RAISE(ABORT, 'household_member is append-only'); END;
CREATE TRIGGER household_member_no_replace BEFORE INSERT ON household_member
WHEN EXISTS (SELECT 1 FROM household_member WHERE id = NEW.id OR name = NEW.name)
BEGIN SELECT RAISE(ABORT, 'household_member is append-only'); END;

-- How shared divides: two or more members, each in basis points above zero, summing to 10,000.
-- The parts are written before the share's 'made' event, which checks them.
CREATE TABLE household_share (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE household_share_part (
    share_id      TEXT NOT NULL REFERENCES household_share (id),
    member_id     INTEGER NOT NULL REFERENCES household_member (id),
    basis_points  INTEGER NOT NULL CHECK (basis_points BETWEEN 1 AND 9999),
    PRIMARY KEY (share_id, member_id)
) STRICT;

-- A share is active from 'made' until an 'undone' event, and stays on record after it. One is
-- active at a time.
CREATE TABLE household_share_event (
    id          INTEGER PRIMARY KEY,
    share_id    TEXT NOT NULL REFERENCES household_share (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (share_id, event)
) STRICT;

CREATE TRIGGER household_share_parts_sum BEFORE INSERT ON household_share_event
WHEN NEW.event = 'made'
 AND ((SELECT COUNT(*) FROM household_share_part WHERE share_id = NEW.share_id) < 2
      OR (SELECT SUM(basis_points) FROM household_share_part WHERE share_id = NEW.share_id)
         <> 10000)
BEGIN SELECT RAISE(ABORT, 'a household share needs two or more parts summing to 10000'); END;

CREATE TRIGGER household_share_one_active BEFORE INSERT ON household_share_event
WHEN NEW.event = 'made'
 AND EXISTS (SELECT 1 FROM household_share_event made
             WHERE made.event = 'made'
               AND NOT EXISTS (SELECT 1 FROM household_share_event undone
                               WHERE undone.share_id = made.share_id AND undone.event = 'undone'))
BEGIN SELECT RAISE(ABORT, 'a household share is active already'); END;

CREATE TRIGGER household_share_part_before_made BEFORE INSERT ON household_share_part
WHEN EXISTS (SELECT 1 FROM household_share_event WHERE share_id = NEW.share_id)
BEGIN SELECT RAISE(ABORT, 'household_share_part is append-only'); END;

CREATE TRIGGER household_share_no_update BEFORE UPDATE ON household_share
BEGIN SELECT RAISE(ABORT, 'household_share is append-only'); END;
CREATE TRIGGER household_share_no_delete BEFORE DELETE ON household_share
BEGIN SELECT RAISE(ABORT, 'household_share is append-only'); END;
CREATE TRIGGER household_share_no_replace BEFORE INSERT ON household_share
WHEN EXISTS (SELECT 1 FROM household_share WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'household_share is append-only'); END;

CREATE TRIGGER household_share_part_no_update BEFORE UPDATE ON household_share_part
BEGIN SELECT RAISE(ABORT, 'household_share_part is append-only'); END;
CREATE TRIGGER household_share_part_no_delete BEFORE DELETE ON household_share_part
BEGIN SELECT RAISE(ABORT, 'household_share_part is append-only'); END;
CREATE TRIGGER household_share_part_no_replace BEFORE INSERT ON household_share_part
WHEN EXISTS (SELECT 1 FROM household_share_part
             WHERE share_id = NEW.share_id AND member_id = NEW.member_id)
BEGIN SELECT RAISE(ABORT, 'household_share_part is append-only'); END;

CREATE TRIGGER household_share_event_no_update BEFORE UPDATE ON household_share_event
BEGIN SELECT RAISE(ABORT, 'household_share_event is append-only'); END;
CREATE TRIGGER household_share_event_no_delete BEFORE DELETE ON household_share_event
BEGIN SELECT RAISE(ABORT, 'household_share_event is append-only'); END;
CREATE TRIGGER household_share_event_no_replace BEFORE INSERT ON household_share_event
WHEN EXISTS (SELECT 1 FROM household_share_event
             WHERE id = NEW.id OR (share_id = NEW.share_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'household_share_event is append-only'); END;

-- Each account's default: one member, or shared where member_id is NULL. It binds no records, so it
-- reaches every transaction of the account, imported before or after it.
CREATE TABLE account_attribution (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES account (id),
    member_id   INTEGER REFERENCES household_member (id),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

-- An attribution is active from 'made' until an 'undone' event. One is active per account.
CREATE TABLE account_attribution_event (
    id              INTEGER PRIMARY KEY,
    attribution_id  TEXT NOT NULL REFERENCES account_attribution (id),
    event           TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (attribution_id, event)
) STRICT;

CREATE TRIGGER account_attribution_one_active BEFORE INSERT ON account_attribution_event
WHEN NEW.event = 'made'
 AND EXISTS (SELECT 1 FROM account_attribution_event made
             JOIN account_attribution other ON other.id = made.attribution_id
             WHERE made.event = 'made'
               AND other.account_id = (SELECT account_id FROM account_attribution
                                       WHERE id = NEW.attribution_id)
               AND NOT EXISTS (SELECT 1 FROM account_attribution_event undone
                               WHERE undone.attribution_id = made.attribution_id
                                 AND undone.event = 'undone'))
BEGIN SELECT RAISE(ABORT, 'this account has an active attribution already'); END;

CREATE TRIGGER account_attribution_no_update BEFORE UPDATE ON account_attribution
BEGIN SELECT RAISE(ABORT, 'account_attribution is append-only'); END;
CREATE TRIGGER account_attribution_no_delete BEFORE DELETE ON account_attribution
BEGIN SELECT RAISE(ABORT, 'account_attribution is append-only'); END;
CREATE TRIGGER account_attribution_no_replace BEFORE INSERT ON account_attribution
WHEN EXISTS (SELECT 1 FROM account_attribution WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'account_attribution is append-only'); END;

CREATE TRIGGER account_attribution_event_no_update BEFORE UPDATE ON account_attribution_event
BEGIN SELECT RAISE(ABORT, 'account_attribution_event is append-only'); END;
CREATE TRIGGER account_attribution_event_no_delete BEFORE DELETE ON account_attribution_event
BEGIN SELECT RAISE(ABORT, 'account_attribution_event is append-only'); END;
CREATE TRIGGER account_attribution_event_no_replace BEFORE INSERT ON account_attribution_event
WHEN EXISTS (SELECT 1 FROM account_attribution_event
             WHERE id = NEW.id OR (attribution_id = NEW.attribution_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'account_attribution_event is append-only'); END;
