# Real-Data Readiness Checklist

The steps the owner takes before the first real document (D-058 point 10, M5.5). M6 starts only
once the owner has run them. Each `pf` step gives its command and the output to expect. Each macOS
step is followed by a `pf` step that checks its result.

Every `pf` step was walked through on synthetic data in `build/`, with the volume probes answered
by the suite's recordings (`build/walkthrough_m5_5.py`, not kept). No disk image was mounted there,
and the macOS steps were not run. This document gives the paths the owner named: the ledger's
image `~/CommonCents.sparsebundle` mounted at `/Volumes/CommonCents`, and the backup image kept in
`~/CommonCents_LocalBackups` (D-058 point 7, as amended). `IDs`, digests, dates and sizes differ
on each run.

No real layout exists until M6, so nothing here imports a real statement. The ledger is created,
backed up and restored empty, which tests the gates and the backup on the owner's own volumes.

Run `pf` as `bin/pf` from this checkout. Below, `L` is `/Volumes/CommonCents/ledger/ledger.db` and
`B` is `/Volumes/CommonCentsBackups/backups`.

## 1. Settings outside pf

Each is the owner's, and none can be checked by `pf`.

1. **iCloud Desktop and Documents is off.** System Settings, Apple Account, iCloud, iCloud Drive.
   `~/Documents/commoncents_data` would sync otherwise. Confirmed off on 2026-11-08: check again.
2. **Neither image's password is in the login Keychain** (D-058 point 3, as corrected). Keychain
   Access, search for `CommonCents`: no entry.
3. **Time Machine.** If it runs, it copies `~/Documents/commoncents_data` unencrypted unless that
   disk is encrypted or the folder excluded. The images copy as encrypted files.
4. **The security proposal** ([security-controls-proposal.md](security-controls-proposal.md))
   stays unapplied unless the owner decides otherwise (D-025, D-058 point E). If applied, run its
   own verification table.

## 2. The ledger's image

The image exists, encrypted as a file, with ownership enabled and `/Volumes/CommonCents/ledger`
`0700` (checked 2026-11-09). Mount it, then:

```sh
pf init --db /Volumes/CommonCents/ledger/ledger.db --real
```

```text
Created real ledger /Volumes/CommonCents/ledger/ledger.db
```

Any `Error:` line means a gate refused, and it names the rule and the fix. Nothing is created. For
example, on the startup volume:

```text
Error: a real ledger must be on a mounted disk image, and /System/Volumes/Data is not one. FileVault on the startup volume does not count
```

Then add each account, for example:

```sh
pf account add --db L --name Checking --type checking
```

```text
Added account Checking: <ID>
```

```sh
pf archive verify --db L
```

```text
Originals intact: 0
Missing: 0
Altered: 0
Not referenced: 0
The archive is intact.
```

## 3. The statements, into the image

```sh
mkdir -m 700 /Volumes/CommonCents/statements
```

Copy the statements from `~/Documents/commoncents_data` into it. `pf` imports from there in M6, and
keeps each imported file's bytes in `/Volumes/CommonCents/ledger/originals`. Recommended: once a
verified backup holds them (step 5, after the first import in M6), remove the copies outside the
image, which only FileVault protects. Deleting them is the owner's decision.

## 4. The backup image

Created once, in the owner's folder, with its own password:

```sh
hdiutil create -size 2g -type SPARSEBUNDLE -fs APFS -encryption AES-256 \
    -volname CommonCentsBackups ~/CommonCents_LocalBackups/CommonCentsBackups.sparsebundle
hdiutil attach ~/CommonCents_LocalBackups/CommonCentsBackups.sparsebundle
sudo diskutil enableOwnership /Volumes/CommonCentsBackups
mkdir -m 700 /Volumes/CommonCentsBackups/backups
```

A new image ignores ownership until `enableOwnership` runs (M5.2), and `pf` refuses it until then,
naming the command. This image shares the internal disk with the ledger's, so a backup on it does
not survive losing that disk or the Mac (D-058 point 7, as amended). A second copy on an external
drive would.

## 5. A backup, verified

```sh
pf backup create --db L --to B/2026-11-10
```

```text
Backup written to /Volumes/CommonCentsBackups/backups/2026-11-10
Ledger: real, with 0 originals
Files: <bytes> bytes in 2 files, each matching the manifest
SQLite integrity and foreign key checks: ok
Schema version: 18
Logical digest: <digest>, matching the manifest
Recorded in the ledger. To check it later, run: pf backup verify --from /Volumes/CommonCentsBackups/backups/2026-11-10
```

With documents, the files are the ledger, the manifest and one per original. Each later backup
goes into a new folder: `--to` never names an existing one.

```sh
pf backup verify --from B/2026-11-10
```

```text
Ledger: real, with 0 originals
Files: <bytes> bytes in 2 files, each matching the manifest
SQLite integrity and foreign key checks: ok
Schema version: 18
Logical digest: <digest>, matching the manifest
The backup is intact.
```

A backup on the ledger's own volume is refused, writing nothing:

```sh
mkdir -m 700 /Volumes/CommonCents/elsewhere
pf backup create --db L --to /Volumes/CommonCents/elsewhere/backup
```

```text
Error: a backup must be on a mounted volume other than the ledger's, and /Volumes/CommonCents/elsewhere/backup is on /Volumes/CommonCents
```

## 6. A restore, checked

Into a new folder, never over the ledger:

```sh
mkdir -m 700 /Volumes/CommonCents/restore-test
pf backup restore --from B/2026-11-10 --to /Volumes/CommonCents/restore-test/ledger.db
```

```text
Restored /Volumes/CommonCents/restore-test/ledger.db from /Volumes/CommonCentsBackups/backups/2026-11-10
Ledger: real, with 0 originals
Files: <bytes> bytes in 2 files, each matching the manifest
SQLite integrity and foreign key checks: ok
Schema version: 18
Logical digest: <digest>, matching the manifest
```

```sh
pf archive verify --db /Volumes/CommonCents/restore-test/ledger.db
diff <(pf totals --db L) <(pf totals --db /Volumes/CommonCents/restore-test/ledger.db)
```

`archive verify` prints `The archive is intact.`, and `diff` prints nothing. The restore-test
folder is then the owner's to keep or remove: `pf` deletes nothing.

## 7. Storage

```sh
pf storage --db L
```

```text
Software: <bytes> bytes in <n> files (the personal_finance package; the Python interpreter and its environment are not counted)
Database: <bytes> bytes in 1 files (the ledger with its journal)
Originals: 0 bytes in 0 files referenced, 0 bytes in 0 files not referenced
Backups: <bytes> bytes in 2 files in 1 recorded, as written; their volumes are not read
  <time> /Volumes/CommonCentsBackups/backups/2026-11-10: <bytes> bytes in 2 files
```

## 8. Closed when unmounted

Eject `/Volumes/CommonCents`, then:

```sh
pf totals --db L
```

```text
Error: database not found: /Volumes/CommonCents/ledger/ledger.db
```

Once every step gives its expected output, the gate is open for M6's first layout.
