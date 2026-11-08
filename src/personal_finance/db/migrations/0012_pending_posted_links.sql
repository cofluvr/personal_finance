-- The D-008 migration. Rules are in docs/decisions.md D-008 and D-052.

-- One transaction may hold a pending and a posted record of one document only when a person
-- confirmed them as one event, so the per-document uniqueness exempts confirmed links. Nothing
-- references transaction_source and no trigger is defined on it, so it is rebuilt directly.
CREATE TABLE transaction_source_rebuilt (
    transaction_id      TEXT NOT NULL,
    source_record_id    TEXT NOT NULL UNIQUE,
    source_document_id  TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    link_rule           TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (transaction_id, source_record_id),
    FOREIGN KEY (transaction_id, account_id)
        REFERENCES ledger_transaction (id, account_id),
    FOREIGN KEY (source_record_id, source_document_id, account_id)
        REFERENCES source_record (id, source_document_id, account_id)
) STRICT;

INSERT INTO transaction_source_rebuilt
SELECT transaction_id, source_record_id, source_document_id, account_id, link_rule, created_at
FROM transaction_source;

DROP TABLE transaction_source;
ALTER TABLE transaction_source_rebuilt RENAME TO transaction_source;

-- At most one record from any one document, except a confirmed pending and posted pair (D-008).
-- Which two records a confirmed link may join is checked by the code that confirms them.
CREATE UNIQUE INDEX transaction_source_one_record_per_document
    ON transaction_source (transaction_id, source_document_id)
    WHERE link_rule <> 'confirmed_same_event';
