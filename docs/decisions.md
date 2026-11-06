# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

## D-001 Database: SQLite through the standard library — Approved

One SQLite file through stdlib `sqlite3`, using `STRICT` tables, hand-written
SQL and numbered migrations tracked with `PRAGMA user_version`. No ORM.

- Connections use `autocommit=True` with explicit `BEGIN IMMEDIATE`, because the
  legacy mode commits silently before `executescript`.
- Rollback journal rather than WAL for now: one writer, on-demand use, no
  sidecar files to back up. Revisit if the UI needs to read during an import.
- `connect()` never creates a database, so a mistyped path fails instead of
  producing an empty ledger.

## D-002 Encryption — Pending, by M5

Plain SQLite is acceptable only while all data is synthetic. Stdlib `sqlite3`
offers no encryption. Options at M5 are SQLCipher or an encrypted disk image.
New databases are created with `0600` permissions, which is access control and
not encryption.

## D-003 Money: signed integer cents — Approved

- Stored as signed integer cents, negative for money leaving the account or
  charged to a card. Direction is derived from the sign, so the two cannot
  disagree.
- Parsing uses integer arithmetic on the text. This differs from the planned
  `Decimal` route: `Decimal` under the default context rounds past 28 digits,
  and pure integer parsing has no such failure.
- Blank input returns `None` (missing). Malformed input raises an error.
- Sub-cent precision is rejected rather than rounded. Trailing zeros such as
  `12.340` are accepted because the value is exactly representable.
- Amounts outside the SQLite 64-bit integer range are rejected.
- Floats are rejected by type, and pandas stays out of the ledger path.

## D-004 Provenance layers — Approved

`source_document` and `source_record` are immutable, enforced by triggers.
Parser output goes in `record_parse`, one row per record per parser version, so
a parser change adds a row rather than rewriting history. `ledger_transaction`
holds logical transactions, and `transaction_source` links them to records.

## D-005 Document coverage is explicit — Approved

Coverage is what a document claims to contain for one account. It is recorded in
`document_coverage`, per account because one statement can hold several accounts.

| Kind | Meaning |
|---|---|
| `complete` | Every transaction for the account in the date range is present, on a stated date basis, with stated evidence |
| `partial` | The document is known to omit transactions or stop early |
| `unknown` | No evidence either way. This is the default |

Coverage must never be inferred from the earliest and latest transaction dates
alone. A gap in activity looks the same as a gap in the document. `complete`
requires a start date, end date, date basis (transaction or posting) and evidence
(`document_metadata` or `user_declared`), and the database enforces this.

## D-006 Duplicate confidence rules — Approved, implemented in slice 3

Replaces the exact-match rule proposed in the original plan. Exact date, amount
and description across documents is not proof on its own.

All comparisons are within one account.

| Evidence | Outcome |
|---|---|
| Byte-identical file (SHA-256) | Skip and record the attempt |
| Same reliable external ID, same amount | Confident duplicate, whatever the coverage |
| Same reliable external ID, different amount | Possible duplicate |
| Exact match, both documents have `complete` coverage of the date on the same basis, and it is not a boundary date (D-007) | Confident duplicate, paired one-for-one |
| Exact match, coverage partial or unknown on either side | Possible duplicate |
| Exact match on a boundary date | Possible duplicate |
| Exact match, coverage stated on different date bases | Possible duplicate |
| Same amount, date within 3 days or differing description | Possible duplicate |
| Same document, same status | Never merged |

- External IDs count as reliable only if the layout declares them so. Otherwise
  they are ordinary evidence.
- The 3-day window is a starting value.
- Possible duplicates stay separate transactions, both count in totals, and the
  amount at risk is disclosed. Identical-looking rows are flagged as one group
  rather than pairwise, and no merge is chosen for convenience.
- Assumption: a document does not list the same transaction twice. To be tested
  against real samples at M6.

**Known consequence:** ID-less exports without coverage evidence put every
overlapping row into review, and totals stay overstated until resolved. A
`user_declared` coverage option at import is the proposed mitigation, with
group-level resolution in M2.

## D-007 Boundary dates — Approved, implemented in slice 3

A date is a boundary date, and so cannot support a confident match, when either
holds:

- The two documents' shared coverage is that single date, because each may hold
  a different part of the day.
- The date is a document's last covered date and the document was generated that
  same day, because later activity may be missing.

## D-008 One record per document per transaction — Approved

A logical transaction can hold at most one source record from any one document.
This rule limits merging but does not justify it: D-006 still decides whether a
merge happens. The database enforces it with
`UNIQUE (transaction_id, source_document_id)`, and composite foreign keys ensure
a link cannot join a record to a transaction in another account.

Import order must not change the result. Totals and open review items are
compared across orders in acceptance test A16.

## D-009 Stable identity for decisions and corrections — Approved, implemented in M2

- Decisions and overrides reference internal `ledger_transaction.id` and
  `source_record.id` values. These are random, immutable and carry no meaning.
- `raw_fingerprint` and `occurrence` are **supporting evidence only**. They can
  suggest that a new record corresponds to an old one, but they do not guarantee
  that a correction survives a re-export or parser change.
- If an existing decision cannot be confidently mapped to a new record, the
  system raises a review item. It must not silently transfer or discard the
  decision.

## D-010 M1 totals terminology — Approved

Until transfer and card-payment handling exists, totals are labelled **account
inflows**, **account outflows** and **net account movement**. They must not be
described as household income or spending, because they still include transfers
and card payments.

## D-011 Transfer treatment — Approved, implemented in M3

Replaces the proposal to place unconfirmed transfers in a separate group outside
income and spending.

- Confirmed internal transfers are excluded from income and spending.
- Suspected transfers stay visibly unresolved.
- A suspected transfer must not increase the safe-to-spend allowance merely
  because it was identified as a possible transfer. Until confirmed, a suspected
  outflow keeps reducing capacity and a suspected inflow does not add to it.
- A separate "potentially adjusted" view may be proposed, but primary spending
  guidance stays conservative.

## D-012 Card payments without card history — Default, implemented in M3

A card payment whose card was never imported is excluded from spending, with a
warning that spending is understated.

## D-013 Reporting date — Default, implemented in M4

A transaction's month uses transaction date, then posting date, and records which
was used.

## D-014 Financial type before categories — Default

Financial type (transfer, income and so on) belongs to Phase 1A, and category
rules to Phase 1B. Import step 7 does nothing until then.

**Change from the plan:** the plan said M1 would reserve schema for transfers and
balances. The schema instead adds those tables and columns by migration at M3 and
M4, so no unused columns exist whose meaning was guessed early.

## D-015 Accounts are explicit at import — Default

`--account` is required until real layouts show what metadata exists. Institution
plus last four digits is deliberately not unique.

## D-016 Pending edge cases — Default, implemented in M2

Changed amounts between pending and posted (such as tips) are flagged for review.
Stale pending items are flagged, never removed.

## D-017 Archiving — Approved, implemented in M5

Archive by copying, leaving the input file in place.

- This may leave already-processed files in the input folder.
- It consumes additional storage, which must be reported separately (PRD §20).
- Archiving must not affect transaction deduplication or source provenance.
  Identity comes from content hashes and ledger records, never from a file's
  location.

## D-018 Parser strategy — Default

Layouts are declared per format and version, and tested. A layout says how a
document is read, including its sign convention, date meanings, whether external
IDs are reliable and where coverage comes from. No institution layout is claimed
until redacted samples exist and have tests.

## D-019 Workspace and privacy boundaries — Approved

- Work stays inside `personal_finance/`. Parent and sibling directories,
  unrelated project memory, and any file outside this folder need permission
  first.
- All development data is synthetic.
- The M5 real-data gate is mandatory before processing actual documents.

Limits of these controls, as reviewed on 2026-11-05:

- `.gitignore` only stops untracked files being added by default. It does not
  stop `git add -f`, does not affect already-tracked files, and does not stop any
  tool reading a file.
- Files under `tests/fixtures/synthetic/` are deliberately not ignored, so a real
  file placed there could be committed. Only review prevents that.
- Ignoring uppercase extensions such as `.CSV` relies on git's `core.ignorecase`,
  which is on for this repo but is not guaranteed elsewhere.
- Instructions to an AI tool are not an enforcement mechanism. Enforcement comes
  from tool permissions and from keeping real data out of the workspace.
- The repo has no `.claude/settings.json`, no hooks and no `info/exclude` entries.
  User-level Claude settings and the global git configuration are outside this
  folder and were not inspected, so their effect is unknown.
- Keeping real data out of this workspace remains the primary control.

## D-020 Dependencies — Approved

Runtime dependencies: none so far. Development dependencies are pinned in
`requirements-dev.txt`, and were installed once from PyPI into `.venv`.
Application and test execution stay offline, and the test suite blocks sockets.

The package is not installed into the venv. pytest finds it through
`pythonpath = ["src"]`. An editable install would need `setuptools`, which is a
further download, so the CLI entry point is decided in slice 4.

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
