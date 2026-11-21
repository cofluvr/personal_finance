-- Account links: a loan subaccount under an aggregate loan account, so net worth counts the debt
-- once. Rules are in docs/decisions-m12-m21.md D-071 point 2.

-- One link, active from 'made' until 'undone'. Changing one is undo then link. One level deep and
-- one aggregate per subaccount are checked under the write lock (G3), since they turn on which
-- links are active.
CREATE TABLE account_link (
    id              TEXT PRIMARY KEY,
    subaccount_id   TEXT NOT NULL REFERENCES account (id),
    aggregate_id    TEXT NOT NULL REFERENCES account (id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (subaccount_id <> aggregate_id)
) STRICT;

CREATE INDEX account_link_aggregate ON account_link (aggregate_id);

-- Both sides are loans.
CREATE TRIGGER account_link_loans_only BEFORE INSERT ON account_link
WHEN NOT EXISTS (SELECT 1 FROM account WHERE id = NEW.subaccount_id AND account_type = 'loan')
  OR NOT EXISTS (SELECT 1 FROM account WHERE id = NEW.aggregate_id AND account_type = 'loan')
BEGIN SELECT RAISE(ABORT, 'only a loan account links to an aggregate loan account'); END;

CREATE TABLE account_link_event (
    id          INTEGER PRIMARY KEY,
    link_id     TEXT NOT NULL REFERENCES account_link (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (link_id, event)
) STRICT;

CREATE TRIGGER account_link_no_update BEFORE UPDATE ON account_link
BEGIN SELECT RAISE(ABORT, 'account_link is append-only'); END;
CREATE TRIGGER account_link_no_delete BEFORE DELETE ON account_link
BEGIN SELECT RAISE(ABORT, 'account_link is append-only'); END;
CREATE TRIGGER account_link_no_replace BEFORE INSERT ON account_link
WHEN EXISTS (SELECT 1 FROM account_link WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'account_link is append-only'); END;

CREATE TRIGGER account_link_event_no_update BEFORE UPDATE ON account_link_event
BEGIN SELECT RAISE(ABORT, 'account_link_event is append-only'); END;
CREATE TRIGGER account_link_event_no_delete BEFORE DELETE ON account_link_event
BEGIN SELECT RAISE(ABORT, 'account_link_event is append-only'); END;
CREATE TRIGGER account_link_event_no_replace BEFORE INSERT ON account_link_event
WHEN EXISTS (SELECT 1 FROM account_link_event
             WHERE id = NEW.id OR (link_id = NEW.link_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'account_link_event is append-only'); END;
