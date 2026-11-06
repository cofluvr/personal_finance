-- Cross-document reconciliation. Rules are in docs/decisions.md D-026 to D-033.

-- How a document was interpreted at import, so that changing Python configuration
-- cannot silently reinterpret historical evidence (D-026).
CREATE TABLE document_interpretation (
    source_document_id            TEXT PRIMARY KEY REFERENCES source_document (id),
    layout_id                     TEXT NOT NULL,
    parser_version                TEXT NOT NULL,
    external_id_namespace         TEXT,
    external_id_guarantee         TEXT NOT NULL
                                      CHECK (external_id_guarantee IN ('none', 'stable', 'stable_unique')),
    -- Whether pending rows fall inside a complete claim on each date basis.
    -- NULL means the layout offers no such claim.
    pending_in_transaction_basis  INTEGER CHECK (pending_in_transaction_basis IN (0, 1)),
    pending_in_posting_basis      INTEGER CHECK (pending_in_posting_basis IN (0, 1)),
    CHECK ((external_id_guarantee = 'none') = (external_id_namespace IS NULL))
) STRICT;

-- Only the two invented layouts can exist in stored data. Anything else is given no
-- identifier guarantee, because nothing is known about it.
INSERT INTO document_interpretation
SELECT document.id,
       document.layout_id,
       COALESCE((SELECT MIN(parse.parser_version)
                 FROM record_parse parse
                 JOIN source_record record ON record.id = parse.source_record_id
                 WHERE record.source_document_id = document.id), '1'),
       CASE document.layout_id WHEN 'synthetic_checking_v1' THEN 'synthetic_checking_v1' END,
       CASE document.layout_id WHEN 'synthetic_checking_v1' THEN 'stable_unique' ELSE 'none' END,
       CASE document.layout_id WHEN 'synthetic_checking_v1' THEN 1 END,
       CASE WHEN document.layout_id IN ('synthetic_checking_v1', 'synthetic_card_v1') THEN 0 END
FROM source_document document;

-- The transaction created for each record at import. A group's public ID is chosen
-- from these, so a split can give a record its own ID back (D-029).
CREATE TABLE source_record_origin (
    source_record_id         TEXT PRIMARY KEY REFERENCES source_record (id),
    original_transaction_id  TEXT NOT NULL
) STRICT;

INSERT INTO source_record_origin
SELECT source_record_id, transaction_id FROM transaction_source;

-- Every move of a record between transactions. Current membership is in
-- transaction_source, and this table only says how it got there (D-029).
CREATE TABLE transaction_link_history (
    id                   INTEGER PRIMARY KEY,
    source_record_id     TEXT NOT NULL REFERENCES source_record (id),
    from_transaction_id  TEXT NOT NULL,
    to_transaction_id    TEXT NOT NULL,
    action               TEXT NOT NULL CHECK (action IN ('merged', 'split')),
    reason               TEXT NOT NULL,
    rules_fingerprint    TEXT NOT NULL CHECK (length(rules_fingerprint) = 64),
    trigger_document_id  TEXT REFERENCES source_document (id),
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (from_transaction_id <> to_transaction_id)
) STRICT;

CREATE INDEX transaction_link_history_from ON transaction_link_history (from_transaction_id);
CREATE INDEX transaction_link_history_to ON transaction_link_history (to_transaction_id);
CREATE INDEX transaction_link_history_record ON transaction_link_history (source_record_id);

-- The configuration an account was last reconciled under. Compared by fingerprint,
-- so it cannot claim currency for a different effective configuration (D-033).
CREATE TABLE account_reconciliation (
    account_id         TEXT PRIMARY KEY REFERENCES account (id),
    rules_version      INTEGER NOT NULL,
    rules_fingerprint  TEXT NOT NULL CHECK (length(rules_fingerprint) = 64),
    rules_json         TEXT NOT NULL CHECK (json_valid(rules_json)),
    reconciled_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER document_interpretation_no_update BEFORE UPDATE ON document_interpretation
BEGIN SELECT RAISE(ABORT, 'document_interpretation is immutable'); END;
CREATE TRIGGER document_interpretation_no_delete BEFORE DELETE ON document_interpretation
BEGIN SELECT RAISE(ABORT, 'document_interpretation is immutable'); END;
CREATE TRIGGER document_interpretation_no_replace BEFORE INSERT ON document_interpretation
WHEN EXISTS (SELECT 1 FROM document_interpretation
             WHERE source_document_id = NEW.source_document_id)
BEGIN SELECT RAISE(ABORT, 'document_interpretation is immutable'); END;

CREATE TRIGGER source_record_origin_no_update BEFORE UPDATE ON source_record_origin
BEGIN SELECT RAISE(ABORT, 'source_record_origin is immutable'); END;
CREATE TRIGGER source_record_origin_no_delete BEFORE DELETE ON source_record_origin
BEGIN SELECT RAISE(ABORT, 'source_record_origin is immutable'); END;
CREATE TRIGGER source_record_origin_no_replace BEFORE INSERT ON source_record_origin
WHEN EXISTS (SELECT 1 FROM source_record_origin WHERE source_record_id = NEW.source_record_id)
BEGIN SELECT RAISE(ABORT, 'source_record_origin is immutable'); END;

CREATE TRIGGER transaction_link_history_no_update BEFORE UPDATE ON transaction_link_history
BEGIN SELECT RAISE(ABORT, 'transaction_link_history is append-only'); END;
CREATE TRIGGER transaction_link_history_no_delete BEFORE DELETE ON transaction_link_history
BEGIN SELECT RAISE(ABORT, 'transaction_link_history is append-only'); END;
CREATE TRIGGER transaction_link_history_no_replace BEFORE INSERT ON transaction_link_history
WHEN EXISTS (SELECT 1 FROM transaction_link_history WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'transaction_link_history is append-only'); END;
