-- Recurring obligations stated by a person, their dated terms, the proposals a person dismissed,
-- and the spending each obligation reaches. Rules are in docs/decisions-m12-m21.md D-067 and
-- D-068 points 5 and 6, and "How M12.2 was implemented".

-- One obligation: money out in spending on account_id whose effective description contains
-- description_contains, both normalized under normalization_version, and whose effective category
-- is category_id when one is named. Its definition never changes: a change is a new obligation
-- superseding it (D-048's chain). chain_id names the chain's first obligation, itself for one
-- superseding nothing, and the chain's terms hang from it.
CREATE TABLE recurring_obligation (
    id                      TEXT PRIMARY KEY,
    account_id              TEXT NOT NULL REFERENCES account (id),
    name                    TEXT NOT NULL CHECK (trim(name) <> ''),
    description_contains    TEXT NOT NULL CHECK (trim(description_contains) <> ''),
    normalization_version   INTEGER NOT NULL CHECK (normalization_version >= 1),
    category_id             INTEGER REFERENCES category (id),
    tolerance_days          INTEGER NOT NULL CHECK (tolerance_days BETWEEN 0 AND 7),
    supersedes_id           TEXT REFERENCES recurring_obligation (id),
    chain_id                TEXT NOT NULL REFERENCES recurring_obligation (id),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((supersedes_id IS NULL) = (chain_id = id))
) STRICT;

-- A chain's dated terms, as income_source_terms: cadence, its days and anchor, then the amount as
-- a range in cents, LOW = HIGH for an exact amount, and the class. A later row takes over from
-- effective_from, so a month before it keeps its terms (G7).
CREATE TABLE recurring_obligation_terms (
    id                INTEGER PRIMARY KEY,
    chain_id          TEXT NOT NULL REFERENCES recurring_obligation (id),
    effective_from    TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    cadence           TEXT NOT NULL CHECK (cadence IN ('weekly', 'biweekly', 'semimonthly',
                                                       'monthly', 'quarterly', 'annual',
                                                       'every_months')),
    first_day         INTEGER CHECK (first_day IS NULL OR first_day BETWEEN 1 AND 31),
    second_day        INTEGER CHECK (second_day IS NULL OR second_day BETWEEN 1 AND 31),
    interval_months   INTEGER CHECK (interval_months IS NULL OR interval_months >= 2),
    anchor            TEXT NOT NULL CHECK (date(anchor) IS anchor),
    low_cents         INTEGER NOT NULL CHECK (low_cents > 0),
    high_cents        INTEGER NOT NULL,
    obligation_class  TEXT NOT NULL CHECK (obligation_class IN ('fixed', 'discretionary')),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (chain_id, effective_from),
    CHECK (high_cents >= low_cents),
    CHECK (CASE cadence
               WHEN 'weekly' THEN first_day IS NULL AND second_day IS NULL
                                  AND interval_months IS NULL
               WHEN 'biweekly' THEN first_day IS NULL AND second_day IS NULL
                                    AND interval_months IS NULL
               WHEN 'semimonthly' THEN first_day IS NOT NULL AND second_day IS NOT NULL
                                       AND second_day > first_day
                                       AND interval_months IS NULL
               WHEN 'every_months' THEN first_day IS NOT NULL AND second_day IS NULL
                                        AND interval_months IS NOT NULL
               ELSE first_day IS NOT NULL AND second_day IS NULL AND interval_months IS NULL
           END)
) STRICT;

-- An obligation is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE recurring_obligation_event (
    id             INTEGER PRIMARY KEY,
    obligation_id  TEXT NOT NULL REFERENCES recurring_obligation (id),
    event          TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (obligation_id, event)
) STRICT;

-- A proposal a person withdrew, by its key, which is stable across imports. It stays withdrawn
-- until its 'undone' event. Dismissing the same key again after an undo is a new dismissal.
CREATE TABLE obligation_proposal_dismissal (
    id            TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL REFERENCES account (id),
    proposal_key  TEXT NOT NULL CHECK (length(proposal_key) = 16),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE obligation_proposal_dismissal_event (
    id            INTEGER PRIMARY KEY,
    dismissal_id  TEXT NOT NULL REFERENCES obligation_proposal_dismissal (id),
    event         TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (dismissal_id, event)
) STRICT;

CREATE TRIGGER recurring_obligation_no_update BEFORE UPDATE ON recurring_obligation
BEGIN SELECT RAISE(ABORT, 'recurring_obligation is append-only'); END;
CREATE TRIGGER recurring_obligation_no_delete BEFORE DELETE ON recurring_obligation
BEGIN SELECT RAISE(ABORT, 'recurring_obligation is append-only'); END;
CREATE TRIGGER recurring_obligation_no_replace BEFORE INSERT ON recurring_obligation
WHEN EXISTS (SELECT 1 FROM recurring_obligation WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'recurring_obligation is append-only'); END;

CREATE TRIGGER recurring_obligation_terms_no_update BEFORE UPDATE ON recurring_obligation_terms
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_terms is append-only'); END;
CREATE TRIGGER recurring_obligation_terms_no_delete BEFORE DELETE ON recurring_obligation_terms
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_terms is append-only'); END;
CREATE TRIGGER recurring_obligation_terms_no_replace BEFORE INSERT ON recurring_obligation_terms
WHEN EXISTS (SELECT 1 FROM recurring_obligation_terms
             WHERE id = NEW.id OR (chain_id = NEW.chain_id
                                   AND effective_from = NEW.effective_from))
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_terms is append-only'); END;

CREATE TRIGGER recurring_obligation_event_no_update BEFORE UPDATE ON recurring_obligation_event
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_event is append-only'); END;
CREATE TRIGGER recurring_obligation_event_no_delete BEFORE DELETE ON recurring_obligation_event
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_event is append-only'); END;
CREATE TRIGGER recurring_obligation_event_no_replace BEFORE INSERT ON recurring_obligation_event
WHEN EXISTS (SELECT 1 FROM recurring_obligation_event
             WHERE id = NEW.id OR (obligation_id = NEW.obligation_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'recurring_obligation_event is append-only'); END;

CREATE TRIGGER obligation_proposal_dismissal_no_update BEFORE UPDATE
ON obligation_proposal_dismissal
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal is append-only'); END;
CREATE TRIGGER obligation_proposal_dismissal_no_delete BEFORE DELETE
ON obligation_proposal_dismissal
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal is append-only'); END;
CREATE TRIGGER obligation_proposal_dismissal_no_replace BEFORE INSERT
ON obligation_proposal_dismissal
WHEN EXISTS (SELECT 1 FROM obligation_proposal_dismissal WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal is append-only'); END;

CREATE TRIGGER obligation_proposal_dismissal_event_no_update BEFORE UPDATE
ON obligation_proposal_dismissal_event
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal_event is append-only'); END;
CREATE TRIGGER obligation_proposal_dismissal_event_no_delete BEFORE DELETE
ON obligation_proposal_dismissal_event
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal_event is append-only'); END;
CREATE TRIGGER obligation_proposal_dismissal_event_no_replace BEFORE INSERT
ON obligation_proposal_dismissal_event
WHEN EXISTS (SELECT 1 FROM obligation_proposal_dismissal_event
             WHERE id = NEW.id OR (dismissal_id = NEW.dismissal_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'obligation_proposal_dismissal_event is append-only'); END;

-- Derived, never edited by hand: each spending transaction an applying obligation reaches, what
-- it is there, and the class of the terms it is read under. paid and amount_out_of_range pair it
-- with a nominal due date. missed and expected are worked out where they are shown, so nothing
-- here depends on today. obligation_conflict has no class: the transaction is discretionary.
-- Rewritten whole on every write. A retired transaction takes its rows with it.
CREATE TABLE transaction_obligation (
    transaction_id    TEXT NOT NULL REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    obligation_id     TEXT NOT NULL REFERENCES recurring_obligation (id),
    state             TEXT NOT NULL CHECK (state IN ('paid', 'amount_out_of_range',
                                                     'unscheduled', 'obligation_conflict')),
    nominal_date      TEXT CHECK (nominal_date IS NULL OR date(nominal_date) IS nominal_date),
    obligation_class  TEXT CHECK (obligation_class IS NULL
                                  OR obligation_class IN ('fixed', 'discretionary')),
    PRIMARY KEY (transaction_id, obligation_id),
    CHECK ((state IN ('paid', 'amount_out_of_range')) = (nominal_date IS NOT NULL)),
    CHECK ((state = 'obligation_conflict') = (obligation_class IS NULL))
) STRICT;
