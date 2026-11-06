-- INSERT OR REPLACE removes the conflicting row without firing delete triggers,
-- so 0001 alone did not protect source evidence. These triggers run before
-- conflict resolution and refuse any insert that would collide (D-004).

CREATE TRIGGER source_document_no_replace BEFORE INSERT ON source_document
WHEN EXISTS (SELECT 1 FROM source_document
             WHERE id = NEW.id OR content_sha256 = NEW.content_sha256)
BEGIN SELECT RAISE(ABORT, 'source_document is immutable'); END;

CREATE TRIGGER source_record_no_replace BEFORE INSERT ON source_record
WHEN EXISTS (SELECT 1 FROM source_record
             WHERE id = NEW.id
                OR (source_document_id = NEW.source_document_id
                    AND (record_index = NEW.record_index
                         OR (raw_fingerprint = NEW.raw_fingerprint
                             AND occurrence = NEW.occurrence))))
BEGIN SELECT RAISE(ABORT, 'source_record is immutable'); END;

CREATE TRIGGER record_parse_no_replace BEFORE INSERT ON record_parse
WHEN EXISTS (SELECT 1 FROM record_parse
             WHERE source_record_id = NEW.source_record_id
               AND parser_version = NEW.parser_version)
BEGIN SELECT RAISE(ABORT, 'record_parse is append-only'); END;

CREATE TRIGGER document_coverage_no_replace BEFORE INSERT ON document_coverage
WHEN EXISTS (SELECT 1 FROM document_coverage
             WHERE source_document_id = NEW.source_document_id
               AND account_id = NEW.account_id)
BEGIN SELECT RAISE(ABORT, 'document_coverage is immutable'); END;
