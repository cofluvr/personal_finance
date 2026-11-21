-- Loan terms with dated rate and payment periods, and the payoff plan. Rules are in
-- docs/decisions-m12-m21.md D-071 points 4 to 6.

-- One account's terms: a due day and, optionally, the remaining months the lender states. One is
-- active per account, from 'made' until 'undone'. A loan's or card's rate periods and a loan's
-- payment periods belong to it.
CREATE TABLE loan_terms (
    id                TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES account (id),
    due_day           INTEGER NOT NULL CHECK (due_day BETWEEN 1 AND 28),
    remaining_months  INTEGER CHECK (remaining_months IS NULL OR remaining_months BETWEEN 1 AND 600),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER loan_terms_loan_or_card BEFORE INSERT ON loan_terms
WHEN NOT EXISTS (SELECT 1 FROM account WHERE id = NEW.account_id
                 AND account_type IN ('loan', 'credit_card'))
BEGIN SELECT RAISE(ABORT, 'only a loan or a card has loan terms'); END;

CREATE TABLE loan_terms_event (
    id          INTEGER PRIMARY KEY,
    terms_id    TEXT NOT NULL REFERENCES loan_terms (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (terms_id, event)
) STRICT;

-- An APR in millionths of a percent (G8), so 6.875% is 6875000, from a date. The rate for a month
-- is the period in effect on its first day.
CREATE TABLE loan_rate_period (
    id                     INTEGER PRIMARY KEY,
    terms_id               TEXT NOT NULL REFERENCES loan_terms (id),
    effective_from         TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    rate_millionths        INTEGER NOT NULL CHECK (rate_millionths BETWEEN 0 AND 100000000),
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (terms_id, effective_from)
) STRICT;

-- A scheduled payment from a date: a graduated schedule is a sequence of these. The amount due on
-- a due date is the period in effect that day. A card has none.
CREATE TABLE loan_payment_period (
    id              INTEGER PRIMARY KEY,
    terms_id        TEXT NOT NULL REFERENCES loan_terms (id),
    effective_from  TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    payment_cents   INTEGER NOT NULL CHECK (payment_cents > 0),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (terms_id, effective_from)
) STRICT;

CREATE TRIGGER loan_payment_period_loans_only BEFORE INSERT ON loan_payment_period
WHEN NOT EXISTS (SELECT 1 FROM loan_terms terms JOIN account ON account.id = terms.account_id
                 WHERE terms.id = NEW.terms_id AND account.account_type = 'loan')
BEGIN SELECT RAISE(ABORT, 'only a loan has scheduled payments'); END;

-- The payoff plan (point 6): the plan made last applies, replacing every earlier one, which stays
-- on record. custom_order lists account IDs, comma-joined, for a custom order only. The extra is
-- an amount, the planned contribution of a goal (D-070's debt goal), or neither.
CREATE TABLE payoff_plan (
    id              TEXT PRIMARY KEY,
    order_kind      TEXT NOT NULL CHECK (order_kind IN ('avalanche', 'snowball', 'custom')),
    custom_order    TEXT,
    extra_cents     INTEGER CHECK (extra_cents IS NULL OR extra_cents > 0),
    extra_fund_id   TEXT REFERENCES fund (id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((custom_order IS NOT NULL) = (order_kind = 'custom')),
    CHECK (extra_cents IS NULL OR extra_fund_id IS NULL)
) STRICT;

CREATE TABLE payoff_plan_event (
    id          INTEGER PRIMARY KEY,
    plan_id     TEXT NOT NULL UNIQUE REFERENCES payoff_plan (id),
    event       TEXT NOT NULL CHECK (event = 'made'),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER loan_terms_no_update BEFORE UPDATE ON loan_terms
BEGIN SELECT RAISE(ABORT, 'loan_terms is append-only'); END;
CREATE TRIGGER loan_terms_no_delete BEFORE DELETE ON loan_terms
BEGIN SELECT RAISE(ABORT, 'loan_terms is append-only'); END;
CREATE TRIGGER loan_terms_no_replace BEFORE INSERT ON loan_terms
WHEN EXISTS (SELECT 1 FROM loan_terms WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'loan_terms is append-only'); END;

CREATE TRIGGER loan_terms_event_no_update BEFORE UPDATE ON loan_terms_event
BEGIN SELECT RAISE(ABORT, 'loan_terms_event is append-only'); END;
CREATE TRIGGER loan_terms_event_no_delete BEFORE DELETE ON loan_terms_event
BEGIN SELECT RAISE(ABORT, 'loan_terms_event is append-only'); END;
CREATE TRIGGER loan_terms_event_no_replace BEFORE INSERT ON loan_terms_event
WHEN EXISTS (SELECT 1 FROM loan_terms_event
             WHERE id = NEW.id OR (terms_id = NEW.terms_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'loan_terms_event is append-only'); END;

CREATE TRIGGER loan_rate_period_no_update BEFORE UPDATE ON loan_rate_period
BEGIN SELECT RAISE(ABORT, 'loan_rate_period is append-only'); END;
CREATE TRIGGER loan_rate_period_no_delete BEFORE DELETE ON loan_rate_period
BEGIN SELECT RAISE(ABORT, 'loan_rate_period is append-only'); END;
CREATE TRIGGER loan_rate_period_no_replace BEFORE INSERT ON loan_rate_period
WHEN EXISTS (SELECT 1 FROM loan_rate_period
             WHERE id = NEW.id
                OR (terms_id = NEW.terms_id AND effective_from = NEW.effective_from))
BEGIN SELECT RAISE(ABORT, 'loan_rate_period is append-only'); END;

CREATE TRIGGER loan_payment_period_no_update BEFORE UPDATE ON loan_payment_period
BEGIN SELECT RAISE(ABORT, 'loan_payment_period is append-only'); END;
CREATE TRIGGER loan_payment_period_no_delete BEFORE DELETE ON loan_payment_period
BEGIN SELECT RAISE(ABORT, 'loan_payment_period is append-only'); END;
CREATE TRIGGER loan_payment_period_no_replace BEFORE INSERT ON loan_payment_period
WHEN EXISTS (SELECT 1 FROM loan_payment_period
             WHERE id = NEW.id
                OR (terms_id = NEW.terms_id AND effective_from = NEW.effective_from))
BEGIN SELECT RAISE(ABORT, 'loan_payment_period is append-only'); END;

CREATE TRIGGER payoff_plan_no_update BEFORE UPDATE ON payoff_plan
BEGIN SELECT RAISE(ABORT, 'payoff_plan is append-only'); END;
CREATE TRIGGER payoff_plan_no_delete BEFORE DELETE ON payoff_plan
BEGIN SELECT RAISE(ABORT, 'payoff_plan is append-only'); END;
CREATE TRIGGER payoff_plan_no_replace BEFORE INSERT ON payoff_plan
WHEN EXISTS (SELECT 1 FROM payoff_plan WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'payoff_plan is append-only'); END;

CREATE TRIGGER payoff_plan_event_no_update BEFORE UPDATE ON payoff_plan_event
BEGIN SELECT RAISE(ABORT, 'payoff_plan_event is append-only'); END;
CREATE TRIGGER payoff_plan_event_no_delete BEFORE DELETE ON payoff_plan_event
BEGIN SELECT RAISE(ABORT, 'payoff_plan_event is append-only'); END;
CREATE TRIGGER payoff_plan_event_no_replace BEFORE INSERT ON payoff_plan_event
WHEN EXISTS (SELECT 1 FROM payoff_plan_event WHERE id = NEW.id OR plan_id = NEW.plan_id)
BEGIN SELECT RAISE(ABORT, 'payoff_plan_event is append-only'); END;
