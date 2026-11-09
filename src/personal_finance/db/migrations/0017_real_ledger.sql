-- Marks a ledger that holds actual financial data. Rules are in docs/decisions.md D-058.

-- A ledger holding this row is real, and every open checks its location first. One without it is
-- synthetic, as every ledger before this migration is. `pf init --real` writes the row into a
-- ledger holding nothing yet, so a synthetic ledger is never promoted. It is never changed or
-- removed.
CREATE TABLE real_ledger (
    only_row    INTEGER PRIMARY KEY CHECK (only_row = 1),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER real_ledger_only_when_empty BEFORE INSERT ON real_ledger
WHEN EXISTS (SELECT 1 FROM account) OR EXISTS (SELECT 1 FROM import_run)
BEGIN SELECT RAISE(ABORT, 'only a ledger holding nothing yet can be marked real'); END;

CREATE TRIGGER real_ledger_no_update BEFORE UPDATE ON real_ledger
BEGIN SELECT RAISE(ABORT, 'real_ledger is append-only'); END;
CREATE TRIGGER real_ledger_no_delete BEFORE DELETE ON real_ledger
BEGIN SELECT RAISE(ABORT, 'real_ledger is append-only'); END;
CREATE TRIGGER real_ledger_no_replace BEFORE INSERT ON real_ledger
WHEN EXISTS (SELECT 1 FROM real_ledger)
BEGIN SELECT RAISE(ABORT, 'real_ledger is append-only'); END;
