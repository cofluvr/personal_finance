# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-057 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
holds the index, the rules in brief, and the newest decisions in full, once there are any. When a
decision here is accepted and the next one is written, move its full text to the end of that file
and keep its index line.

## Index

| Decision | Title and status |
|---|---|
| D-001 | Database: SQLite through the standard library — Approved |
| D-002 | Encryption — Approved in D-058, implemented and accepted in M5.2 |
| D-003 | Money: signed integer cents — Approved |
| D-004 | Provenance layers — Approved |
| D-005 | Document coverage is explicit — Approved |
| D-006 | Duplicate confidence rules — Approved, implemented in slice 3 |
| D-007 | Boundary dates — Approved, implemented in slice 3 |
| D-008 | One record per document per transaction — Approved |
| D-009 | Stable identity for decisions and corrections — Approved, implemented in M2 |
| D-010 | M1 totals terminology — Approved |
| D-011 | Transfer treatment — Approved, implemented in M3 |
| D-012 | Card payments without card history — Default, implemented in M3 |
| D-013 | Reporting date — Default, implemented in M4 |
| D-014 | Financial type before categories — Default |
| D-015 | Accounts are explicit at import — Default |
| D-016 | Pending edge cases — Default, implemented in M2 |
| D-017 | Archiving — Approved, implemented in M5 |
| D-018 | Parser strategy — Default |
| D-019 | Workspace and privacy boundaries — Approved |
| D-020 | Dependencies — Approved |
| D-021 | Representations within one document — Default |
| D-022 | Repeat imports of identical bytes — Default, with approved rules below |
| D-023 | Failure handling — Default |
| D-024 | Coverage is not extraction — Approved |
| D-025 | Security controls proposal — Not applied |
| D-026 | Identifier guarantees are persisted — Approved, implemented in slice 3 |
| D-027 | Effective coverage for metadata claims — Approved, implemented in slice 3 |
| D-028 | Single-day overlaps apply to ID-less matching only — Approved |
| D-029 | Source movement history — Approved, implemented in slice 3 |
| D-030 | Displayed values of a merged transaction — Approved, implemented in slice 3 |
| D-031 | Candidate grouping — Approved as an initial heuristic, implemented in slice 3 |
| D-032 | Description similarity — Approved as an initial heuristic, implemented in slice 3 |
| D-033 | Rule versions and existing accounts — Approved, implemented in slice 3 |
| D-034 | Reconciliation performance — Approved as provisional benchmarks |
| D-035 | Migration is explicit — Approved |
| D-036 | Import summary units — Approved |
| D-037 | No application logging, and a safe CLI boundary — Approved |
| D-038 | Entry point — Approved |
| D-039 | Temporary files during development — Approved |
| D-040 | Review evidence and revision tokens — Approved |
| D-041 | Requirements for later M2 slices — Approved as requirements |
| D-042 | Rejection and the identity constraint model — Approved, implemented and accepted in M2.2 |
| D-043 | Validating decision commands and undo — Approved, implemented and accepted in M2.2 |
| D-044 | Decision conflicts — Approved, implemented and accepted in M2.2 |
| D-045 | Owner's qualifications on M2.2 — Approved, implemented and accepted in M2.2 |
| D-046 | Confirmation, partitions and superseding — Approved, implemented and accepted in M2.3 |
| D-047 | Separating machine-made merges — Approved, implemented and accepted in M2.4 |
| D-048 | New evidence on decided records, and superseding chains — Approved, implemented and accepted in M2.5 |
| D-049 | Value corrections — Approved, implemented and accepted in M2.6 |
| D-050 | Resolving incomplete records — Approved, implemented and accepted in M2.7 |
| D-051 | Coverage correction with history — Approved, implemented and accepted in M2.8 |
| D-052 | Pending to posted — Approved, implemented and accepted in M2.9 |
| D-053 | Financial types — Approved, implemented and accepted in M3.1 |
| D-054 | Transfers across accounts — Approved, implemented and accepted in M3.2 |
| D-055 | Card payments, one-sided transfers and coverage warnings — Approved, implemented and accepted in M3.3 |
| D-056 | Income and spending — Approved, implemented and accepted in M3.4 |
| D-057 | M4 plan: balances and reports — Approved, implemented and accepted in M4 |
| D-058 | M5 plan: the real-data gate — Approved, M5.1 and M5.2 implemented and accepted, M5.3 implemented |

## Rules in brief

One line per approved rule, moved from the handoff. The decision named in the last column governs.

| Decision | Rule | Log |
|---|---|---|
| Coverage correction | Limitation stays until M2. A conflict changes nothing and explains itself. Never recommend deleting the database or editing SQL | D-022 |
| Inclusive end date | A user declaration vouches for the whole end date when generation metadata is absent, under the layout's pending definition. Never assumed for a date range in metadata | D-007 |
| Coverage evidence | Keep user confirmation, validated layout metadata, a non-establishing date range, and unknown or partial coverage distinct | D-005 |
| Coverage versus extraction | Complete coverage does not mean every row parsed. Disclosures stay, and no identities are manufactured | D-024 |
| File and account | A byte-identical file under another account is rejected, never skipped. Existing import preserved. **Verified and tested** | D-022 |
| Candidates | Only plausible candidates enter review. No exact adjustment for ambiguous groups | D-006 |
| One record per document | An initial safeguard, not proof | D-008 |
| Decisions and corrections | Use stable internal IDs. Fingerprints are evidence only | D-009 |
| Transfers (M3) | Suspected transfers never increase safe-to-spend | D-011 |
| Totals wording | Account inflows, account outflows, net account movement | D-010 |
| Repository | Do not move it. Real data needs the M5 gate first | D-019 |
| Security proposal | **Unapplied.** Unverified, and not active protection | D-025 |
| External-ID matching | Validated and account-scoped. A differing description alone does not conflict for a reliable ID, and both are preserved. Conflicts in amount, status or a date present on both records are flagged | D-006 |
| Single-day overlap | ID-less matches stay possible duplicates, including under `user_declared` coverage. An intentional conservative policy, not a mathematical requirement. Does not override a confident reliable-ID match | D-007 |
| Candidate discovery | Needs evidence beyond amount and date: similar merchant or description, a validated identifier, or a documented source-specific relationship. Different descriptions alone are not evidence. The date window is a configurable heuristic. Candidates create review items and never authorize a merge | D-006 |
| Unknown status | Does not conflict with `posted`, for status comparison only. Does not establish identity, and is never filled in as `posted` | D-006 |
| Test-only layout | A synthetic layout with unreliable IDs is allowed in tests for A21. It is not a production layout | [layouts.md](layouts.md) |
| Unresolved rows | Exact matches stay possible duplicates when an unresolved row could plausibly affect the count. Reliable ID matches are not affected | D-024 |
| Identifier guarantees | Stored per document, never reread from Python. The `synthetic_checking_v1` clarification is one-time and synthetic-only | D-026 |
| Metadata coverage | A separate effective interval, with the claimed interval preserved | D-027 |
| Single-day policy | ID-less matching only | D-028 |
| Source movement | Machine-made merges can split. Every record preserved, history append-only, M2 decisions take precedence | D-029 |
| Displayed values | One primary source, no field mixing | D-030 |
| Candidate grouping | Connected groups, bounded by fixed calendar blocks, counted as distinct transactions | D-031 |
| Similarity | Candidate evidence only, with known limits | D-032 |
| Rule versions | Fingerprint of the effective configuration per account | D-033 |
| Performance | Provisional benchmarks for the documented fixtures only. Current locking stays. Not test assertions | D-034 |
| Migration | Explicit, and separate from reconciliation. Read commands stay read-only | D-035 |
| Summary units | Files and source rows are the only partitions. Records accepted are never called transactions created. Account review totals are final state, never sums of per-file snapshots. "Review groups", not "flags" | D-036 |
| Failed files | Row counts are unavailable, or known but rolled back. Never zero, never counted as stored | D-036 |
| Logging | None in M1. The boundary prints a fixed message with exit code 2. Cancellation and a closed pipe are not errors. No dumps on disk | D-037 |
| Entry point | `bin/pf` is verified. `project.scripts` is declared only. A shared-environment clone is a source-checkout check, not a clean install | D-038 |
| Temporary files | pytest temp folders are allowed for synthetic artifacts. Walkthroughs, clones and breaks use `build/` | D-039 |
| Review evidence | `review show` displays data for the one item requested, under `trace`'s terms. Routine output and errors stay clean. Six kinds of evidence stay separate, and missing stays missing | D-037, D-040 |
| Revision token | All material evidence, not membership alone. Deterministic and documented. New inputs join it when they exist, with a version bump | D-040 |
| Later M2 requirements | Corrections and coverage conflicts stay distinguishable. Several overrides on one transaction need a defined effective value | D-041 |
| Rejection | A pair-level assertion. No "reject group", and never an implied "all distinct". Binds source records. Shares one model with confirmation | D-042 |
| Whole-group withholding | An automatic group containing a constrained pair is withheld entirely, with its records separate and counted | D-042 |
| Decision commands | Current account, then account, item ID and token together, under one write lock. Never reconciles for the user. Undo needs the same | D-043 |
| Decision conflicts | Their own `decision_conflict` kind, disclosed on their own line | D-044 |
| Closing an item | By removal. The decision stays in history, and undo can raise a new item | D-045 |
| Rejectable pairs | Direct, undecided candidates only, not two transactions merely sharing a group | D-045 |
| Rejection and the ledger | Must change no totals or memberships, or it refuses atomically | D-045 |
| Undo token | Decision state and everything relevant to regrouping. Undo is never a snapshot restore | D-045 |
| Confirmation | An explicit partition: same within a group, different between groups, nothing about the rest | D-046 |
| A confirmed group | Direct links, one record per document, no two unique IDs, at most 50 transactions | D-046 |
| Confirmed units | Survive new evidence. An automatic merge joins only when valid, else it is withheld | D-046 |
| Settling a conflict | Only by one confirmation's partition. A rejection never settles one | D-046 |
| Superseding | One decision, by a confirmation, naming its token. Every old pair contradicted or kept. Undo restores it or refuses | D-046 |
| Separation | A partition of every record of one transaction, stored as a confirmation targeting it. Groups of several records become confirmed units | D-047 |
| What can be separated | Records joined automatically, including those a confirmed unit absorbed. Not a confirmed core, one record, or a transaction in an open conflict | D-047 |
| Separation and the ledger | May raise totals. Changes only that transaction, raises no conflict, or refuses atomically | D-047 |
| Transaction token | `t1`, over one transaction's material evidence. Item `r3` and undo `d2` unchanged | D-047 |
| Superseding chains | Superseded while anything superseding it is not undone. Only the newest applies and can be undone, one link at a time. 0008 re-derives chain accounts | D-048 |
| New evidence | No decision transfers to a new record. `review show` lists records alike a decided record, binding nothing | D-048 |
| What supersedes what | A confirmation joins apart pairs, a separation splits a confirmation's pairs, a rejection supersedes nothing. One at a time | D-048 |
| Undo token | `d3`, the same fields, so a ledger without chains keeps its digest | D-048 |
| Corrections | Amount, dates and description. Stored apart, applied after derivation, never read by matching. Bind the records of their transaction | D-049 |
| Effective value | Agreeing corrections apply. Disagreeing ones, or one whose records sit in several transactions, leave the source value, disclosed | D-049 |
| Correction chains | D-048's rule. Undo never refuses for contradiction. Confirm and separate refuse to leave a correction unsettled | D-049 |
| Correction tokens | `r4`, `t2` and `d4` add corrections, keeping digests when there are none. `c1` for undo | D-049 |
| Financial types | Nine types and `unclassified`, stated by a person only. Each fits one direction but `transfer` | D-053 |
| A classification | A correction of a field with no source value: D-049's rules, D-048's chains, stored apart | D-053 |
| Type totals | Account movement unchanged. One line per type and one for unclassified | D-053 |
| Classification tokens | `r7`, `t5`, `d6` and `c2` add classifications, keeping digests. `f1` for undo | D-053 |
| Transfers across accounts | Each account derives alone. A person matches two candidates, binding their records, and the outcome is read after both | D-054 |
| Transfer candidates | A person's transfer-kind type on one side, the exact opposite amount in another account, dates within 5 days. Never stored | D-054 |
| Receiving accounts | Card, loan and investment payments may be money in on the account they pay | D-054 |
| One-sided transfers | A person's statement over a transfer-kind transaction, naming a registered counterpart. Refused while the other side may be in view | D-055 |
| Counterpart coverage | A state only when complete coverage on one basis spans every day within 5 days. Less is a warning | D-055 |
| Card payments | Out of spending, matched or one-sided. A one-sided one to a card warns that its spending is understated | D-012, D-055 |
| Income and spending | Five groups, each transaction in one, adding to net account movement: confirmed transfers, income, spending, unconfirmed transfer kinds and unclassified | D-056 |
| Confirmed transfers | A side of an applied match or one-sided transfer, whatever its own type | D-056 |
| Unconfirmed transfer kinds | Neither income, spending nor transfers, disclosed as a bound on both | D-011, D-056 |
| Reporting periods | In M4, with D-013. Totals cover the ledger or one account | D-056 |
| ID lists | One JSON array parameter read with `json_each`, never one SQL parameter per ID | D-057 |
| Balance observations | A posted balance at the end of one day, stated by a person. A card or loan states what it owes, stored negated. One active per account and day. Never transaction evidence | D-057 |
| Statement reconciliation | Consecutive observations, activity after the earlier day through the later one, by effective posting date else transaction date. Agreement is evidence, not coverage, and a difference is never absorbed | D-057 |
| Scale benchmark | 100,000 transactions, 60 months, four accounts, 20,000 matches. Below two seconds per report, provisional, never a test assertion | D-034, D-057 |
| Monthly reports | A transaction's month is its effective transaction date, else its effective posting date. Months add to `totals`, D-056's groups add to each month, and a month is covered only by complete transaction-basis coverage of every day | D-013, D-057 |
| Real ledgers | Real or synthetic, fixed at `init`. Only a real ledger is checked, on every open, and a synthetic one is never promoted | D-058 |
| Real ledger location | Refused inside a git work tree or a synced folder, through a symbolic link, not owned by the user, or open to group or others. Checked, never repaired. Its imports never come from a git work tree | D-019, D-058 |
| Originals | A real ledger keeps each new document's bytes in `originals/` under its SHA-256, `0400`, before the import commits. Never overwritten or deleted. Identity never reads it | D-017, D-058 |
| Encrypted volume | A real ledger's folder is inside, never at the root of, a mounted disk image whose APFS volume honours ownership, and which diskutil reports encrypted or hdiutil reports encrypted as an image. FileVault on the startup volume does not count. Any other answer refuses. Temporary files stay in memory | D-002, D-058 |

## Not yet decided

From `shared-contract.md` §6: safe-to-spend details and loan projection assumptions
(Phase 1B), and pairing protocol and snapshot compatibility (Phase 1C). Transfer matching
was decided in D-054, resource benchmarks in D-057, and backup and recovery in D-058.

## D-058 M5 plan: the real-data gate — Approved, M5.1 and M5.2 implemented and accepted, M5.3 implemented

Proposed on 2026-11-08, and approved by the owner the same day with the lead engineer's
recommendations, including points A to F, with M5.1 approved to build. Each later slice needs its
own approval, as in M3 and M4. Delivers plan.md's M5 (data location outside the repo, encryption,
file permissions, archiving, backup and restore) against PRD §19, §20's storage reporting and §21's
"backups restore records, rules, corrections, and goals" and "core operation succeeds without
internet access". Settles D-002, builds D-017, and keeps D-019 and D-025. Changes none of D-042 to
D-057. Acceptance tests, H1 to W4, are in [plan.md](plan.md).

```sh
pf init           --db DB [--real]
pf storage        --db DB
pf archive verify --db DB
pf backup create  --db DB --to DIR
pf backup verify  --from BACKUP
pf backup restore --from BACKUP --to NEW_DB
```

**Slices:**

| Slice | Scope |
|---|---|
| M5.1 | Real ledgers, their location and file permissions |
| M5.2 | Encryption: an encrypted volume, checked on every open (D-002) |
| M5.3 | Archiving originals, and storage by kind (D-017) |
| M5.4 | Backup, verification and restore |
| M5.5 | Network and dependency behaviour, and the readiness checklist |

**Recommendations:**

1. **A ledger is synthetic or real, fixed at `init`.** Migration 0017 adds `real_ledger`, holding
   one row on a real ledger and none on a synthetic one. Triggers refuse the row in a ledger holding
   an account or an import run, and any change or removal of it. Existing ledgers and every `init`
   without `--real` are synthetic and behave exactly as now, so every existing test, token and
   output is unchanged. Only a real ledger runs the gates below, on every open, read-only commands
   included. A synthetic ledger is never promoted: real data starts in a new
   real ledger.
2. **A real ledger's location** is refused, naming the rule, when the database or its directory:
   does not exist yet (the folder); is inside any git work tree, this repository included (a
   `.git` in it or any parent); is inside a known synced folder (`~/Library/Mobile Documents`,
   `~/Library/CloudStorage`, `~/Dropbox`); is reached through a symbolic link at any step; is not
   owned by the user; or grants any group or other permission, so `0700` and `0600` pass. It checks
   rather than repairs: a wrong mode is refused with the `chmod` to run, never changed silently
   (fail fast). Files a real ledger imports are refused from inside a git work tree too.
3. **Encryption by an encrypted APFS volume, not SQLCipher (D-002).** The owner creates an
   encrypted disk image with Disk Utility or `hdiutil`, and keeps its password themselves, not in
   the login Keychain (corrected by the owner on 2026-11-08).
   The application holds no key, password or secret, so PRD §19's "secrets kept out of source code
   and ordinary configuration" holds by having none, and no dependency is added (D-020). On every
   open, a real ledger's directory must be on a volume that `diskutil info -plist` reports as
   encrypted, read with `plistlib`. An unknown answer, a missing key or a failed probe refuses
   (fail closed). Tests replace the probe, so the suite never mounts a volume. One walkthrough on
   a real encrypted image is the owner's, or needs their approval, since mounting writes outside
   the repository.

   **Amended by the owner on 2026-11-08, approving M5.2.** FileVault does not satisfy point A. The
   probe requires a mounted disk image that is not the startup volume, as well as encryption, and
   a ledger on the FileVault-encrypted startup volume is refused. The real ledger lives in a `0700`
   folder inside the mounted volume, never at its root. M5.5's checklist moves the owner's
   statements into the image.

   **Amended again by the owner on 2026-11-09, after M5.2's review.** An image encrypted as a file
   (`hdiutil create -encryption`) is accepted too, though diskutil reports its APFS volume
   unencrypted: `hdiutil info -plist` must show exactly one attached image backing the volume's
   device at its mount point, and that image must report itself encrypted. hdiutil joins diskutil
   as the second outside call, and point 9 allows both.
4. **Caches stay on that volume.** A real ledger runs with `PRAGMA temp_store = MEMORY`, so SQLite
   writes no sort or index spill to the system temp folder. Its rollback journal sits beside the
   database, and a test shows it gets `0600`. The application writes no other cache, and no log
   (D-037).
5. **Originals are archived by copying on import (D-017),** for a real ledger only, into
   `originals/` beside the database, named by the document's SHA-256, written to a temporary name,
   synced, renamed into place and set `0400`. Identity still comes from content and ledger
   records, never the location. The copy is made before the import commits, and a failed copy
   fails the file (`archive_failed`) with nothing kept. A copy left by a rolled-back import is
   harmless, since its name is its content, and `pf storage` counts it as not referenced.
   `pf archive verify` rehashes every original and lists missing, altered and unreferenced ones.
   Nothing is ever deleted (PRD §19, "until explicit deletion"), and no deletion command is built.
6. **`pf storage`** reports software, database (with its journal), originals and backups apart
   (PRD §20), in bytes and file counts. Backups are counted only for destinations recorded in the
   ledger by `backup create`.
7. **A backup is a new directory,** never an overwrite: the ledger copied with SQLite's online
   backup API (`Connection.backup`), every referenced original, and a `manifest.json` holding each
   file's SHA-256 and size, the schema version, the code version and a logical digest: every
   table's rows in primary-key order, hashed. The destination passes recommendation 2's and 3's
   checks and must not be on the ledger's own volume, so one lost disk is not both copies. A
   backup holds the whole ledger, so records, rules fingerprints, decisions, corrections,
   classifications, matches and observations are all in it, and goals will be once they exist.
8. **Restore never overwrites.** `pf backup restore` writes to a new path that passes every gate,
   then checks the manifest's hashes, `PRAGMA integrity_check` and `foreign_key_check`, the schema
   version against the code (as `open_ledger`), and the logical digest, and refuses on any
   difference with nothing left behind. `pf backup verify` runs the same checks without
   restoring. **The restore test** compares every report, list and token of the restored ledger
   with the original's, byte for byte, on generated ledgers, and every original by hash.
9. **No network, and it is shown.** A test reads every module under `src/` and refuses an import
   of `socket`, `ssl`, `http`, `urllib`, `ftplib`, `smtplib` or `subprocess` outside the
   `diskutil` and `hdiutil` calls in `db/volume_probes.py` (point 3, as amended). The existing socket guard stays. The no-network and dependency behaviour is
   written down once, in status.md.
10. **Readiness is a checklist, not code.** M5.5 writes `docs/real-data-readiness.md`: the steps
    the owner takes before the first real document (create the encrypted image, `init --real` on
    it, a backup to a second encrypted volume and a restore of it, `archive verify`), each with the
    command and its expected output. M6 starts only once the owner has run it.

**Not in M5,** each left visible rather than guessed: real layouts (M6), deleting originals,
scheduled or rotated backups, backups to a network or cloud service, a key or password the
application manages, encrypting a synthetic ledger, other operating systems, F2's timestamp marker
(needed only before a UI or export shows legacy timestamps), and the security proposal (point E).

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. An encrypted APFS volume.** No dependency, no key in the application, and the gate is
  checkable. Its limit: while mounted, anything running as the user can read it, as with any file.
  Alternatively SQLCipher, which encrypts the file itself but adds a native dependency, a key the
  application must obtain, and still leaves originals and backups to encrypt separately.
- **B. A real or synthetic ledger fixed at `init`,** so tests and walkthroughs stay as they are.
  Alternatively every ledger passes the gates, with tests replacing the checks, which leaves
  `build/` walkthroughs refused.
- **C. Archiving inside import,** so no real document is kept without its original.
  Alternatively a separate `pf archive add`, which can be forgotten.
- **D. A directory backup with a manifest.** Plain files, checked by hash. Alternatively one
  `zipfile` archive, which is one file to move but must be unpacked to check.
- **E. The security proposal stays a separate owner action.** M5 does not apply it (D-025, and
  this session's "no security changes"). The readiness checklist asks the owner to decide on it
  and, if applied, to run its own verification table. The primary control is unchanged: real data
  stays outside this workspace (D-019).
- **F. A tripwire, recommended against.** A real ledger could refuse to open when `CLAUDECODE` is
  set in the environment, which Claude Code sets in its shells. It stops an accident only, is
  trivially bypassed, and may be read as a control it is not. Recommended against, unless the
  owner wants it as a reminder.

**Inputs needed from the owner before M5.2 and M5.4 are built** (PRD §22): the macOS version, the
data destination and the backup destination, both on encrypted volumes the owner creates.

**How M5.1 was implemented,** where recommendations 1 and 2 left a choice. Approved to build by the
owner on 2026-11-08, built the same day, and accepted as built:

- The mark is the presence of `real_ledger`'s one row, with no kind column to keep consistent.
  `init --real` checks the location, creates the ledger as before, then writes the row. A failure
  between the two leaves an empty synthetic ledger, which a repeat `init --real` refuses to
  overwrite, as `init` always has.
- The link rule compares the absolute path with the resolved one, so a link anywhere on the way,
  the database itself included, refuses. macOS's `/tmp` and `/var` are links, so no real ledger
  lives under them.
- `open_ledger` and `migrate`, the only two ways a command opens a ledger, check it before the
  schema version, so an unsafe ledger is refused before anything else is said about it.
- Privacy is no group or other permission bit, not an exact mode, and the refusal names the
  `chmod` that fixes it. Ownership compares with the effective user.
- An import checks every file before importing any, so a refusal imports nothing. The search for
  `.git` follows links.
- **Not detected:** iCloud's Desktop and Documents sync makes `~/Desktop` and `~/Documents` synced
  with no folder from the list in the path, and the path alone cannot tell. M5.5's checklist asks
  the owner to rule it out.
- pytest's temporary folder can sit inside this repository, a git work tree, so the tests treat a
  work tree found above their own folder as absent and still find one made inside it.

**How M5.2 was implemented,** under point 3 as amended. Approved to build by the owner on
2026-11-08, built the same day on synthetic data, and accepted as built on 2026-11-09. The second
amendment followed:

- **The keys** come from real `diskutil info -plist` output on macOS Golden Gate 27.2: the startup
  Data volume, run on this repository's volume, and the owner's empty image, with their approval.
  A real ledger needs `MountPoint` equal to its folder's mount point, `BusProtocol` `Disk Image`
  (the startup volume reports `Apple Fabric`), `FilesystemType` `apfs`, and `Encryption` and
  `GlobalPermissionsEnabled` each the boolean `true`. A non-zero exit, an `Error` key, output that
  is not a plist dictionary, or a missing key or other type refuses. Messages name the mount point,
  never a value diskutil returned.
- diskutil refuses a folder ("Could not find disk"), so the probe walks up to the nearest mount
  point and asks about that. A ledger whose folder is the mount point is refused before asking.
  Under the startup Data volume the walk reaches `/` through its firmlinks, which is refused as
  not a disk image either way.
- **Encryption of the image file alone is not reported by diskutil.** The owner's image, made with
  `hdiutil create -encryption AES-256`, holds an APFS volume reporting `Encryption` false, while
  `hdiutil isencrypted` says YES. Under the second amendment, a volume diskutil does not report
  encrypted is looked up in `hdiutil info -plist` (keys from a real run, with the owner's
  approval): `images`, each with `system-entities` holding `dev-entry` and `mount-point`, and
  `image-encrypted`. The entity must be `/dev/` plus diskutil's `DeviceIdentifier`, at the same
  mount point, in exactly one image, and `image-encrypted` the boolean `true`. hdiutil is asked
  only when diskutil does not report encryption.
- **Ownership on a mounted image must be checked on the real image.** A new image ignored
  ownership (`GlobalPermissionsEnabled` false), which makes M5.1's owner and mode checks
  meaningless, so the probe refuses it and names `sudo diskutil enableOwnership`. The rule was
  added with the owner after the real image showed it. On 2026-11-08 the owner enabled ownership,
  and the ledger folder was shown `drwx------`, owned by the owner.
- `db/volume_probes.py` holds the application's only subprocess calls: `/usr/sbin/diskutil` and
  `/usr/bin/hdiutil` by their full paths, through one runner with a 30-second timeout, and failing
  to run either refuses. Tests replace both with recordings in
  `tests/fixtures/synthetic/volume_probes`, so the suite never runs them or mounts a volume.
- `temp_store = MEMORY` is set by the same check that every open of a real ledger runs, before
  `migrate` migrates. `init --real` migrates its empty ledger before the mark, so it holds nothing
  to spill. SQLite unlinks temporary files as it opens them, so the test reads the temp folder's
  modification time in a child process, since SQLite reads `SQLITE_TMPDIR` once per process. The
  same sort on a synthetic ledger is the control that shows it spills.
- **Point 4's journal needs no code.** SQLite gives a journal its database's mode whatever the
  umask, and a test shows `0600` beside the database with the umask cleared.
- **Not detected:** whether the image's password is strong or where it is kept, and where the
  image file itself lives. It is not under `/Volumes`, so the synced-folder rule does not see it.

**How M5.3 was implemented,** where recommendations 5 and 6 left a choice. The owner approved the
lead engineer's recommendations on 2026-11-09, and it was built the same day on synthetic data. It
awaits review. No migration: `import_attempt.failure_code` takes any code.

- **The bytes archived** are the ones read once, hashed and parsed, never a second read of the
  file. The copy is the last step before `COMMIT`, so a file that fails to parse leaves none.
- **A file already holding the name** is rehashed. Matching bytes are kept as the original,
  untouched. Anything else, a link or a folder included, fails the import as `archive_failed` and
  is never overwritten, so `archive verify` shows it altered.
- **The folder** is `originals/` beside the database, flat, with no extension on a name. `import`
  creates it `0700` before importing, and `import`, `archive verify` and `storage` refuse it when it
  is a link, not a folder, not owned by the user or open to group or others. Ordinary opens do not
  check it. A copy is written to `.<hash>.<random>.partial` with `O_EXCL`, synced, set `0400`,
  renamed, and the folder synced. A failed copy removes its partial file.
- **A repeat import copies nothing,** even when its original is missing: `archive verify` reports
  that.
- **`archive verify`** lists missing and altered originals with their document, and every other
  entry as not referenced. It exits 1 unless the archive is intact, and refuses a synthetic ledger.
- **`storage`** counts every file under the installed `personal_finance` package as software, not
  the interpreter or `.venv`. The database counts with any `-journal`, `-wal` and `-shm` beside it.
  Originals are split into referenced and not referenced. Sizes are exact bytes, read without
  following links. Backups read "none recorded" until M5.4 adds the table recording them.
- **Not handled:** two real ledgers in one folder share `originals/`, and each lists the other's
  originals as not referenced.
