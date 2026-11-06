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
- Amounts outside the SQLite 64-bit integer range are rejected, and text over 64
  characters is rejected before any conversion. Every failure on text input is a
  `MoneyParseError`, so one bad row cannot crash an import.
- SQLite `SUM` raises an error on overflow rather than returning a float. Reports
  must keep using `SUM`, not `TOTAL`.
- Floats are rejected by type, and pandas stays out of the ledger path.

## D-004 Provenance layers — Approved

`source_document` and `source_record` are immutable, enforced by triggers.
Parser output goes in `record_parse`, one row per record per parser version, so
a parser change adds a row rather than rewriting history. `ledger_transaction`
holds logical transactions, and `transaction_source` links them to records.

`INSERT OR REPLACE` does not fire delete triggers, so migration `0002` adds
before-insert triggers to refuse it.

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

A user declaration must state the account, inclusive start and end dates, the date
basis, and an explicit claim of complete coverage for that interval. It is stored
with evidence `user_declared`. Without one, coverage stays unknown.

Complete coverage says only that nothing inside the interval is missing. Rows
outside the interval are allowed and carry no claim. What complete means for
pending transactions is defined per layout in [layouts.md](layouts.md).

Four kinds of evidence must stay distinct:

| Evidence | Stored as | Establishes completeness? |
|---|---|---|
| Explicit user confirmation | `complete`, `user_declared` | Yes, including the whole end date (D-007) |
| Validated layout metadata | `complete`, `document_metadata` | Yes, within the limits of D-007, and only where the layout declares that its metadata means this |
| A date range that does not establish completeness | `partial` | No |
| Unknown or partial coverage | `unknown` or `partial` | No |

A bare date range is not a claim of completeness. In `synthetic_checking_v1`, dates
without a `coverage-kind` fail the file. A real layout whose statement period does
not prove completeness records it as `partial` (M6).

## D-006 Duplicate confidence rules — Approved, implemented in slice 3

Replaces the exact-match rule proposed in the original plan. Exact date, amount
and description across documents is not proof on its own.

All comparisons are within one account.

| Evidence | Outcome |
|---|---|
| Byte-identical file (SHA-256) | Skip and record the attempt |
| Same reliable external ID, compatible material fields | Confident duplicate, whatever the coverage |
| Same reliable external ID, conflicting amount or other material field | Possible duplicate |
| Same reliable external ID repeated within either document | Possible duplicate |
| Exact match, both documents have `complete` coverage of the date on the same basis, the row falls within both claims, it is not a boundary date (D-007), and no unresolved row could affect the count (D-024) | Confident duplicate, paired one-for-one |
| Exact match, coverage partial or unknown on either side | Possible duplicate |
| Exact match on a boundary date | Possible duplicate |
| Exact match, coverage stated on different date bases | Possible duplicate |
| Same amount, within the date window, with additional evidence (below) | Possible duplicate |
| Same amount and date, with no additional evidence | Not a candidate |
| Same document, same status | Never merged |

- External IDs count as reliable only if a validated layout declares them so, and
  they are scoped to one account. Otherwise they are ordinary evidence.
- Reliable-ID matching is separate from heuristic candidate discovery. It runs on
  its own evidence, and neither path substitutes for the other.
- Material fields are amount, settlement status, and any date present on both
  records. A date missing from one record is compatible and is not filled in from
  the other. A differing description alone is not a conflict for a reliable ID
  (Approved), but both are preserved.
- A pending row and a posted row sharing an ID conflict on status, so they stay
  flagged until M2.
- `unknown` status does not conflict with `posted`, for status comparison only. It
  does not establish identity, and source statuses are preserved: `unknown` is
  never filled in as `posted`. Pending-to-posted reconciliation remains M2.
- Heuristic candidates need additional evidence beyond amount and date: a matching
  or sufficiently similar merchant or description, a validated external identifier,
  or another documented source-specific relationship. Different descriptions alone
  are not positive matching evidence.
- The bounded date window is a configurable heuristic, starting at 3 days. It is not
  proof of identity.
- Candidate discovery creates review items. It never authorizes an automatic merge.
- Only plausible candidates enter review: a row needs a real counterpart in
  another document. Unknown coverage alone never flags a row.
- Possible duplicates stay separate transactions and both count in totals, so
  totals may be overstated, and summaries must say so. Identical-looking rows are
  flagged as one group rather than pairwise, and no merge is chosen for convenience.
- Any amount shown for candidates is a disclosure and not an exact adjustment.
  Overlapping groups can make a single adjustment figure meaningless, so none is
  presented as one.
- Assumption: a document does not list the same transaction twice. To be tested
  against real samples at M6.

**Known consequence:** in ID-less exports without coverage evidence, rows with a
counterpart in another document go to review, and totals stay overstated until
resolved. Declaring coverage at import (D-005) avoids this, and group-level
resolution arrives in M2.

## D-007 Boundary dates — Approved, implemented in slice 3

These rules apply to ID-less matching based on occurrence and coverage. A date is
a boundary date, and so cannot support a confident match, when any of these holds:

- The two documents' shared coverage is that single date. This is an intentional
  conservative initial policy, not a mathematical requirement: two complete claims
  could in principle justify a match, but a wrong flag costs one review while a
  wrong merge hides a real purchase. It applies to `user_declared` coverage too.
- The date is the last covered date of a `document_metadata` claim, and the
  document was generated that same day, because later activity may be missing.
- The date is the last covered date of a `document_metadata` claim and the document
  gives no generation date. The end date is not assumed complete.

The last two do not apply to `user_declared` coverage. A user declaration vouches
for the entire inclusive end date, even when generation metadata is absent. The
user is confirming full coverage of that interval under the layout's pending and
posted definition. This assumption is never applied automatically to a date range
found in document metadata.

Boundary dates do not override a confident match based on a validated,
account-scoped external ID with compatible material fields.

Amended by D-027 (effective interval for metadata claims) and clarified by D-028
(single-day scope).

## D-008 One record per document per transaction — Approved

A logical transaction can hold at most one source record from any one document.
The database enforces this with `UNIQUE (transaction_id, source_document_id)`, and
composite foreign keys stop a link joining a record to a transaction in another
account.

This is an initial deduplication safeguard. It stops automatic matching collapsing
legitimate repeated purchases. It limits merging and never justifies one: D-006
still decides that. **It is not proof that a document cannot contain two
representations of one financial event.**

Where it applies: rows of the same status in a tested layout, which that layout
treats as separate events.

Where it does not hold, such as a pending and posted version in one export, or one
external ID repeated within a document, the rows are kept and flagged under D-021
rather than silently treated as separate expenses.

If M2 needs one event to hold two records from a document, a migration replaces
the constraint with a partial unique index that exempts reviewed links. A test
proves that this migration works on populated data.

Import order must not change the result. Acceptance test A16 compares financial
totals, source associations and unresolved candidate relationships across orders,
and does not compare generated IDs or display order.

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
- Local commits on the feature branch are approved. Every push needs the owner's
  explicit approval. The owner's own push of `c75aee0` was intentional.

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
further download. Until slice 4 decides the entry point, the CLI runs as
`PYTHONPATH=src .venv/bin/python -m personal_finance`.

## D-021 Representations within one document — Default

Import keeps every row of a document as its own transaction, and flags evidence
that two rows may be one event:

| Evidence within one document | Rule |
|---|---|
| Same external ID on more than one row | `same_document_repeated_external_id` |
| Pending and posted rows, same amount and description, dates within 3 days | `same_document_pending_posted` |

Flagged rows stay separate and count in totals until reviewed in M2. This only
flags. Pending-to-posted reconciliation remains M2. Identical rows with the same
status are not flagged, because a tested layout treats them as separate events.

## D-022 Repeat imports of identical bytes — Default, with approved rules below

A byte-identical file is one document. Importing it again changes no ledger data
and records an `already_imported` attempt, except where the new request
contradicts what was recorded. A different account, layout or coverage declaration
is a failed attempt, with nothing changed, and is never reported as already
imported.

File and account (Approved): a byte-identical file under a different account is
rejected clearly and never skipped, and the existing import is preserved. Tests
confirm this.

Coverage correction (Approved): the limitation stays until M2 adds a correction and
history workflow. A conflict leaves existing data unchanged and explains the
limitation. Deleting the database or editing SQL directly must not be recommended
as a workaround.

## D-023 Failure handling — Default

Each file is imported in one database transaction, holding the write lock from
the duplicate check to commit, so a failed import leaves no records or
transactions. Failed attempts are recorded afterwards with a fixed code. A bad row
goes to the unresolved queue, and only a document-level problem fails the file.

Failure codes and reason codes never contain file contents.

## D-024 Coverage is not extraction — Approved

Complete source coverage does not mean every row was parsed successfully. Coverage
describes the document, and parsing describes what was read from it.

- Unresolved-row disclosures always remain, whatever the coverage.
- Completeness must not be used to conceal extraction failures or to manufacture
  transaction identities.
- For slice 3 (Approved): one-for-one pairing relies on counts, and an unresolved row
  can distort a count. Exact matches are only possible duplicates when either
  document has an unresolved row that could fall on that date, including one whose
  date is unknown. A reliable external ID match is not affected.

## D-025 Security controls proposal — Not applied

[security-controls-proposal.md](security-controls-proposal.md) is unapplied. Its
version requirements and VS Code behaviour are unverified, and it must not be
described as active protection.

## D-026 Identifier guarantees are persisted — Approved, implemented in slice 3

- Each document stores how it was interpreted at import: layout, parser version,
  ID namespace, ID guarantee, and whether pending rows fall inside its coverage
  claim. Reconciliation reads this stored evidence, never current Python
  configuration, so a code change cannot silently reinterpret history.
- A layout definition that differs from what is stored for the same layout and
  parser version fails the import.
- The same ID in a validated namespace, with compatible material fields, is a
  confident match (D-006). Different IDs establish distinctness only in a validated
  namespace whose layout guarantees stable, unique transaction identifiers.
- Temporary limitation: an ID-bearing row against an ID-less row can only be a
  possible duplicate. Revisit for CSV-to-PDF matching (M7).

One-time clarification: `synthetic_checking_v1` IDs are declared stable and unique
within the layout's account-scoped namespace. This is allowed once, because the
layout is invented and synthetic-only. It does not generalize: changing a real
layout's guarantee needs explicit versioning and a migration decision.

Checked before backfilling: the CSV fixtures for this layout repeat no ID and reuse
none across files. The inline row in `test_a_repeated_external_id_stays_visible_and_counted`
is an intentional violation (A29). A repeated ID stays flagged under D-021.

## D-027 Effective coverage for metadata claims — Approved, implemented in slice 3

Amends D-007. The claimed interval stays in `document_coverage` unchanged as source
evidence. Matching derives a separate effective interval.

| Coverage | Effective end |
|---|---|
| `document_metadata` with `generated_on` | The earlier of `coverage_end` and the day before `generated_on` |
| `document_metadata` without `generated_on` | The day before `coverage_end` |
| `user_declared` | `coverage_end`. This restriction does not apply |

- Dates after the generation date do not establish complete coverage.
- The generation day itself stays excluded: date-only metadata cannot show that the
  day was complete.
- Missing or inconsistent metadata is never read as stronger evidence.

## D-028 Single-day overlaps apply to ID-less matching only — Approved

The single-day policy in D-007 applies only to ID-less, coverage-based matching, for
every kind of coverage evidence. A validated, account-scoped external ID with
compatible material fields can establish a confident match when coverage overlaps
for one day, is unknown, or is otherwise insufficient for ID-less matching. A45 is
the direct regression test.

## D-029 Source movement history — Approved, implemented in slice 3

- Automatic splits are allowed for machine-generated merges only. Explicit user
  decisions take precedence from M2, and no automatic reconciliation may silently
  overturn one.
- Every source record is preserved. An append-only history records each move between
  transactions, with the reason, the rules version and the triggering document.
- Each record keeps its original transaction identity. A group's public ID is the
  original ID of its earliest-imported record, so a split can revive a retired ID.
- `trace` distinguishes current membership from historical moves. A retired ID whose
  records now sit in several transactions lists all of them, never a single target.
- Source grouping is deterministic for a given set of documents and rules, and can
  change as documents arrive. This is separate from public ID stability.
- Applying merges and splits is atomic with the import.

## D-030 Displayed values of a merged transaction — Approved, implemented in slice 3

A merged transaction shows all its values from one primary source record, chosen
deterministically, with no mixing of fields between records. It may show `posted`
when its primary source is posted. An `unknown` source status stays unchanged in
`record_parse` and `trace`. Pending-to-posted reconciliation remains M2.

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
