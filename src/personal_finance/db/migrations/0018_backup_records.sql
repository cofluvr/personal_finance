-- Backups recorded by `pf backup create`. Rules are in docs/decisions.md D-058.

-- One row per backup, written once the new backup folder has passed every check `pf backup verify`
-- runs. The backup itself is copied before its row is written, so it holds only the rows of earlier
-- backups. Sizes are as written, so `pf storage` reports them without reading the backup's volume.
CREATE TABLE backup_record (
    id              TEXT PRIMARY KEY,
    backup_folder   TEXT NOT NULL,
    byte_count      INTEGER NOT NULL CHECK (byte_count >= 0),
    file_count      INTEGER NOT NULL CHECK (file_count >= 2),
    logical_digest  TEXT NOT NULL CHECK (length(logical_digest) = 64),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE TRIGGER backup_record_no_update BEFORE UPDATE ON backup_record
BEGIN SELECT RAISE(ABORT, 'backup_record is append-only'); END;
CREATE TRIGGER backup_record_no_delete BEFORE DELETE ON backup_record
BEGIN SELECT RAISE(ABORT, 'backup_record is append-only'); END;
CREATE TRIGGER backup_record_no_replace BEFORE INSERT ON backup_record
WHEN EXISTS (SELECT 1 FROM backup_record WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'backup_record is append-only'); END;
