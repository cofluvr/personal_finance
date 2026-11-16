-- Income sources stated by a person, their dated terms, and the deposits each reaches. Rules are in
-- docs/decisions-m12-m21.md D-067 and D-068, and its M12.1 slice plan.

-- One source: money in on account_id, typed income, whose effective description contains
-- description_contains, both normalized under normalization_version. Its definition never changes:
-- a change is a new source superseding it (D-048's chain). chain_id names the chain's first source,
-- itself for a source superseding nothing, and the chain's terms hang from it.
CREATE TABLE income_source (
    id                      TEXT PRIMARY KEY,
    account_id              TEXT NOT NULL REFERENCES account (id),
    name                    TEXT NOT NULL CHECK (trim(name) <> ''),
    kind                    TEXT NOT NULL CHECK (kind IN ('salary', 'side')),
    description_contains    TEXT NOT NULL CHECK (trim(description_contains) <> ''),
    normalization_version   INTEGER NOT NULL CHECK (normalization_version >= 1),
    tolerance_days          INTEGER NOT NULL CHECK (tolerance_days BETWEEN 0 AND 7),
    amount_tolerance_cents  INTEGER NOT NULL CHECK (amount_tolerance_cents >= 0),
    member_id               INTEGER REFERENCES household_member (id),
    tax_eligible            INTEGER NOT NULL CHECK (tax_eligible IN (0, 1)),
    supersedes_id           TEXT REFERENCES income_source (id),
    chain_id                TEXT NOT NULL REFERENCES income_source (id),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((supersedes_id IS NULL) = (chain_id = id))
) STRICT;

-- A chain's dated terms. The first, made with its source, starts at the anchor. A later one takes
-- over from effective_from, so a month before it keeps its terms (G7). Day columns hold what the
-- cadence names: none for weekly and biweekly, two ascending days for semimonthly, one day
-- otherwise, and the months between pay dates for every N months.
CREATE TABLE income_source_terms (
    id               INTEGER PRIMARY KEY,
    chain_id         TEXT NOT NULL REFERENCES income_source (id),
    effective_from   TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    cadence          TEXT NOT NULL CHECK (cadence IN ('weekly', 'biweekly', 'semimonthly',
                                                      'monthly', 'quarterly', 'annual',
                                                      'every_months')),
    first_day        INTEGER CHECK (first_day IS NULL OR first_day BETWEEN 1 AND 31),
    second_day       INTEGER CHECK (second_day IS NULL OR second_day BETWEEN 1 AND 31),
    interval_months  INTEGER CHECK (interval_months IS NULL OR interval_months >= 2),
    anchor           TEXT NOT NULL CHECK (date(anchor) IS anchor),
    amount_cents     INTEGER NOT NULL CHECK (amount_cents > 0),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (chain_id, effective_from),
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

-- A source is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE income_source_event (
    id          INTEGER PRIMARY KEY,
    source_id   TEXT NOT NULL REFERENCES income_source (id),
    event       TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_id, event)
) STRICT;

CREATE TRIGGER income_source_no_update BEFORE UPDATE ON income_source
BEGIN SELECT RAISE(ABORT, 'income_source is append-only'); END;
CREATE TRIGGER income_source_no_delete BEFORE DELETE ON income_source
BEGIN SELECT RAISE(ABORT, 'income_source is append-only'); END;
CREATE TRIGGER income_source_no_replace BEFORE INSERT ON income_source
WHEN EXISTS (SELECT 1 FROM income_source WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'income_source is append-only'); END;

CREATE TRIGGER income_source_terms_no_update BEFORE UPDATE ON income_source_terms
BEGIN SELECT RAISE(ABORT, 'income_source_terms is append-only'); END;
CREATE TRIGGER income_source_terms_no_delete BEFORE DELETE ON income_source_terms
BEGIN SELECT RAISE(ABORT, 'income_source_terms is append-only'); END;
CREATE TRIGGER income_source_terms_no_replace BEFORE INSERT ON income_source_terms
WHEN EXISTS (SELECT 1 FROM income_source_terms
             WHERE id = NEW.id OR (chain_id = NEW.chain_id
                                   AND effective_from = NEW.effective_from))
BEGIN SELECT RAISE(ABORT, 'income_source_terms is append-only'); END;

CREATE TRIGGER income_source_event_no_update BEFORE UPDATE ON income_source_event
BEGIN SELECT RAISE(ABORT, 'income_source_event is append-only'); END;
CREATE TRIGGER income_source_event_no_delete BEFORE DELETE ON income_source_event
BEGIN SELECT RAISE(ABORT, 'income_source_event is append-only'); END;
CREATE TRIGGER income_source_event_no_replace BEFORE INSERT ON income_source_event
WHEN EXISTS (SELECT 1 FROM income_source_event
             WHERE id = NEW.id OR (source_id = NEW.source_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'income_source_event is append-only'); END;

-- Derived, never edited by hand: each deposit an applying source reaches, and what it is there.
-- received and amount_changed pair it with a nominal pay date. missed and expected are pay dates
-- with no deposit, worked out where they are shown, so nothing here depends on today. Rewritten
-- whole on every write. A retired transaction takes its rows with it.
CREATE TABLE transaction_income_source (
    transaction_id  TEXT NOT NULL REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    source_id       TEXT NOT NULL REFERENCES income_source (id),
    state           TEXT NOT NULL CHECK (state IN ('received', 'amount_changed', 'unscheduled',
                                                   'source_conflict')),
    nominal_date    TEXT CHECK (nominal_date IS NULL OR date(nominal_date) IS nominal_date),
    PRIMARY KEY (transaction_id, source_id),
    CHECK ((state IN ('received', 'amount_changed')) = (nominal_date IS NOT NULL))
) STRICT;
