-- What safe-to-spend reads that a person states: the accounts it may draw on, the links saying an
-- obligation is a loan's payment or a reserve's purchase, and the emergency fund's restoration.
-- Seeds the checking_buffer_cents setting key. Rules are in docs/decisions-m12-m21.md D-072
-- points 2 and 4, and "How M16.1 was implemented".

INSERT INTO ledger_setting_key (setting_key) VALUES ('checking_buffer_cents');

-- One designation, active from 'made' until 'undone'. Changing one is undo then set. One active
-- designation per account is checked under the write lock (G3), since it turns on the events.
CREATE TABLE account_liquidity (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES account (id),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX account_liquidity_account ON account_liquidity (account_id);

-- Only checking and savings accounts are liquid.
CREATE TRIGGER account_liquidity_checking_or_savings BEFORE INSERT ON account_liquidity
WHEN NOT EXISTS (SELECT 1 FROM account WHERE id = NEW.account_id
                 AND account_type IN ('checking', 'savings'))
BEGIN SELECT RAISE(ABORT, 'only a checking or savings account is designated liquid'); END;

CREATE TABLE account_liquidity_event (
    id              INTEGER PRIMARY KEY,
    designation_id  TEXT NOT NULL REFERENCES account_liquidity (id),
    event           TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (designation_id, event)
) STRICT;

-- "This obligation is the payment of this loan's schedule", or "the purchase this reserve saves
-- for": exactly one of loan_account_id and fund_id. The link applies to the obligation's chain, so
-- a supersession keeps it. One link per chain and one per loan or reserve are checked under the
-- write lock, since they turn on which links and obligations are active.
CREATE TABLE obligation_coverage (
    id               TEXT PRIMARY KEY,
    obligation_id    TEXT NOT NULL REFERENCES recurring_obligation (id),
    loan_account_id  TEXT REFERENCES account (id),
    fund_id          TEXT REFERENCES fund (id),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((loan_account_id IS NULL) <> (fund_id IS NULL))
) STRICT;

CREATE TRIGGER obligation_coverage_loan_or_reserve BEFORE INSERT ON obligation_coverage
WHEN (NEW.loan_account_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM account WHERE id = NEW.loan_account_id
                      AND account_type = 'loan'))
  OR (NEW.fund_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM fund WHERE id = NEW.fund_id AND kind = 'reserve'))
BEGIN SELECT RAISE(ABORT, 'an obligation covers only a loan account or a reserve'); END;

CREATE TABLE obligation_coverage_event (
    id           INTEGER PRIMARY KEY,
    coverage_id  TEXT NOT NULL REFERENCES obligation_coverage (id),
    event        TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (coverage_id, event)
) STRICT;

-- The emergency fund's dated monthly restoration, applied only while it is underfunded. A later
-- effective_from takes over (G2, G7). Undo steps back the newest active row.
CREATE TABLE fund_restoration (
    id              TEXT PRIMARY KEY,
    fund_id         TEXT NOT NULL REFERENCES fund (id),
    effective_from  TEXT NOT NULL CHECK (date(effective_from) IS effective_from),
    monthly_cents   INTEGER NOT NULL CHECK (monthly_cents > 0),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER fund_restoration_emergency_only BEFORE INSERT ON fund_restoration
WHEN NOT EXISTS (SELECT 1 FROM fund WHERE id = NEW.fund_id AND kind = 'emergency')
BEGIN SELECT RAISE(ABORT, 'only the emergency fund takes a restoration'); END;

CREATE TABLE fund_restoration_event (
    id              INTEGER PRIMARY KEY,
    restoration_id  TEXT NOT NULL REFERENCES fund_restoration (id),
    event           TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (restoration_id, event)
) STRICT;

CREATE TRIGGER account_liquidity_no_update BEFORE UPDATE ON account_liquidity
BEGIN SELECT RAISE(ABORT, 'account_liquidity is append-only'); END;
CREATE TRIGGER account_liquidity_no_delete BEFORE DELETE ON account_liquidity
BEGIN SELECT RAISE(ABORT, 'account_liquidity is append-only'); END;
CREATE TRIGGER account_liquidity_no_replace BEFORE INSERT ON account_liquidity
WHEN EXISTS (SELECT 1 FROM account_liquidity WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'account_liquidity is append-only'); END;

CREATE TRIGGER account_liquidity_event_no_update BEFORE UPDATE ON account_liquidity_event
BEGIN SELECT RAISE(ABORT, 'account_liquidity_event is append-only'); END;
CREATE TRIGGER account_liquidity_event_no_delete BEFORE DELETE ON account_liquidity_event
BEGIN SELECT RAISE(ABORT, 'account_liquidity_event is append-only'); END;
CREATE TRIGGER account_liquidity_event_no_replace BEFORE INSERT ON account_liquidity_event
WHEN EXISTS (SELECT 1 FROM account_liquidity_event
             WHERE id = NEW.id OR (designation_id = NEW.designation_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'account_liquidity_event is append-only'); END;

CREATE TRIGGER obligation_coverage_no_update BEFORE UPDATE ON obligation_coverage
BEGIN SELECT RAISE(ABORT, 'obligation_coverage is append-only'); END;
CREATE TRIGGER obligation_coverage_no_delete BEFORE DELETE ON obligation_coverage
BEGIN SELECT RAISE(ABORT, 'obligation_coverage is append-only'); END;
CREATE TRIGGER obligation_coverage_no_replace BEFORE INSERT ON obligation_coverage
WHEN EXISTS (SELECT 1 FROM obligation_coverage WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'obligation_coverage is append-only'); END;

CREATE TRIGGER obligation_coverage_event_no_update BEFORE UPDATE ON obligation_coverage_event
BEGIN SELECT RAISE(ABORT, 'obligation_coverage_event is append-only'); END;
CREATE TRIGGER obligation_coverage_event_no_delete BEFORE DELETE ON obligation_coverage_event
BEGIN SELECT RAISE(ABORT, 'obligation_coverage_event is append-only'); END;
CREATE TRIGGER obligation_coverage_event_no_replace BEFORE INSERT ON obligation_coverage_event
WHEN EXISTS (SELECT 1 FROM obligation_coverage_event
             WHERE id = NEW.id OR (coverage_id = NEW.coverage_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'obligation_coverage_event is append-only'); END;

CREATE TRIGGER fund_restoration_no_update BEFORE UPDATE ON fund_restoration
BEGIN SELECT RAISE(ABORT, 'fund_restoration is append-only'); END;
CREATE TRIGGER fund_restoration_no_delete BEFORE DELETE ON fund_restoration
BEGIN SELECT RAISE(ABORT, 'fund_restoration is append-only'); END;
CREATE TRIGGER fund_restoration_no_replace BEFORE INSERT ON fund_restoration
WHEN EXISTS (SELECT 1 FROM fund_restoration WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'fund_restoration is append-only'); END;

CREATE TRIGGER fund_restoration_event_no_update BEFORE UPDATE ON fund_restoration_event
BEGIN SELECT RAISE(ABORT, 'fund_restoration_event is append-only'); END;
CREATE TRIGGER fund_restoration_event_no_delete BEFORE DELETE ON fund_restoration_event
BEGIN SELECT RAISE(ABORT, 'fund_restoration_event is append-only'); END;
CREATE TRIGGER fund_restoration_event_no_replace BEFORE INSERT ON fund_restoration_event
WHEN EXISTS (SELECT 1 FROM fund_restoration_event
             WHERE id = NEW.id OR (restoration_id = NEW.restoration_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'fund_restoration_event is append-only'); END;
