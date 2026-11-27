-- How a real ledger is protected (D-081). Each real ledger has exactly one protection, set by
-- `pf init --real` and never changed, as the marker row is append-only and never updated.
--
-- encrypted_disk_image: D-058's rules. The folder is on a mounted encrypted disk image, never in a
--   synced folder. Every real ledger made before this migration has it.
-- private_folder: any folder you own outside a git work tree, synced folders such as iCloud Drive
--   included. Its folder, database and originals folder are made private on every open.
ALTER TABLE real_ledger ADD COLUMN protection TEXT NOT NULL DEFAULT 'encrypted_disk_image'
    CHECK (protection IN ('encrypted_disk_image', 'private_folder'));
