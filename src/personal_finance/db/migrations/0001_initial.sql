-- Initial M1 schema. Rules and reasons are in docs/decisions.md.
--
-- Conventions:
--   IDs are random text values with no meaning (D-009).
--   Money is signed integer cents, negative for money out of the account (D-003).
--   Dates are ISO YYYY-MM-DD text. NULL means missing, never zero or a guess.
--   Timestamps are UTC ISO 8601 text.

CREATE TABLE account (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL UNIQUE,
    institution   TEXT,
    account_type  TEXT NOT NULL CHECK (account_type IN
                      ('checking', 'savings', 'credit_card', 'loan', 'investment', 'retirement')),
    -- Deliberately not unique with institution (PRD section 6).
    last4         TEXT CHECK (last4 IS NULL OR last4 GLOB '[0-9][0-9][0-9][0-9]'),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TABLE import_run (
    id           TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at  TEXT
) STRICT;

-- A byte-identical file has one source_document however many times it is imported.
CREATE TABLE source_document (
    id              TEXT PRIMARY KEY,
    content_sha256  TEXT NOT NULL UNIQUE CHECK (length(content_sha256) = 64),
    file_name       TEXT NOT NULL,
    byte_size       INTEGER NOT NULL CHECK (byte_size >= 0),
    format          TEXT NOT NULL CHECK (format IN ('csv', 'pdf')),
    layout_id       TEXT NOT NULL,
    -- When the document says it was produced, if it says. Used for D-007.
    generated_on    TEXT CHECK (generated_on IS NULL OR date(generated_on) IS generated_on),
    imported_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

-- Every attempt is recorded, including failures that leave no source_document.
CREATE TABLE import_attempt (
    id                  TEXT PRIMARY KEY,
    import_run_id       TEXT NOT NULL REFERENCES import_run (id),
    file_name           TEXT NOT NULL,
    content_sha256      TEXT,
    outcome             TEXT NOT NULL CHECK (outcome IN ('imported', 'already_imported', 'failed')),
    source_document_id  TEXT REFERENCES source_document (id),
    -- A fixed code, never file contents, so it is safe to display and log.
    failure_code        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((outcome = 'failed') = (failure_code IS NOT NULL)),
    CHECK (outcome = 'failed' OR source_document_id IS NOT NULL)
) STRICT;

-- What a document claims to contain for one account (D-005). Never derived from
-- the earliest and latest transaction dates alone.
CREATE TABLE document_coverage (
    source_document_id  TEXT NOT NULL REFERENCES source_document (id),
    account_id          TEXT NOT NULL REFERENCES account (id),
    coverage_kind       TEXT NOT NULL CHECK (coverage_kind IN ('complete', 'partial', 'unknown')),
    coverage_start      TEXT CHECK (coverage_start IS NULL OR date(coverage_start) IS coverage_start),
    coverage_end        TEXT CHECK (coverage_end IS NULL OR date(coverage_end) IS coverage_end),
    date_basis          TEXT CHECK (date_basis IN ('transaction', 'posting')),
    evidence            TEXT CHECK (evidence IN ('document_metadata', 'user_declared')),
    PRIMARY KEY (source_document_id, account_id),
    CHECK (coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end),
    CHECK (coverage_kind <> 'complete' OR (coverage_start IS NOT NULL AND coverage_end IS NOT NULL
                                           AND date_basis IS NOT NULL AND evidence IS NOT NULL)),
    CHECK (coverage_kind <> 'unknown' OR (coverage_start IS NULL AND coverage_end IS NULL
                                          AND date_basis IS NULL AND evidence IS NULL))
) STRICT;

-- One row per raw record as read. Failed rows are kept too.
CREATE TABLE source_record (
    id                  TEXT PRIMARY KEY,
    source_document_id  TEXT NOT NULL REFERENCES source_document (id),
    -- NULL only when a multi-account document does not reveal the account.
    account_id          TEXT REFERENCES account (id),
    record_index        INTEGER NOT NULL CHECK (record_index >= 1),
    raw_json            TEXT NOT NULL CHECK (json_valid(raw_json)),
    -- Supporting evidence only, not identity (D-009).
    raw_fingerprint     TEXT NOT NULL CHECK (length(raw_fingerprint) = 64),
    occurrence          INTEGER NOT NULL CHECK (occurrence >= 1),
    UNIQUE (source_document_id, record_index),
    UNIQUE (source_document_id, raw_fingerprint, occurrence),
    UNIQUE (id, source_document_id, account_id)
) STRICT;

-- Parser output, one row per record per parser version. Rows with
-- status = 'unresolved' are the unresolved-import queue.
CREATE TABLE record_parse (
    source_record_id   TEXT NOT NULL REFERENCES source_record (id),
    parser_version     TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('parsed', 'unresolved')),
    reason_code        TEXT,
    transaction_date   TEXT CHECK (transaction_date IS NULL OR date(transaction_date) IS transaction_date),
    posting_date       TEXT CHECK (posting_date IS NULL OR date(posting_date) IS posting_date),
    amount_cents       INTEGER,
    description        TEXT,
    external_id        TEXT,
    settlement_status  TEXT NOT NULL DEFAULT 'unknown'
                           CHECK (settlement_status IN ('pending', 'posted', 'unknown')),
    PRIMARY KEY (source_record_id, parser_version),
    CHECK ((status = 'unresolved') = (reason_code IS NOT NULL)),
    CHECK (status <> 'parsed' OR (amount_cents IS NOT NULL
                                  AND (transaction_date IS NOT NULL OR posting_date IS NOT NULL)))
) STRICT;

-- One logical transaction per real-world event. Totals read this table.
-- external_id is not unique: the same ID with a different amount must be
-- retained and flagged (D-006).
CREATE TABLE ledger_transaction (
    id                 TEXT PRIMARY KEY,
    account_id         TEXT NOT NULL REFERENCES account (id),
    external_id        TEXT,
    transaction_date   TEXT CHECK (transaction_date IS NULL OR date(transaction_date) IS transaction_date),
    posting_date       TEXT CHECK (posting_date IS NULL OR date(posting_date) IS posting_date),
    amount_cents       INTEGER NOT NULL,
    currency           TEXT NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    description        TEXT,
    settlement_status  TEXT NOT NULL DEFAULT 'unknown'
                           CHECK (settlement_status IN ('pending', 'posted', 'unknown')),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, account_id),
    CHECK (transaction_date IS NOT NULL OR posting_date IS NOT NULL)
) STRICT;

CREATE INDEX ledger_transaction_account_dates
    ON ledger_transaction (account_id, posting_date, transaction_date);
CREATE INDEX ledger_transaction_external_id
    ON ledger_transaction (account_id, external_id) WHERE external_id IS NOT NULL;

-- Links logical transactions to the records that support them. The composite
-- foreign keys stop a link crossing accounts or misstating its document.
CREATE TABLE transaction_source (
    transaction_id      TEXT NOT NULL,
    source_record_id    TEXT NOT NULL UNIQUE,
    source_document_id  TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    link_rule           TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (transaction_id, source_record_id),
    -- At most one record from any one document (D-008).
    UNIQUE (transaction_id, source_document_id),
    FOREIGN KEY (transaction_id, account_id)
        REFERENCES ledger_transaction (id, account_id),
    FOREIGN KEY (source_record_id, source_document_id, account_id)
        REFERENCES source_record (id, source_document_id, account_id)
) STRICT;

CREATE TABLE review_issue (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL CHECK (kind IN ('possible_duplicate', 'unresolved_record')),
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    rule           TEXT NOT NULL,
    evidence_json  TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_json)),
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at    TEXT,
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL))
) STRICT;

-- An issue can cover a whole group of identical-looking records (D-006).
CREATE TABLE review_issue_subject (
    review_issue_id   TEXT NOT NULL REFERENCES review_issue (id),
    transaction_id    TEXT REFERENCES ledger_transaction (id),
    source_record_id  TEXT REFERENCES source_record (id),
    UNIQUE (review_issue_id, transaction_id),
    UNIQUE (review_issue_id, source_record_id),
    CHECK ((transaction_id IS NULL) <> (source_record_id IS NULL))
) STRICT;

CREATE INDEX review_issue_subject_transaction
    ON review_issue_subject (transaction_id) WHERE transaction_id IS NOT NULL;
CREATE INDEX review_issue_subject_record
    ON review_issue_subject (source_record_id) WHERE source_record_id IS NOT NULL;

-- Source evidence is immutable (D-004). Parser output is append-only for the
-- same reason: a new parser version adds a row.
CREATE TRIGGER source_document_no_update BEFORE UPDATE ON source_document
BEGIN SELECT RAISE(ABORT, 'source_document is immutable'); END;
CREATE TRIGGER source_document_no_delete BEFORE DELETE ON source_document
BEGIN SELECT RAISE(ABORT, 'source_document is immutable'); END;

CREATE TRIGGER source_record_no_update BEFORE UPDATE ON source_record
BEGIN SELECT RAISE(ABORT, 'source_record is immutable'); END;
CREATE TRIGGER source_record_no_delete BEFORE DELETE ON source_record
BEGIN SELECT RAISE(ABORT, 'source_record is immutable'); END;

CREATE TRIGGER record_parse_no_update BEFORE UPDATE ON record_parse
BEGIN SELECT RAISE(ABORT, 'record_parse is append-only'); END;
CREATE TRIGGER record_parse_no_delete BEFORE DELETE ON record_parse
BEGIN SELECT RAISE(ABORT, 'record_parse is append-only'); END;

CREATE TRIGGER document_coverage_no_update BEFORE UPDATE ON document_coverage
BEGIN SELECT RAISE(ABORT, 'document_coverage is immutable'); END;
CREATE TRIGGER document_coverage_no_delete BEFORE DELETE ON document_coverage
BEGIN SELECT RAISE(ABORT, 'document_coverage is immutable'); END;

-- Decisions and overrides depend on these IDs staying put (D-009).
CREATE TRIGGER account_id_immutable BEFORE UPDATE OF id ON account
BEGIN SELECT RAISE(ABORT, 'account id is immutable'); END;
CREATE TRIGGER ledger_transaction_identity_immutable
BEFORE UPDATE OF id, account_id ON ledger_transaction
BEGIN SELECT RAISE(ABORT, 'transaction identity is immutable'); END;
