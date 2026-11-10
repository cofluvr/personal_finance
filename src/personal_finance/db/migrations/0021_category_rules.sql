-- Category rules stated by a person, and the category each gives spending. Rules are in
-- docs/decisions.md D-064.

-- One rule: spending whose effective description contains description_contains, both normalized
-- under normalization_version, takes category_id, narrowed by an account, a spending type and a
-- first date where given. It binds no records, so it reaches transactions imported after it.
CREATE TABLE category_rule (
    id                     TEXT PRIMARY KEY,
    account_id             TEXT REFERENCES account (id),
    category_id            INTEGER NOT NULL REFERENCES category (id),
    description_contains   TEXT NOT NULL CHECK (trim(description_contains) <> ''),
    normalization_version  INTEGER NOT NULL CHECK (normalization_version >= 1),
    financial_type         TEXT CHECK (financial_type IS NULL
                                       OR financial_type IN ('purchase', 'fee', 'interest',
                                                             'refund')),
    from_date              TEXT CHECK (from_date IS NULL OR date(from_date) IS from_date),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

-- A rule is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE category_rule_event (
    id          INTEGER PRIMARY KEY,
    rule_id     TEXT NOT NULL REFERENCES category_rule (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (rule_id, event)
) STRICT;

CREATE TRIGGER category_rule_no_update BEFORE UPDATE ON category_rule
BEGIN SELECT RAISE(ABORT, 'category_rule is append-only'); END;
CREATE TRIGGER category_rule_no_delete BEFORE DELETE ON category_rule
BEGIN SELECT RAISE(ABORT, 'category_rule is append-only'); END;
CREATE TRIGGER category_rule_no_replace BEFORE INSERT ON category_rule
WHEN EXISTS (SELECT 1 FROM category_rule WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'category_rule is append-only'); END;

CREATE TRIGGER category_rule_event_no_update BEFORE UPDATE ON category_rule_event
BEGIN SELECT RAISE(ABORT, 'category_rule_event is append-only'); END;
CREATE TRIGGER category_rule_event_no_delete BEFORE DELETE ON category_rule_event
BEGIN SELECT RAISE(ABORT, 'category_rule_event is append-only'); END;
CREATE TRIGGER category_rule_event_no_replace BEFORE INSERT ON category_rule_event
WHEN EXISTS (SELECT 1 FROM category_rule_event
             WHERE id = NEW.id OR (rule_id = NEW.rule_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'category_rule_event is append-only'); END;

-- Derived, never edited by hand: the outcome of active rules on each spending transaction no
-- person's categorization reaches. A transaction with no row is one no rule reaches. Rewritten
-- whole wherever transaction_category is. A retired transaction takes its row with it.
CREATE TABLE transaction_rule_category (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'rule_conflict')),
    category_id     INTEGER REFERENCES category (id),
    CHECK ((state = 'applied') = (category_id IS NOT NULL))
) STRICT;
