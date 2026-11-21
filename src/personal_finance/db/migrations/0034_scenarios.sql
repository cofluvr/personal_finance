-- Financial scenarios: named alternatives to the active plan, their dated inputs, and the
-- promotions that turn confirmed inputs into planning entries. Rules are in
-- docs/decisions-m12-m21.md D-074 and its M18 slice plans. Nothing here reaches a transaction,
-- and no ledger table changes (G1): the baseline is the active plan, read live, never copied.

-- A scenario: a name and whether uncertain inputs count. IDs identify, so names may repeat.
CREATE TABLE scenario (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL CHECK (trim(name) = name AND name <> ''),
    include_uncertain  INTEGER NOT NULL CHECK (include_uncertain IN (0, 1)),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE scenario_event (
    id           INTEGER PRIMARY KEY,
    scenario_id  TEXT NOT NULL REFERENCES scenario (id),
    event        TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (scenario_id, event)
) STRICT;

-- One dated input with PRD §15's six distinctions: the amount (money out positive, signed by
-- kind), the dates (from, and an optional inclusive to), once or a cadence, the entry it
-- replaces or none, confirmed or uncertain, and take-home or gross. Each kind's own options are
-- nullable columns, present exactly where the kind takes them. A home purchase's amount is its
-- price, and a borrowing's its proceeds.
CREATE TABLE scenario_input (
    id                      TEXT PRIMARY KEY,
    scenario_id             TEXT NOT NULL REFERENCES scenario (id),
    kind                    TEXT NOT NULL CHECK (kind IN ('income', 'bonus', 'expense',
                                                          'annual_expense', 'purchase',
                                                          'home_purchase', 'loan_payoff',
                                                          'borrowing')),
    amount_cents            INTEGER NOT NULL CHECK (amount_cents >= 0),
    from_date               TEXT NOT NULL CHECK (date(from_date) IS from_date),
    to_date                 TEXT CHECK (to_date IS NULL
                                        OR (date(to_date) IS to_date AND to_date >= from_date)),
    -- 'once', or the cadence as a person types it (D-068): monthly:D, biweekly, annual:MM-DD...
    cadence                 TEXT NOT NULL CHECK (cadence <> ''),
    anchor                  TEXT CHECK (anchor IS NULL OR date(anchor) IS anchor),
    replaces_kind           TEXT CHECK (replaces_kind IS NULL
                                        OR replaces_kind IN ('income_source',
                                                             'recurring_obligation', 'fund')),
    replaces_id             TEXT,
    uncertain               INTEGER NOT NULL CHECK (uncertain IN (0, 1)),
    gross                   INTEGER NOT NULL CHECK (gross IN (0, 1)),
    take_home_basis_points  INTEGER CHECK (take_home_basis_points IS NULL
                                           OR take_home_basis_points BETWEEN 100 AND 10000),
    down_payment_cents      INTEGER CHECK (down_payment_cents IS NULL OR down_payment_cents >= 0),
    closing_costs_cents     INTEGER CHECK (closing_costs_cents IS NULL
                                           OR closing_costs_cents >= 0),
    ownership_costs_cents   INTEGER CHECK (ownership_costs_cents IS NULL
                                           OR ownership_costs_cents >= 0),
    loan_rate_millionths    INTEGER CHECK (loan_rate_millionths IS NULL
                                           OR loan_rate_millionths BETWEEN 0 AND 100000000),
    loan_months             INTEGER CHECK (loan_months IS NULL OR loan_months BETWEEN 1 AND 600),
    -- A loan payoff's loan: the account's terms when it was stated.
    loan_terms_id           TEXT REFERENCES loan_terms (id),
    -- Where an additional recurring income or expense would be promoted to, both or neither.
    account_id              TEXT REFERENCES account (id),
    match_text              TEXT CHECK (match_text IS NULL OR trim(match_text) <> ''),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((replaces_kind IS NULL) = (replaces_id IS NULL)),
    CHECK ((cadence = 'once') = (kind IN ('bonus', 'purchase', 'home_purchase', 'loan_payoff',
                                          'borrowing'))),
    CHECK (cadence = 'once' OR kind <> 'annual_expense' OR cadence GLOB 'annual:*'),
    CHECK (cadence <> 'once' OR (to_date IS NULL AND anchor IS NULL)),
    CHECK (CASE kind
               WHEN 'income' THEN replaces_kind IS NULL OR replaces_kind = 'income_source'
               WHEN 'expense' THEN replaces_kind IS NULL OR replaces_kind = 'recurring_obligation'
               WHEN 'annual_expense' THEN replaces_kind IS NULL OR replaces_kind = 'fund'
               ELSE replaces_kind IS NULL
           END),
    CHECK (gross = (take_home_basis_points IS NOT NULL)),
    CHECK (gross = 0 OR kind IN ('income', 'bonus')),
    CHECK ((kind = 'home_purchase') = (down_payment_cents IS NOT NULL)),
    CHECK ((kind = 'home_purchase') = (closing_costs_cents IS NOT NULL)),
    CHECK ((kind = 'home_purchase') = (ownership_costs_cents IS NOT NULL)),
    CHECK (down_payment_cents IS NULL OR down_payment_cents <= amount_cents),
    CHECK ((kind IN ('home_purchase', 'borrowing')) = (loan_rate_millionths IS NOT NULL)),
    CHECK ((kind IN ('home_purchase', 'borrowing')) = (loan_months IS NOT NULL)),
    CHECK ((kind = 'loan_payoff') = (loan_terms_id IS NOT NULL)),
    CHECK ((account_id IS NULL) = (match_text IS NULL)),
    CHECK (account_id IS NULL OR (kind IN ('income', 'expense') AND replaces_kind IS NULL))
) STRICT;

CREATE INDEX scenario_input_scenario ON scenario_input (scenario_id);

CREATE TABLE scenario_input_event (
    id          INTEGER PRIMARY KEY,
    input_id    TEXT NOT NULL REFERENCES scenario_input (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (input_id, event)
) STRICT;

-- M18.3: one promotion of a scenario's confirmed inputs, active from 'made' until 'undone'.
CREATE TABLE scenario_promotion (
    id           TEXT PRIMARY KEY,
    scenario_id  TEXT NOT NULL REFERENCES scenario (id),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE scenario_promotion_event (
    id            INTEGER PRIMARY KEY,
    promotion_id  TEXT NOT NULL REFERENCES scenario_promotion (id),
    event         TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (promotion_id, event)
) STRICT;

-- Each planning entry a promotion created, with the input it came from: a new source,
-- obligation or reserve by its ID, or a new terms row by its row ID. A terms row of an undone
-- promotion no longer applies, so undoing the promotion gives back the plan as it was.
CREATE TABLE scenario_promotion_entry (
    id            INTEGER PRIMARY KEY,
    promotion_id  TEXT NOT NULL REFERENCES scenario_promotion (id),
    input_id      TEXT NOT NULL REFERENCES scenario_input (id),
    entry_kind    TEXT NOT NULL CHECK (entry_kind IN ('income_source', 'recurring_obligation',
                                                      'fund', 'income_source_terms',
                                                      'recurring_obligation_terms',
                                                      'fund_terms')),
    entry_id      TEXT,
    terms_row_id  INTEGER,
    CHECK ((entry_kind GLOB '*_terms') = (terms_row_id IS NOT NULL)),
    CHECK ((entry_id IS NULL) = (terms_row_id IS NOT NULL))
) STRICT;

CREATE INDEX scenario_promotion_entry_promotion ON scenario_promotion_entry (promotion_id);

CREATE TRIGGER scenario_no_update BEFORE UPDATE ON scenario
BEGIN SELECT RAISE(ABORT, 'scenario is append-only'); END;
CREATE TRIGGER scenario_no_delete BEFORE DELETE ON scenario
BEGIN SELECT RAISE(ABORT, 'scenario is append-only'); END;
CREATE TRIGGER scenario_no_replace BEFORE INSERT ON scenario
WHEN EXISTS (SELECT 1 FROM scenario WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'scenario is append-only'); END;

CREATE TRIGGER scenario_event_no_update BEFORE UPDATE ON scenario_event
BEGIN SELECT RAISE(ABORT, 'scenario_event is append-only'); END;
CREATE TRIGGER scenario_event_no_delete BEFORE DELETE ON scenario_event
BEGIN SELECT RAISE(ABORT, 'scenario_event is append-only'); END;
CREATE TRIGGER scenario_event_no_replace BEFORE INSERT ON scenario_event
WHEN EXISTS (SELECT 1 FROM scenario_event
             WHERE id = NEW.id OR (scenario_id = NEW.scenario_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'scenario_event is append-only'); END;

CREATE TRIGGER scenario_input_no_update BEFORE UPDATE ON scenario_input
BEGIN SELECT RAISE(ABORT, 'scenario_input is append-only'); END;
CREATE TRIGGER scenario_input_no_delete BEFORE DELETE ON scenario_input
BEGIN SELECT RAISE(ABORT, 'scenario_input is append-only'); END;
CREATE TRIGGER scenario_input_no_replace BEFORE INSERT ON scenario_input
WHEN EXISTS (SELECT 1 FROM scenario_input WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'scenario_input is append-only'); END;

CREATE TRIGGER scenario_input_event_no_update BEFORE UPDATE ON scenario_input_event
BEGIN SELECT RAISE(ABORT, 'scenario_input_event is append-only'); END;
CREATE TRIGGER scenario_input_event_no_delete BEFORE DELETE ON scenario_input_event
BEGIN SELECT RAISE(ABORT, 'scenario_input_event is append-only'); END;
CREATE TRIGGER scenario_input_event_no_replace BEFORE INSERT ON scenario_input_event
WHEN EXISTS (SELECT 1 FROM scenario_input_event
             WHERE id = NEW.id OR (input_id = NEW.input_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'scenario_input_event is append-only'); END;

CREATE TRIGGER scenario_promotion_no_update BEFORE UPDATE ON scenario_promotion
BEGIN SELECT RAISE(ABORT, 'scenario_promotion is append-only'); END;
CREATE TRIGGER scenario_promotion_no_delete BEFORE DELETE ON scenario_promotion
BEGIN SELECT RAISE(ABORT, 'scenario_promotion is append-only'); END;
CREATE TRIGGER scenario_promotion_no_replace BEFORE INSERT ON scenario_promotion
WHEN EXISTS (SELECT 1 FROM scenario_promotion WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'scenario_promotion is append-only'); END;

CREATE TRIGGER scenario_promotion_event_no_update BEFORE UPDATE ON scenario_promotion_event
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_event is append-only'); END;
CREATE TRIGGER scenario_promotion_event_no_delete BEFORE DELETE ON scenario_promotion_event
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_event is append-only'); END;
CREATE TRIGGER scenario_promotion_event_no_replace BEFORE INSERT ON scenario_promotion_event
WHEN EXISTS (SELECT 1 FROM scenario_promotion_event
             WHERE id = NEW.id OR (promotion_id = NEW.promotion_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_event is append-only'); END;

CREATE TRIGGER scenario_promotion_entry_no_update BEFORE UPDATE ON scenario_promotion_entry
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_entry is append-only'); END;
CREATE TRIGGER scenario_promotion_entry_no_delete BEFORE DELETE ON scenario_promotion_entry
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_entry is append-only'); END;
CREATE TRIGGER scenario_promotion_entry_no_replace BEFORE INSERT ON scenario_promotion_entry
WHEN EXISTS (SELECT 1 FROM scenario_promotion_entry WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'scenario_promotion_entry is append-only'); END;
