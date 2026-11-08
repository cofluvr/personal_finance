-- Coverage correction with history. Rules are in docs/decisions.md D-051.

-- A person's later statement of one document's coverage for one account. document_coverage keeps
-- the claim made at import, unchanged. Each declaration supersedes the one in effect, if any, and
-- only the newest of a chain applies (D-048).
CREATE TABLE coverage_declaration (
    id                         TEXT PRIMARY KEY,
    account_id                 TEXT NOT NULL,
    source_document_id         TEXT NOT NULL,
    coverage_kind              TEXT NOT NULL CHECK (coverage_kind IN ('complete', 'unknown')),
    coverage_start             TEXT CHECK (coverage_start IS NULL OR date(coverage_start) IS coverage_start),
    coverage_end               TEXT CHECK (coverage_end IS NULL OR date(coverage_end) IS coverage_end),
    date_basis                 TEXT CHECK (date_basis IN ('transaction', 'posting')),
    supersedes_declaration_id  TEXT REFERENCES coverage_declaration (id),
    target_revision            TEXT NOT NULL,
    created_at                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (source_document_id, account_id)
        REFERENCES document_coverage (source_document_id, account_id),
    CHECK (coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end),
    CHECK (coverage_kind <> 'complete' OR (coverage_start IS NOT NULL AND coverage_end IS NOT NULL
                                           AND date_basis IS NOT NULL)),
    CHECK (coverage_kind <> 'unknown' OR (coverage_start IS NULL AND coverage_end IS NULL
                                          AND date_basis IS NULL))
) STRICT;

CREATE INDEX coverage_declaration_account ON coverage_declaration (account_id);

-- A declaration is active from 'made' until an 'undone' event, and stays on record after it.
CREATE TABLE coverage_declaration_event (
    id              INTEGER PRIMARY KEY,
    declaration_id  TEXT NOT NULL REFERENCES coverage_declaration (id),
    event           TEXT NOT NULL CHECK (event IN ('made', 'undone')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (declaration_id, event)
) STRICT;

CREATE TRIGGER coverage_declaration_supersedes_same_document BEFORE INSERT ON coverage_declaration
WHEN NEW.supersedes_declaration_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM coverage_declaration old
                 WHERE old.id = NEW.supersedes_declaration_id
                   AND old.source_document_id = NEW.source_document_id
                   AND old.account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'a declaration can only supersede one of its own document'); END;

CREATE TRIGGER coverage_declaration_no_update BEFORE UPDATE ON coverage_declaration
BEGIN SELECT RAISE(ABORT, 'coverage_declaration is append-only'); END;
CREATE TRIGGER coverage_declaration_no_delete BEFORE DELETE ON coverage_declaration
BEGIN SELECT RAISE(ABORT, 'coverage_declaration is append-only'); END;
CREATE TRIGGER coverage_declaration_no_replace BEFORE INSERT ON coverage_declaration
WHEN EXISTS (SELECT 1 FROM coverage_declaration WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'coverage_declaration is append-only'); END;

CREATE TRIGGER coverage_declaration_event_no_update BEFORE UPDATE ON coverage_declaration_event
BEGIN SELECT RAISE(ABORT, 'coverage_declaration_event is append-only'); END;
CREATE TRIGGER coverage_declaration_event_no_delete BEFORE DELETE ON coverage_declaration_event
BEGIN SELECT RAISE(ABORT, 'coverage_declaration_event is append-only'); END;
CREATE TRIGGER coverage_declaration_event_no_replace BEFORE INSERT ON coverage_declaration_event
WHEN EXISTS (SELECT 1 FROM coverage_declaration_event
             WHERE id = NEW.id OR (declaration_id = NEW.declaration_id AND event = NEW.event))
BEGIN SELECT RAISE(ABORT, 'coverage_declaration_event is append-only'); END;
