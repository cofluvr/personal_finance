-- A loan payment's interest and fees, stated by a person from the lender's statement, on the
-- payment's records. Rules are in docs/decisions-m12-m21.md D-071 point 7.

-- One breakdown, anchored on the records of its transaction when it was made, as a categorization
-- is (D-063). target_transaction_id is a snapshot and has no foreign key. Its value is canonical,
-- interest cents, a colon, then fees cents, so two breakdowns agree exactly when their values are
-- equal. The principal is the remainder of the payment.
CREATE TABLE loan_payment_breakdown (
    id                       TEXT PRIMARY KEY,
    account_id               TEXT NOT NULL REFERENCES account (id),
    breakdown                TEXT NOT NULL CHECK (breakdown GLOB '[0-9]*:[0-9]*'
                                                  AND breakdown NOT GLOB '*[^0-9:]*'
                                                  AND breakdown <> '0:0'),
    target_transaction_id    TEXT NOT NULL,
    target_revision          TEXT NOT NULL,
    supersedes_breakdown_id  TEXT REFERENCES loan_payment_breakdown (id),
    created_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX loan_payment_breakdown_account ON loan_payment_breakdown (account_id);

CREATE TABLE loan_payment_breakdown_record (
    breakdown_id      TEXT NOT NULL REFERENCES loan_payment_breakdown (id),
    source_record_id  TEXT NOT NULL REFERENCES source_record (id),
    PRIMARY KEY (breakdown_id, source_record_id)
) STRICT;

CREATE INDEX loan_payment_breakdown_record_source
    ON loan_payment_breakdown_record (source_record_id);

-- A breakdown is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE loan_payment_breakdown_event (
    id            INTEGER PRIMARY KEY,
    breakdown_id  TEXT NOT NULL REFERENCES loan_payment_breakdown (id),
    event         TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (breakdown_id, event)
) STRICT;

CREATE TRIGGER loan_payment_breakdown_supersedes_same_account
BEFORE INSERT ON loan_payment_breakdown
WHEN NEW.supersedes_breakdown_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM loan_payment_breakdown old
                 WHERE old.id = NEW.supersedes_breakdown_id AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a breakdown can only supersede one of its own account'); END;

CREATE TRIGGER loan_payment_breakdown_no_update BEFORE UPDATE ON loan_payment_breakdown
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_no_delete BEFORE DELETE ON loan_payment_breakdown
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_no_replace BEFORE INSERT ON loan_payment_breakdown
WHEN EXISTS (SELECT 1 FROM loan_payment_breakdown WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown is append-only'); END;

CREATE TRIGGER loan_payment_breakdown_record_no_update
BEFORE UPDATE ON loan_payment_breakdown_record
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_record is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_record_no_delete
BEFORE DELETE ON loan_payment_breakdown_record
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_record is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_record_no_replace
BEFORE INSERT ON loan_payment_breakdown_record
WHEN EXISTS (SELECT 1 FROM loan_payment_breakdown_record
             WHERE breakdown_id = NEW.breakdown_id AND source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_record is append-only'); END;

CREATE TRIGGER loan_payment_breakdown_event_no_update
BEFORE UPDATE ON loan_payment_breakdown_event
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_event is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_event_no_delete
BEFORE DELETE ON loan_payment_breakdown_event
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_event is append-only'); END;
CREATE TRIGGER loan_payment_breakdown_event_no_replace
BEFORE INSERT ON loan_payment_breakdown_event
WHEN EXISTS (SELECT 1 FROM loan_payment_breakdown_event
             WHERE id = NEW.id OR (breakdown_id = NEW.breakdown_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'loan_payment_breakdown_event is append-only'); END;

-- Derived, never edited by hand: the outcome of active breakdowns on each live transaction they
-- reach, the applied value canonical as above. does_not_fit is a single agreeing breakdown on a
-- transaction no longer a confirmed loan payment, or whose interest and fees now exceed its
-- effective amount. Rewritten wherever transaction_category is. A retired transaction takes its
-- row with it.
CREATE TABLE transaction_loan_breakdown (
    transaction_id  TEXT PRIMARY KEY REFERENCES ledger_transaction (id) ON DELETE CASCADE,
    state           TEXT NOT NULL CHECK (state IN ('applied', 'conflict', 'basis_changed',
                                                   'does_not_fit')),
    breakdown       TEXT,
    CHECK ((state = 'applied') = (breakdown IS NOT NULL))
) STRICT;
