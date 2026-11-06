-- Keeps a retired transaction's identity recoverable, and records which source supplies
-- a transaction's displayed values. Rules are in docs/decisions.md D-029 and D-030.

-- NULL means not recorded yet: a transaction merged before this migration gets its
-- value the next time its account is reconciled.
ALTER TABLE ledger_transaction
    ADD COLUMN primary_source_record_id TEXT REFERENCES source_record (id);

UPDATE ledger_transaction
SET primary_source_record_id = (SELECT MIN(link.source_record_id)
                                FROM transaction_source link
                                WHERE link.transaction_id = ledger_transaction.id)
WHERE (SELECT COUNT(*) FROM transaction_source link
       WHERE link.transaction_id = ledger_transaction.id) = 1;

-- Each retirement and revival of a public transaction ID. Moves of source records stay
-- in transaction_link_history. A retirement keeps the row's created_at, so a revival
-- can restore it.
CREATE TABLE transaction_identity_history (
    id                      INTEGER PRIMARY KEY,
    transaction_id          TEXT NOT NULL,
    event                   TEXT NOT NULL CHECK (event IN ('retired', 'revived')),
    transaction_created_at  TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    rules_fingerprint       TEXT NOT NULL CHECK (length(rules_fingerprint) = 64),
    trigger_document_id     TEXT REFERENCES source_document (id),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX transaction_identity_history_transaction
    ON transaction_identity_history (transaction_id);

CREATE TRIGGER transaction_identity_history_no_update
BEFORE UPDATE ON transaction_identity_history
BEGIN SELECT RAISE(ABORT, 'transaction_identity_history is append-only'); END;
CREATE TRIGGER transaction_identity_history_no_delete
BEFORE DELETE ON transaction_identity_history
BEGIN SELECT RAISE(ABORT, 'transaction_identity_history is append-only'); END;
CREATE TRIGGER transaction_identity_history_no_replace
BEFORE INSERT ON transaction_identity_history
WHEN EXISTS (SELECT 1 FROM transaction_identity_history WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'transaction_identity_history is append-only'); END;
