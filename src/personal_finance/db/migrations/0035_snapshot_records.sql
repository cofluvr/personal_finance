-- A record of each snapshot written (D-075 point 7): its ID, schema version, as-of date,
-- window, generation time and content digest. The path is never recorded. Append-only.
CREATE TABLE snapshot_record (
    snapshot_id     TEXT PRIMARY KEY CHECK (length(snapshot_id) = 36),
    schema_version  TEXT NOT NULL CHECK (schema_version GLOB '[0-9]*.[0-9]*'
                                         AND schema_version NOT GLOB '*[^0-9.]*'),
    as_of           TEXT NOT NULL CHECK (date(as_of) IS as_of),
    window_days     INTEGER NOT NULL CHECK (window_days BETWEEN 1 AND 366),
    generated_at    TEXT NOT NULL CHECK (generated_at GLOB
        '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]Z'),
    content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64
                                         AND content_sha256 NOT GLOB '*[^0-9a-f]*'),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER snapshot_record_no_update BEFORE UPDATE ON snapshot_record
BEGIN SELECT RAISE(ABORT, 'snapshot_record is append-only'); END;
CREATE TRIGGER snapshot_record_no_delete BEFORE DELETE ON snapshot_record
BEGIN SELECT RAISE(ABORT, 'snapshot_record is append-only'); END;
CREATE TRIGGER snapshot_record_no_replace BEFORE INSERT ON snapshot_record
WHEN EXISTS (SELECT 1 FROM snapshot_record WHERE snapshot_id = NEW.snapshot_id)
BEGIN SELECT RAISE(ABORT, 'snapshot_record is append-only'); END;
