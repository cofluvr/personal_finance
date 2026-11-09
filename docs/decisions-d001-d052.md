# Decision Log: Full Text of D-001 to D-061

Moved out of [decisions.md](decisions.md) on 2026-11-08, unchanged, D-053 once D-054 was written, D-058 once D-059 was, D-059 once D-060 was, D-060 once D-061 was, and D-061 once D-062 was. The index, the rules in brief and
the newest decisions are in decisions.md. Status values are defined there. Read a decision here
when a task touches it: search for its heading, such as `## D-049`.

The handoff's "as built" sections and follow-ups named below are now in
[archive/handoff-history.md](archive/handoff-history.md). Measurements placed in status.md are now in
[benchmarks.md](benchmarks.md).

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

Refined by D-042: identity decisions anchor on `source_record.id`.


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
  explicit approval. The owner's own pushes of `c75aee0` and `643e1b1` were intentional.

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

Reconciliation runs inside that same transaction, so a lost lock or a blocked commit
leaves no partial import and no partial reconciliation. `database_busy` is reported as a
failure with what to do next, and retrying completes the work (Approved for now, D-034).

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
- A retired ID's `created_at` is kept in `transaction_identity_history`, separate from
  source moves, and a revival restores it exactly. An ID retired before migration 0004
  has no such record, so it takes the timestamp of its first record's link, written in
  the same import. That is a fallback and not an exact creation time: `trace` labels it
  approximate, and no precision is claimed for it.

## D-030 Displayed values of a merged transaction — Approved, implemented in slice 3

A merged transaction shows all its values from one primary source record, chosen
deterministically, with no mixing of fields between records. It may show `posted`
when its primary source is posted. An `unknown` source status stays unchanged in
`record_parse` and `trace`. Pending-to-posted reconciliation remains M2.

The primary source is chosen by, in order: settlement status (posted, then unknown, then
pending), more dates present, having a description, then lowest document hash and row
number. It is stored as `primary_source_record_id`, and `trace` names it and says which
criterion each alternative lost on. A transaction merged before migration 0004 has no
recorded primary until its account is next reconciled, and the backfill does not guess.

## D-031 Candidate grouping — Approved as an initial heuristic, implemented in slice 3

- A candidate link needs the same signed amount, no shared document, no proof of
  distinctness (D-026), a date within the window on any date of either side, and a
  similar description (D-032). A same-date counterpart never suppresses a near-date
  one.
- Linked transactions form connected groups. No pairwise relationships are stored.
- A group spanning up to `max_group_span_days` (14) is one review item.
- A longer run is divided into fixed calendar blocks of that length, each extended by
  the date window. Every linked pair therefore shares at least one item, and a
  transaction can sit in two items.
- Disclosures count distinct affected transactions and never sum item memberships.
- This is a review heuristic. It creates review items and never authorizes a merge.

## D-032 Description similarity — Approved as an initial heuristic, implemented in slice 3

Candidate evidence only. It never enters the automatic merge path, and no claim of
general accuracy is made.

Normalization: NFKC and casefold, join hyphens and apostrophes inside a word, strip
`SQ`-style prefixes only before `*`, strip channel terms only as a leading run, and
split into tokens. Mixed letter-and-digit tokens and a leading number stay as merchant
tokens. Later pure numbers and masked numbers become references, compared rather than
discarded.

Two descriptions are similar when neither is blank and their folded text is identical.
Otherwise both need sufficient merchant evidence (not only generic words), matching
first tokens, and either full containment of the shorter in the longer (at least two
tokens, or one of at least five characters) or a token Dice score of at least 0.75. A
single-token merchant with different references is not similar.

Known misses, which count twice with no flag: `3M COMPANY` / `3M CO`, `24 HOUR FITNESS`
/ `24HR FITNESS`, `NORTHWIND MKT` / `NORTHWIND MARKET`, `SQ *CAFE` / `CAFE`.

Known false positives, which cost one review: `NORTHWIND STORE 12` / `NORTHWIND STORE
98`, `76 GAS 1234` / `76 GAS 9876`, `BLUE BOTTLE COFFEE OAKLAND` / `BLUE BOTTLE COFFEE
BERKELEY`.

## D-033 Rule versions and existing accounts — Approved, implemented in slice 3

- Matching rules are one effective configuration per reconciliation, applied to a
  whole account. They live in code as `MatchingRules`, and a parameter can override
  them. Nothing stores an override as production configuration.
- `account_reconciliation` records a fingerprint of the effective configuration,
  including `RULES_VERSION` and any overridden setting.
- An account is current only when its fingerprint equals the one in use and every live
  transaction records its primary source. So a marker cannot claim currency for a
  different configuration, or for transactions missing required metadata.
- An account with no transactions has nothing to reconcile and is never stale.
- `stale_accounts` is the only definition. `is_current` and the `totals` disclosure both
  use it, so they cannot drift.
- Any import attempt for an account, including a byte-identical repeat, reconciles it
  once if it is not current. After that a repeat is a true no-op.
- `reconcile` covers accounts with no new file, and `totals` discloses accounts that
  are not current.

## D-034 Reconciliation performance — Approved as provisional benchmarks

Whole-account re-derivation after each import stays for now, and so does holding the
write lock through it. Neither locking nor matching was redesigned.

Provisional A39 benchmarks: under 10 seconds for one import, and under 2 minutes for the
24-import sequence. They apply only to the documented ordinary and dense fixtures of
about 100,000 rows on the machine recorded in [status.md](status.md), not to arbitrary
datasets. They are measured by `tests/benchmarks/measure_reconciliation.py` and are
deliberately not test assertions, because wall-clock checks would be flaky.

The quadratic stress cases stay documented as known limitations.

Acceptance of A39 is limited to those fixtures. Nothing merges in them, so the cost of
applying many merges is not yet measured (see "Backlog benchmarks" in [plan.md](plan.md)).

## D-035 Migration is explicit — Approved

- `migrate` upgrades the schema and its required metadata. It never changes transaction
  grouping. `reconcile` updates grouping. The two stay separate.
- Read commands open the ledger read-only and never upgrade it. Every other command also
  refuses an outdated schema. Each explains how to migrate and changes nothing.
- Each migration step is atomic. If one fails it leaves no changes, steps before it stay
  applied, and running `migrate` again resumes.
- A migration that has been committed is not edited, because edits are not detected.

## D-036 Import summary units — Approved

Counts keep their own units. Only the first two below are partitions, and nothing else is
added to them or to each other.

| Count | Definition | Reconciles? |
|---|---|---|
| Files attempted | Files named in the run | Imported + already imported + failed |
| Source rows read | Non-blank data rows in a successfully imported file (see [layouts.md](layouts.md)) | Valid records + unresolved records |
| Valid records accepted | Rows stored with a parsed result | Part of rows read only |
| Final logical transactions | Distinct live transactions those valid records now belong to | No |
| Confidently consolidated records | Valid records whose live transaction also has a source record from another document | No |
| Net change in live logical transactions | Signed change in the account's live transactions, measured inside the file's database transaction | No |
| Source memberships changed | Source records in the account whose transaction changed during reconciliation | No |
| Open review groups | Open possible-duplicate review items in the account | No |
| Distinct affected transactions | Different transactions in those groups | No |

- Records accepted are never described as transactions created. A one-row file can add two
  live transactions by splitting an earlier merge, and a file can add none.
- "New" and "matched" are not reported as outcomes of a record, because reconciliation can
  regroup records later. Consolidation is a state at a stated moment.
- A file's own counts describe the moment it was imported. The run summary reads the ledger
  after the last file, so a later file in the run is reflected.
- Net change and memberships changed are sums over the run's files, each measured under its
  own write lock, so they exclude other processes.
- Account review totals are final-state counts, never sums of per-file snapshots.
- Rows from a failed file are never reported as read or stored. A failed file has either a
  known attempted count, when it was parsed and then rolled back, or no count, shown as
  unavailable. Neither is ever shown as zero, and neither joins the row partition.
- A file already imported reads no rows, so it has no row counts.
- User-facing text says "review groups", never "flags", for group membership. Review
  memberships, one transaction in one group, are not reported.

## D-037 No application logging, and a safe CLI boundary — Approved

- M1 writes no logs. Output goes to the terminal only, and the database is the only file
  written.
- `main` catches unexpected exceptions and prints one fixed message with exit code 2. The
  exception's text is never shown, because it can quote file contents.
- Expected validation, migration and `database_busy` errors keep their sanitized messages.
- User cancellation is not an application error, so it is not caught there. The same goes
  for a reader closing the output, as in `pf transactions | head`: the command stops
  silently with exit code 141.
- No traceback or diagnostic dump is written to disk. The cost is that an unexpected error
  must be reproduced with synthetic data to be diagnosed.
- Scope of the privacy rule: import summaries, `reconcile`, `documents`, `review list` and
  error paths never show descriptions, amounts or raw rows. `transactions`, `trace` and
  `review show` exist to show selected data and are not leaks. `totals` shows only aggregate
  amounts.
- Amended 2026-11-06 for M2.1: `review show` displays amounts, descriptions and original
  cells for the one item explicitly requested, under the same terms as `trace`. Its refusals
  repeat nothing they were given. See D-040.
- File and account names are shown as the user typed them.
- Tests allow the ledger, its SQLite support files and explicitly requested outputs, and
  fail on any other new file.

## D-038 Entry point — Approved

- `bin/pf` is the verified launcher. It runs this checkout's `.venv` from any directory, and
  paths containing spaces are supported.
- `[project.scripts]` also declares `pf`. Installing the package needs setuptools, downloaded
  by pip as a build requirement. A non-editable install was verified on 2026-11-06.
- Checking a clone that shares an existing environment is a source-checkout check. It is
  not a clean install, and must not be called one.

## D-039 Temporary files during development — Approved

- pytest's temporary directories may sit outside the repository, for synthetic test
  artifacts only, with normal cleanup. This authorizes nothing else outside the repository.
- Walkthroughs, clone checks and deliberate breaks use `build/`.
- External memory and scratchpad files are not read or written voluntarily. Files managed
  by the tool harness are distinct from the session's own actions, and any unavoidable
  boundary limitation is reported.

## D-040 Review evidence and revision tokens — Approved

`review show` presents one item. These stay visibly separate, and a missing value is shown
as missing, never as blank or zero:

- Original source cells, exactly as read.
- Parsed source values, per record.
- Current logical transaction values.
- Primary-source selection (D-030), with what each alternative lost on.
- Coverage evidence, keeping the claim apart from what matching relies on (D-027).
- Machine-generated reasons.

Ambiguous groups show no duplicate adjustment (D-006). Records sharing a document are
identified. Descriptions and IDs are escaped, so a cell cannot imitate another section or
send terminal controls. `review list` gives item IDs only.

**Revision token.** Each item shows `r<version>-<16 hex characters>`: the start of a SHA-256
of its material evidence, as canonical JSON. It covers all material evidence shown to the
user, not membership alone, and exists so that a later decision can refuse evidence that
changed after it was viewed.

| Covered now | Not covered, because it does not change what the evidence says |
|---|---|
| Item kind, rule, status, reasons and date range | Item, transaction, record, account and decision IDs, and the account name. Records are identified by document hash and row |
| Each transaction's current values and primary source | File names, which are labels. The document hash is covered |
| Each record's original cells, parsed values and link rule | The stale-account warning. Whatever reconciling changes reaches the token through the evidence |
| Each document's interpretation, coverage claim and effective end | Timestamps, which are not part of the evidence loaded |
| Active decisions with a side in the item, from version 2 (D-043) | |

- Equal evidence gives an equal token in any ledger and any import order. A repeat import
  or a reconcile that changes nothing cannot change it, and A16 compares tokens.
- Inputs that do not exist yet are not stubbed. Effective values from corrections, corrected
  coverage and applicable decisions must join the token when they are introduced.
- Any change to the inputs bumps `REVISION_VERSION`, and a test pins the definition. Tokens are
  compared only with a fresh computation and are never stored as identity, so an old token
  simply reads as changed.
- It detects change and proves nothing else. It is derived from row contents, so it appears
  only in `review show`, never in routine output.

## D-041 Requirements for later M2 slices — Approved as requirements

Recorded with the approval of M2.1. None of this is implemented, and the rest of the M2 plan
in [plan.md](plan.md) is provisional and not approved for implementation.

- Resolved by D-042. Before M2.2, define whether reject means a pairwise distinction or a complete partition.
  Rejecting an ambiguous group must not be treated as permission to declare every member
  distinct.
- Corrections and coverage conflicts must stay distinguishable from possible duplicates in
  classification and disclosures, even if they share review infrastructure.
- Rejecting an unmerged candidate leaves totals unchanged. Separating an existing merge may
  change them.
- Before corrections are introduced, define deterministic behaviour when several active
  overrides affect one merged transaction, including exactly which effective value totals use.
  "Neither chosen silently" is not sufficient on its own.

## D-042 Rejection and the identity constraint model — Approved, implemented and accepted in M2.2

Refines D-009 and resolves the first requirement of D-041.

Rejection is a pair-level assertion: these two transactions are different events. There is no
"reject group" command, and rejecting anything never implies that every member of a group is
distinct. A two-member item still names its pair. A partition is valid only when written out
explicitly, and belongs to confirmation in M2.3.

| Question | Rule |
|---|---|
| What it asserts | Between each stated pair of transactions, the records belong to different events. Nothing else, and not that either transaction is correct or complete |
| What it binds | The cross-product of the source records in the two transactions at decision time. `source_record.id` is the anchor, because a merge deletes a retired transaction row |
| What stays undecided | Any other pair in the group, new records (including an exact re-export of a bound row, under D-009), and whether either transaction holds the right records |

Rejection and confirmation share one model: `different_event` and `same_event` are two relations
on record pairs, with one set of rules for contradiction, supersession and undo. M2.2 writes only
`different_event`. The schema allows `same_event` now, because its meaning is settled here and a
later change would mean rebuilding an append-only table.

How automatic reconciliation respects a constraint:

- `derive()` takes an optional constraints input. With none, its output is identical to today.
  It stays a pure function of evidence, active decisions and rules.
- **Whole-group withholding:** if a reliable-ID or exact group would contain a constrained pair,
  the whole group is withheld. Its records stay separate and counted, because choosing which side
  a third record joins would be a guess. New evidence can therefore raise totals, and this is
  disclosed (D-044).
- Two transactions separated by a constraint are never linked directly as candidates. They can
  share an item through an undecided third record, and `review show` lists the decided pair.
- A new record that resembles decided records raises an ordinary candidate item, not a conflict.
- Rejecting an unmerged pair moves no records and leaves totals unchanged. If it ever would move
  one, the command rolls back. Separating an existing merge is M2.4, and may change totals.

Superseding is not needed in M2.2, because `different_event` constraints cannot contradict each
other. Rejecting an already rejected pair is refused. Defined for M2.3: a new decision must name
the one it replaces and restate any pairs it keeps. Undoing it restores the old one, or refuses if
that would contradict an active decision. Nothing is replaced implicitly.

## D-043 Validating decision commands and undo — Approved, implemented and accepted in M2.2

Applies the owner's qualifications on D-040.

Every decision command runs its checks under one write lock, in this order:

1. The account must be current (D-033). If not, the command refuses and says to run `reconcile`
   and then `review show`. It never reconciles on the user's behalf, so changed evidence can
   never be accepted against an old token.
2. Evidence is recomputed inside the lock.
3. Account, item ID, revision token and item status are checked together. A matching token alone
   never identifies a target.
4. Every pair must be two different transactions in that item.
5. The decision is written, the account re-derived, and everything commits together.

A refusal changes nothing and exits with code 2.

- Revision version 2 adds the active decisions with a side in the item. A decision in one
  overlapping item therefore changes the token of any other item touching those records.
- `review decision show` gives a decision's own revision token, and `review undo` requires it with
  the account, so undo meets the same conditions.
- Undo appends an event and keeps the decision on record, then re-derives in the same transaction.
  Source records and parsed values are never touched, and link history records every move.
- The result of undo equals a ledger built without that decision. It is not necessarily the
  earlier totals, because evidence may have arrived since, and the output must say so.

## D-044 Decision conflicts — Approved, implemented and accepted in M2.2

Decision-related conflicts are a separate classification, not a variety of possible duplicate.

| Situation | Classification | Effect |
|---|---|---|
| Undecided pair | `possible_duplicate` | Unchanged |
| An automatic match is withheld | `decision_conflict`, reason `automatic_match_withheld` | The decision stands, records stay separate, and this item replaces any candidate item covering the same records |
| An automatic split divides a bound transaction | `decision_conflict`, reason `decision_basis_changed` | The decision stands, and the user is told its basis changed |
| Stale token, wrong account or stale account | No item. The command refuses | Nothing changes |

- `decision_conflict` is a `review_issue.kind`. Sharing `possible_duplicate` would make every query
  on that kind count conflicts as candidates, against D-041.
- `totals` and import summaries disclose conflicts on their own line, and they never join the
  possible-duplicate counts.
- Widening the kind needs `review_issue` rebuilt. Moving the `review_issue_subject` rows out and back
  in one transaction worked on a populated ledger. A plain rebuild fails its foreign keys at commit.

## D-045 Owner's qualifications on M2.2 — Approved, implemented and accepted in M2.2

Given by the owner on 2026-11-06 with the confirmation to start M2.2. They override anything in
D-042 to D-044 or the plan that they change. Migration 0005 and the populated `review_issue`
rebuild are confirmed.

**Closing an item (amends S4).** An item closes by removal: when no undecided candidate
relationship remains, derivation stops producing it and the row goes, as for any item no longer
warranted. The decision and its source-record constraints stay in append-only history. Undo may
raise a new item with a new ID. Nothing is marked resolved in a way that suppresses candidates
after undo.

**Pair validation (amends D-043 step 4).** Each pair must be a direct, undecided candidate
relationship, not merely two transactions in one connected group. It is checked under the same
write lock as account, item, revision and status. In a chain A–B–C where A and C are not directly
linked, A–C cannot be rejected. The cross-product of source records is bound at decision time, and
new records are not bound automatically.

**Withholding (confirms D-042).** Later evidence can split an existing automatic merge, raising
the transaction count and account movements. This is tested and disclosed. Rejecting the displayed
unmerged pair must itself leave totals and source memberships unchanged. If it would change them,
the command refuses atomically and explains that separating an existing merge belongs to a later
workflow. All source evidence and identity and link history are preserved. `same_event`, when built,
must preserve explicit confirmed groupings unless superseded. Confirmation is not implemented here.

**Conflict wording (extends D-044).** Each reason has its own wording, and nothing claims a merge
was withheld when only the decision basis changed. A conflict with both reasons explains both.
Distinct affected transactions are counted within each category. A transaction can appear in more
than one category, so the counts are never presented as disjoint.

**Undo token (extends D-043).** It covers active decision state and the current material evidence
relevant to regrouping, not only the decision's own text. If that evidence changes after
`review decision show`, undo refuses and asks for another inspection. Stale accounts are refused
without reconciling. Undo re-derives from current evidence without that decision, and never restores
an old financial snapshot.

**Order independence.** Compared on equivalent active source-record constraints, grouping, totals
and semantic review outcomes, using stable fixture evidence and never generated IDs or timestamps.
This includes equivalent decisions made at different valid points in the import sequence.

**Migration and history.** Populated migration is tested for success and for failure atomicity,
preserving issues, subjects, foreign keys, indexes, source evidence and identity and link history.
Decision, constraint and event history refuse update, delete and replacement.

**Performance.** Dense constrained groups are measured and the cost documented. Approved matching
semantics are not changed silently to meet a target.

**Not approved:** confirmation, superseding, separating existing merges, corrections, later slices,
network access, new dependencies, security changes and pushing.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.2 on 2026-11-07:

- A decision's pairs are stored one row per record pair, sharing a `pair_number`. The two sides of
  a stated pair are what `decision_basis_changed` compares.
- A stated pair already touched by a constraint is refused as decided, even if a newer record in
  one transaction is unbound. Such transactions are never direct candidates (D-042).
- The undo token is `d<version>-<16 hex characters>`. It derives the account with and without the
  decision and covers: state, pairs, rules fingerprint, the two results for every record they differ
  on or the decision binds, those records' parsed values and documents, and other active decisions
  touching them. An unrelated file leaves it unchanged. A rules change alters it.
- A conflict item is one connected set of affected transactions. A per-reason count covers every
  transaction in an item citing that reason, so an item with both reasons counts its transactions
  under both, and the wording says "transactions in conflicts where...".
- `review show` lists undecided direct pairs for candidate items, up to 50, and says when it stops.
- `review decision show` shows document, row, transaction IDs and a preview of transaction counts.
  It prints no amounts or descriptions, which is stricter than D-037 requires.
- Link history names the decision for moves caused by withholding and by undo. Where several
  decisions withheld one group, the lowest ID is recorded.

## D-046 Confirmation, partitions and superseding — Approved, implemented and accepted in M2.3

Approved by the owner on 2026-11-07 with the M2.3 plan. Builds on D-042 to D-045 and changes none
of them. Accepted as built by the owner on 2026-11-07, with the limits in the handoff's "M2.3 as
built".

```sh
pf review confirm --db DB --account A ITEM_ID --revision R --group T1 T2 [--group T3] \
   [--supersedes D --supersedes-revision d2-… --keep N ...]
```

**Partitions.** Each named transaction is in exactly one `--group`. Unnamed transactions stay
undecided. Within a group every pair of transactions is stored as `same_event`, binding the
cross-product of their records. Between two groups the pair is stored as `different_event`, even
when the two are not direct candidates, because the person stated it. Nothing is implied: one
`--group A B` says nothing about C. A decision that states no pair at all is refused.

| Question | Rule |
|---|---|
| Items | `cross_document_candidates` and `decision_conflict` only. Others are refused |
| A group | Connected through direct links (D-045). The transactions of a withheld automatic merge are always linked directly, so a conflict needs nothing more |
| Unique IDs | A group may not join two different IDs of a namespace that guarantees them unique (D-026), even through a chain. Neither may an automatic merge joining confirmed units |
| One document | A group may hold at most one record from any document. D-008 and `transaction_source` stay as they are |
| Size | At most 50 transactions named in one decision |
| Contradiction | A group holding both sides of an active `different_event` pair needs `--supersedes` |
| Totals | Only the stated merges may change memberships. Anything else refuses atomically |
| Only one-transaction groups | Refused on a candidate item, because it only keeps transactions apart, which is `review reject` and limited to direct pairs (D-045). Allowed on a conflict, to settle it |

**Derivation.** Records joined by active `same_event` constraints form fixed units. An automatic merge
touching a confirmed unit joins it only if the result keeps one record per document, joins no two
distinct unique IDs and holds no `different_event` pair. Otherwise every automatic merge in that
combination is withheld, its records stay separate or in their confirmed unit, each confirmed unit
stays a transaction of its own, and `automatic_match_withheld` is raised. A confirmed grouping survives repeat imports, rules changes and new files, and changes only by undo
or superseding. Its records link with rule `confirmed_same_event`. With no `same_event` constraint,
`derive()` is unchanged.

**Conflicts.** There is no separate conflict command. A conflict is settled, and closes by removal,
when one active confirmation's partition separates every pair of the transactions it affects, or
when confirmation has joined them. A rejection never settles a conflict, so D-044 holds exactly as
built in M2.2, where a withheld match whose pairs a rejection already covers still raises one.

**Superseding.** One decision at a time, and in M2.3 only for contradiction by a confirmation.
Superseding because of new evidence stays in M2.5.

- A decision is active unless it was undone, or an active decision supersedes it. Amended by D-048:
  a decision stays superseded while anything superseding it has not been undone.
- The new decision names the old one and its current undo token. Every old pair is either
  contradicted by the new partition or kept with `--keep N`, and anything else is refused. Kept pairs
  are copied record for record, so they bind no new records.
- Undoing the superseding decision restores the old one, or refuses if that would contradict an
  active decision. Undoing a superseded decision is refused, naming the decision that replaced it.
- Superseding is done from an open item holding the transactions. A rejection that closed its item
  leaves nothing to confirm on, so it is undone first, which raises the item again. Found while
  building M2.3.

**Tokens.** Revision version 3 adds each decided pair's relation. Decision revision version 2
computes the outcome without the decision with any superseded decision restored, and covers whether
each other active decision touching the scope is a confirmation. Superseding needs the item's token
and the old decision's token, both checked under the write lock.

Corrected at acceptance, to match what was built and accepted: the plan said version 2 would also
hold the decision's own kind, its relation per pair and what it supersedes. All three are fixed
when the decision is written, so they cannot change between `review decision show` and `undo`, and
their effect reaches the token through the outcomes with and without the decision. They were
removed during M2.3 as immaterial, which the handoff records.

**Disclosure.** `review confirm` prints transaction counts and no amounts. `totals` gains its own line
for transactions holding records confirmed as one event. Undo says that totals may rise.

**Cost.** Confirmation is measured at 100 to 2,000 units before it is accepted. If it is materially
slower than M2.2's rejection, the work stops and is reported. Matching is not changed to meet a
target.

## D-047 Separating machine-made merges — Approved, implemented and accepted in M2.4

Approved by the owner on 2026-11-07 with the M2.4 plan, taking every recommendation in it. Builds on
D-029 and D-042 to D-046, and changes none of them. Accepted as built by the owner on 2026-11-07,
including the implementation choices below, with the limits in the handoff's "M2.4 as built".

```sh
pf review merges --db DB --account A
pf review merge show --db DB TRANSACTION_ID
pf review separate --db DB --account A TRANSACTION_ID --revision t1-… --group R1 R2 --group R3
```

**What it is.** A partition of one transaction's source records, stored as a confirmation (D-042
puts partitions under confirmation) whose target is a transaction rather than a review item. Records
in one group are `same_event`, records in different groups `different_event`, one stated pair per
record pair. Whole-group withholding (D-042) then keeps the automatic merge apart, the `same_event`
pairs keep each group of several records together as a confirmed unit, and the partition settles
the conflict that withholding would otherwise raise (D-046). Undoing a machine merge is therefore a
decision, and the next reconcile cannot merge the records again.

| Question | Rule |
|---|---|
| What can be separated | A transaction holding records joined automatically, by `reliable_external_id` or `exact_coverage_pair`, including those a confirmed unit absorbed |
| A reliable-ID merge | Allowed. The output says the decision overrides an ID the source calls unique (D-026) |
| A confirmed unit | Its confirmed core counts as confirmed and its absorbed records as machine-made. No group boundary may cross an active `same_event` pair, which needs undo |
| Refused | One record, nothing joined automatically, or the transaction in an open `decision_conflict`, which is settled through the conflict |
| Groups | Every record named in exactly one group, at least two groups, at most 50 records. Unnamed records would be separated with no stated relation, an implied "all distinct" (D-042) |
| Connection | Not D-046's direct links: the records were joined by this one automatic merge. Two records sharing a reliable ID can differ in description |
| Unique IDs | D-046's check is not repeated: records of one machine merge share one ID or carry none |
| Public IDs | The group holding the earliest-imported record keeps the ID, and the others revive theirs with their `created_at` (D-029) |
| Totals | May rise. Memberships must become exactly the old ones with this transaction replaced by its groups, and no open conflict may hold its records, or the command refuses atomically |

**Commands.** A confident merge raises no review item, and making every merge one would flood the
queue. `review merges` lists separable transactions with record counts and link rules only.
`review merge show` gives one transaction's evidence in `review show`'s sections and a `t1-…` token.
`review separate` runs D-043's checks under one write lock. It is its own command: its target,
connection rule and the direction its ledger check enforces all differ from `review confirm`, which
it shares the partition writer with.

**Conflicts.** A separation creates and settles none when made. Later evidence that would rejoin its
records, such as a re-export carrying the same ID, raises `automatic_match_withheld`, open because
the new record is undecided. `decision_basis_changed` cannot come from its pairs: each side is one
record.

**Superseding and undo.** A separation never supersedes: a live merge holds no `different_event`
pair, and splitting a confirmed core is refused. It can be superseded by a confirmation under D-046,
from an open item, though its groups raise none between themselves, so in practice it is undone
first. Undo re-derives without it, so the merge returns or is withheld with a conflict under D-046's
joining rules. Superseding a confirmation by a separation stays in M2.5.

**Storage.** Migration 0007 renames `decision.review_issue_id` and `item_revision` to `target_id`
and `target_revision`, adds `target_kind` (`item` or `transaction`), and rebuilds
`decision_constraint` with `left_part` and `right_part`, because its check that the two transaction
IDs differ cannot hold when both sides start in one transaction. Nothing references that table, so
it is rebuilt directly, with its triggers and indexes recreated.

**Tokens.** The transaction token is `t<version>-<16 hex characters>`, version 1: the transaction's
values and primary source, each record's cells, parsed values and link rule, each document's
interpretation, coverage and effective end, and the active decided pairs touching its records. IDs,
file names and history are left out. Item revision version 3 and decision revision version 2 are
unchanged, because a separation reaches them through fields they already cover, and its target is
fixed when written, so immaterial.

**Disclosure.** `review separate` prints transaction counts and no amounts, with a notice that totals
can rise. `totals` gains a line for transactions holding records a separation keeps apart, and says
undoing one can lower totals.

**Cost.** A separation touches its candidate group as a partition does, and adds units to it. It is
measured on a shape where separated records still link with many others: two documents with
complete coverage that pair every row, and a third with unknown coverage holding the same rows. If
it is materially slower than a partition on that shape, the work stops and is reported.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.4 on 2026-11-07:

- One stated pair per record pair, with the lower group on the left, so stored rows never depend on
  which record ID sorts first. Pair numbers still follow record IDs, so `--keep` numbers are read
  from `review decision show`.
- `review merges` lists only transactions with something joined automatically: records forming
  more than one confirmed core, a record no `same_event` pair binds counting as its own.
- The override notice names the stored guarantee. No production layout declares plain `stable`,
  so one message covers both rather than a second wording that could never be printed.
- The `totals` line counts transactions holding a record of an active separation's
  `different_event` pairs, so a kept group of several records is counted there and as confirmed.
  The lines are never presented as disjoint (D-045).
- Refusing a transaction in an open conflict, and the check after re-deriving that no open conflict
  holds its records, are tested by inserting a conflict directly. A transaction can be in a conflict
  when a confirmed unit has absorbed one automatic merge while a rejection withholds another merge
  holding one of its records, which takes four documents and two layouts to build.
- The tests of migrations 0005 and 0006 now migrate only to their own version, and map the renamed
  columns when they copy rows from a current ledger. They assert nothing new.
- The item token was checked unchanged by the shared loading code: a fixed ledger gives
  `r3-d41e2251fcd3a611` both at `3a765fe` and after, and a test pins it.

## D-048 New evidence on decided records, and superseding chains — Approved, implemented and accepted in M2.5

Approved by the owner on 2026-11-07 with the M2.5 plan, taking every recommendation in it. Builds on
D-042 to D-047. It amends one rule of D-046, the state of a superseded decision, because that rule
contradicted D-046's own requirement that a confirmation contradict no active decision but the one
it names (F4). Accepted as built by the owner on 2026-11-08, including the implementation choices
below, with the limits in the handoff's "M2.5 as built".

```sh
pf review separate --db DB --account A TRANSACTION_ID --revision t1-… --group R1 --group R2 \
   [--supersedes D --supersedes-revision d3-… --keep N ...]
```

**Supersession chains (amends D-046).** A decision is superseded while any decision superseding it
has not been undone, whether that one is active or superseded in turn. Only the newest decision of a
chain is active, and only it can be undone. Each undo steps back one link: it restores the decision
just before, or refuses if that would contradict an active decision. Refusing a superseded decision
names the newest of its chain. D-046 said "an active decision supersedes it", so in a chain A ← B ← C
the rejection A applied again once C superseded B, while C kept the very pair A keeps apart, and no
conflict was raised. Migration 0008 clears the reconciliation marker of every account holding a
chain of two or more, so that commands refuse it until `reconcile` re-derives it (D-035).

**New evidence touching a decided record.** No decision transfers to a record that did not exist when
it was made (D-042, D-009).

| Situation | Outcome |
|---|---|
| A re-export that merges automatically with a bound record | Its unit is kept apart as the bound record is, and nothing is reviewed again. The decision still binds only the old record |
| A re-export that does not merge (S11) | An ordinary candidate item. A person decides it with `review confirm` on that item |
| A re-export carrying an ID shared by separated records (P7) | A withheld-match conflict, settled by a partition |
| A record that would join a confirmed unit (C8) | Joins when valid, otherwise withheld with a conflict |
| An automatic split under a decision (S12) | `decision_basis_changed`, settled by a partition |

`review show` lists records in the item that are alike a decided record in every parsed value, with
the decision that binds the other, and binds nothing. It reads only evidence the item token already
covers, so the token is unchanged.

**What can supersede what.** A confirmation supersedes a decision whose `different_event` pairs it
joins (D-046). A separation supersedes a confirmation, a separation included, whose `same_event`
pairs its groups split: every other pair of the old decision is kept with `--keep`, copied record for
record. A rejection never supersedes: it adds `different_event` pairs between direct candidates, which
cannot join or split anything. One decision is superseded at a time. Superseding several would need a
link table in place of `supersedes_decision_id` and an undo that restores several at once, while undoing
one and superseding the other already works.

**Tokens.** Item `r3` and transaction `t1` are unchanged. The undo token becomes `d3`: its fields are the
same, but "without this decision" now restores only the decision just before it, so a `d2` token from a
chain ledger must never read as current.

**Conflicts.** A separation that supersedes settles conflicts as any partition does, and refuses
atomically if an open conflict would still hold its records. Undoing it may raise a withheld or
changed-basis conflict under D-046's joining rules. Nothing new raises one.

**Cost.** A superseding separation touches its group as a partition does. It is measured on three
unmerged documents, where the confirmed unit still links with the third. If it is materially slower
than a partition there, the work stops and is reported.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.5 on 2026-11-08:

- A decision is superseded exactly when a decision not undone names it, since only an active decision
  can be superseded. `review decision show` names the immediate successor and, in a chain, the newest.
  Refusing a decision whose successor is itself superseded has its own wording, naming both.
- Migration 0008 deletes the marker of any account where a decision supersedes one that supersedes
  another, whether or not its ledger differs. A `derive()` check showed one can: with the revived
  rejection, an automatic merge into the confirmed unit was withheld with a conflict.
- A superseding separation skips the check that something was joined automatically, so a confirmed
  core alone can be split. Splitting another decision's core is refused, naming it. The old decision's
  `different_event` pairs cannot be split, so they are always kept.
- A transaction-target decision copies kept pairs as they were stored, including their group numbers,
  which describe the old decision's transaction.
- The alike listing compares parsed transaction date, posting date, amount, description, external ID
  and status, across documents only, so two alike rows of one file are never offered as a re-export
  (D-008). It is lazy and `review show` prints at most 50.
- The `d3` digest is unchanged for a ledger without chains: `d2-2a1e1dd2ac99de82` became
  `d3-2a1e1dd2ac99de82`, and a test pins it.

## D-049 Value corrections — Approved, implemented and accepted in M2.6

Approved by the owner on 2026-11-08 with the M2.6 plan, taking every recommendation in it. Meets
D-041's requirements on corrections, and extends D-030. Builds on D-009 and D-040, and changes none
of D-042 to D-048. Accepted as built by the owner on 2026-11-08, including the implementation choices
below, with the limits in the handoff's "M2.6 as built".

```sh
pf review transaction show --db DB TRANSACTION_ID
pf review correct --db DB --account A TRANSACTION_ID --revision t2-… --field amount --value=-12.50 \
   [--supersedes C --supersedes-revision c1-…]
pf review corrections --db DB [--account A]
pf review correction show --db DB CORRECTION_ID
pf review correction undo --db DB --account A CORRECTION_ID --revision c1-…
```

**What can be corrected.** `amount`, `transaction_date`, `posting_date` and `description`, each set to
a concrete value. Nothing can be cleared. Settlement status is M2.9's, and changes the pending count.
An external ID is identity evidence (D-026). One correction holds one field.

**Storage.** Migration 0009 adds append-only `value_correction`, `value_correction_record`, the
records it binds, and `value_correction_event`, plus a derived `transaction_correction` that every
reconcile and correction rewrites. `ledger_transaction` keeps D-030's primary-source values exactly,
so corrections never enter base columns.

**Matching never reads them.** `derive()` reads `record_parse` only, and its signature is unchanged.
A corrected value that could merge or split records would be an identity decision bypassing D-042 to
D-048's checks, membership would depend on corrections anchored on membership, and stored
interpretation (D-026) and fingerprints as evidence only (D-009) would no longer hold.

**Effective value.** For a transaction and a field, take every active correction of that field
binding any record now in the transaction:

| Corrections | State | Value that totals and display use |
|---|---|---|
| None | | The primary source's (D-030) |
| All give the same value | `applied` | That value |
| Values differ | `conflict` | The primary source's |
| One binds records now in another transaction | `basis_changed` | The primary source's |

"Neither chosen silently" is not enough on its own because totals must add some number. This one is
deterministic and independent of order, never chooses between two statements a person made, applies
nothing twice, and is disclosed on its own line with no adjustment figure. Undo settles it.

**Anchoring.** A correction binds every record of its transaction when made. The transaction ID is a
snapshot.

| Event | Outcome |
|---|---|
| A re-export merges automatically | Still applied. The new record is not bound |
| `review confirm` would join disagreeing corrections, or `review separate` would split a correction's records | Refuses atomically. D-047's "raises no conflict" holds |
| An automatic split, or an undo that splits or joins | `basis_changed` or `conflict`, disclosed |

A correction made after a merge binds more records, so a later split gives `basis_changed` where an
earlier one would not. This is how a decision binds records at decision time too.

**Superseding and undo.** Correcting a corrected field needs `--supersedes` naming the one correction
applying there, with its `c1` token. A field in `conflict` or `basis_changed`, or with several
corrections applying, refuses superseding: undo one first, one at a time as in D-048. Chains follow
D-048: only the newest applies, undo steps back one link, and refusing a superseded correction names
the newest of its chain. Corrections constrain no identity, so undo never refuses for contradiction,
and says when it leaves a field unsettled. A correction and a decision never supersede each other.

**Distinguishable (D-041).** Corrections never raise or close a `review_issue`, so no count of possible
duplicates or decision conflicts can include them. `totals` and import summaries disclose corrected
and unsettled transactions on their own lines. `review show` gives them a separate section,
`transactions` marks corrected values, and `trace` shows source and corrected values.

**Commands.** D-043's checks under one write lock: the account must be current, and account,
transaction and token are checked together. A correction changes no membership, so the command
rewrites `transaction_correction` without deriving. Routine output, `review correct`,
`review corrections` and `review correction show` print no amounts or descriptions.

**Tokens (D-040).** A ledger without corrections keeps its digests, because the new fields are left out
while empty.

| Token | New inputs | Version |
|---|---|---|
| Item | Each transaction's active corrections: field, value, state and bound records by file and row | `r3` to `r4` |
| Transaction | The same, for one transaction | `t1` to `t2` |
| Decision undo | Corrections binding records in its scope, and their states with and without it | `d3` to `d4` |
| Correction undo, new | Its field, value, the transactions holding its bound records, and the field's outcome there with and without it | `c1` |

**Cost.** Applying corrections is linear in bound records and transactions. A correction adds no
constraint, so it touches no candidate group. It is measured on the dense constrained group, where
derivation is quadratic, and on many corrections and long chains. If a correction costs more than a
later import of the same account, the work stops and is reported.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.6 on 2026-11-08:

- Fields are stored by their command names: `amount`, `transaction_date`, `posting_date` and
  `description`. An amount is integer cents in its own column, and the others are text, with checks
  that each value fits its field.
- `transaction_correction` is rewritten whole for the account by every reconcile and correction, after
  memberships are final, and loses a retired transaction's rows by `ON DELETE CASCADE`.
- Several corrections applying to one field refuse superseding even when they agree, since replacing
  one would leave the other: undo all but one first.
- `review confirm` and `review separate` compare the account's unsettled fields before and after,
  keyed by the records of each transaction, and refuse if any is new. Decision undo reports the new
  ones and never refuses for them.
- `review correction show` prints no values, which is stricter than D-037 requires, like
  `review decision show`. `review transaction show` and `review merge show` share one display.
  `transactions` now escapes descriptions, since a corrected one is typed by a person.
- The chain rule moved to `reconcile/supersession.py`, now shared by decisions and corrections.
- `c1` was first built also covering its state, the bound records' evidence and other corrections of
  the field. Deliberate breaks showed only the pin noticed any of them: only an active correction has
  a token, the records and documents are immutable, and another correction reaching those
  transactions changes the outcomes. Both were removed before
  review, keeping version 1, since no `c1` token had been shown outside this slice.
- `c1-e2235f95e29f164e` is pinned for a fixed ledger as computed when built. The digests
  `r4-d41e2251fcd3a611`, `r4-74d05de08ff20c6b`, `r4-8f8c8b328e5b7256`, `t2-4ae2352458f9c44c` and
  `d4-2a1e1dd2ac99de82` are the version 3, 1 and 3 digests pinned before M2.6, unchanged.
- Equivalent corrections made at different points can bind different records, so the order test
  compares everything but revisions, and checks that records arriving later are never bound.

## D-050 Resolving incomplete records — Approved, implemented and accepted in M2.7

Approved by the owner on 2026-11-08 with the M2.7 plan, taking every recommendation in it. Meets
PRD §5's unresolved-import queue, D-024 and D-041's requirement that corrections stay distinguishable.
Builds on D-009, D-029, D-030 and D-040, and changes none of D-042 to D-049.

```sh
pf review complete --db DB --account A ITEM_ID --revision r5-… \
   [--amount=-12.50] [--transaction-date D] [--posting-date D] [--description TEXT]
pf review dismiss --db DB --account A ITEM_ID --revision r5-…
pf review resolutions --db DB [--account A]
pf review resolution show --db DB RESOLUTION_ID
pf review resolution undo --db DB --account A RESOLUTION_ID --revision u1-…
```

**What is resolved.** One open `unresolved_record` item, which is one source record. A record has at
most one active resolution. There is no superseding: undo, then resolve again.

**Completing.** A completion supplies only what the parser could not read: an amount when none was
parsed, a date when that date is missing, a description when there is none. It never replaces a
parsed value, which is what a correction does afterwards (D-049), and it must leave the record with
an amount and at least one date. A row whose values were all read, such as `invalid_status`, is
completed with nothing supplied. Settlement status and external IDs are never supplied: the parse's
status stands (M2.9), and an ID is identity evidence (D-026). Values are written as for corrections.

**Dismissing.** A statement that the row adds no transaction: a blank line, a heading or summary row,
or an event already counted elsewhere. It creates no transaction and stops counting as unresolved.

**Storage.** Migration 0010 adds append-only `record_resolution` and `record_resolution_event`.
`source_record` and `record_parse` are untouched, and the parse stays `unresolved`. The item is closed
by removal (D-045), and an undo raises a new one with the parse's reason code. A completed record's
transaction holds its effective values in `ledger_transaction`, because it has no others, and it is
marked as completed wherever it is shown.

**Matching.** A completed record enters `derive()` as a record with its effective values, marked as
completed by hand. Its values were typed by a person, so they never authorize a merge:

| Path | A completed record |
|---|---|
| Reliable-ID matching and exact pairing (D-006) | Takes no part. It is always a transaction of its own unless a person confirms it |
| Exact pairing in its own document (D-024) | Blocks a confident pair under D-024's test, using its completed values, with reason `completed_row` |
| Candidate discovery | Takes part, so a possible duplicate is raised for review |
| A reliable ID shared with another record | Raises an external-ID item with reason `completed_record_shares_id`, never a merge |
| `review confirm` and `review reject` | Allowed as for any transaction |
| Primary source (D-030) | A record read from the source is preferred over one completed by hand, as a new first criterion |

A dismissed record is neither a record nor a blocker, since the person says it is not a transaction.
So a dismissal can make an exact pair confident and lower totals. It never makes one by typed values.

**Undo.** Re-derives from current evidence, never a snapshot (D-043). Undoing a completion is refused
while any decision or correction binding the record is not undone: undo those first. Otherwise its
transaction is retired, and completing the record again revives the same transaction ID (D-029).
Undoing a dismissal restores the blocker, so what it unblocked can split.

**Commands.** D-043's checks under one write lock: the account must be current, and account, item and
token are checked together. Completion, dismissal and undo each derive the account once, and report
transaction counts before and after. Routine output, `review complete`, `review dismiss`,
`review resolutions` and `review resolution show` print no amounts or descriptions, and refusals
never repeat a value. `review show`, `review transaction show`, `trace` and `transactions` show
completed values marked as completed, apart from parsed values.

**Distinguishable (D-041).** `totals` and import summaries disclose transactions completed by hand and
rows dismissed on their own lines, apart from possible duplicates, conflicts and corrections.

**Tokens (D-040).** A ledger without resolutions keeps its digests, because the new fields are left out
while empty.

| Token | New inputs | Version |
|---|---|---|
| Item | Each record's completed values | `r4` to `r5` |
| Transaction | The same, for one transaction | `t2` to `t3` |
| Decision undo | Whether each record in scope is completed by hand | `d4` to `d5` |
| Correction undo | None: a completion binding a corrected record cannot be undone | `c1`, unchanged |
| Resolution undo, new | Its kind, values and record, the evidence of records in scope, and derivation with and without it | `u1` |

**Cost.** One derivation per command, as for a decision. Measured where a dismissal unblocks a whole
document's exact pairs, so that it pays for many merges, against a later import of the same account.
If a resolution costs materially more than that import, the work stops and is reported.

As measured, that comparison was the wrong one, and this is reported for the owner. The later import
merges nothing, so at 5,000 unblocked pairs a resolution took 1.1 to 4.6s against 0.3 to 0.4s. An
import making the same 5,000 merges took 6.7s, so a resolution costs what the merges it unblocks cost,
and nothing more. The work was not stopped. See [status.md](status.md).

**Not in scope.** Same-document checks (D-021) run only at import, so a completed record is never
flagged against rows of its own document. Clearing a parsed value, supplying a status or an ID,
superseding a resolution, and resolving several records at once.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.7 on 2026-11-08, including continuing past the stop rule under Cost:

- Completed values are merged into the record inside `load_evidence`, so `derive()` sees one record
  marked `completed_by_hand`, and builds that record's blocker itself. Its signature is unchanged.
- A record entering the ledger by completion gets its `source_record_origin` the first time it is
  derived, and a record leaving it by undo has its link removed without a link history row, since
  neither is a move between transactions. The identity history says `record_completed` and
  `record_completion_undone`.
- The first criterion for the primary source is `read from the source, then completed by hand`, so
  every later criterion's number moved by one in `trace`.
- `review complete` takes `--amount`, `--transaction-date`, `--posting-date` and `--description`, and
  a value that was read is refused naming the field. Value parsing is shared with corrections.
- `u1` was first built also covering the resolution's kind, values and record, the rules, derivation
  with the resolution, and the transactions holding records in scope. Deliberate breaks showed only
  the pin noticed each. They cannot change while a token can be checked, reach it through derivation,
  or follow from the items. It now covers the review items derivation gives without the resolution,
  for the records whose items differ. No `u1` token was shown outside this slice, so it keeps
  version 1. `u1-eef46741adfc3a9f` is pinned for a fixed ledger.
- `r5-d41e2251fcd3a611`, `r5-74d05de08ff20c6b`, `r5-8f8c8b328e5b7256`, `t3-4ae2352458f9c44c` and
  `d5-2a1e1dd2ac99de82` are the digests pinned before M2.7, unchanged.
- `trace` now escapes descriptions, since a completed one is typed by a person.

## D-051 Coverage correction with history — Approved, implemented and accepted in M2.8

Approved by the owner on 2026-11-08, who asked for M2.8 to be built with the lead engineer's
recommendations, recorded here before its code, and reviewed with M2.7 and M2.9. Replaces D-022's
coverage limitation, keeps D-005, D-007 and D-027, and changes none of D-042 to D-050.

```sh
pf documents --db DB                       # now names each document's ID
pf review coverage show --db DB DOCUMENT_ID
pf review coverage declare --db DB --account A DOCUMENT_ID --revision v1-… \
   --coverage-kind complete --coverage-start D --coverage-end D --coverage-basis posting
pf review coverage declare --db DB --account A DOCUMENT_ID --revision v1-… --coverage-kind unknown
pf review coverage history --db DB [--account A]
pf review coverage undo --db DB --account A DECLARATION_ID --revision k1-…
```

**What is declared.** One document's coverage for one account, after import. `complete` with an
inclusive interval and a date basis, as a declaration at import (D-005), or `unknown`, withdrawing a
claim. `partial` is not offered: for matching it says what `unknown` says.

**What a person may declare.**

| Coverage at import | Allowed |
|---|---|
| `unknown`, or `complete` declared by a person | `complete` or `unknown` |
| Stated by the document's metadata | `unknown` only. A person never claims more than the document states |

The basis must be one the stored interpretation offers (D-026), and a declaration must change the
effective coverage.

**Storage.** Migration 0011 adds append-only `coverage_declaration` and `coverage_declaration_event`.
`document_coverage` stays the claim made at import, unchanged. Each declaration supersedes the one in
effect for that document, if any, and chains follow D-048: only the newest applies, undo steps back
one link, and a superseded declaration is refused naming the newest of its chain. The effective
coverage is the newest active declaration, else the claim at import.

**Matching** reads the effective coverage through `load_evidence`, so `derive()` is unchanged. A
declared `complete` has evidence `user_declared`, so D-027's restriction does not apply and D-007's
rules do. Declaring and undoing re-derive the account, so they can merge or split, raise or lower
totals, and change decision conflicts and correction states, which they report. They never refuse
for that, as an import does not.

**Repeat imports.** A declaration given with a repeat import is compared with the effective coverage:
equal is `already_imported`, different is `coverage_conflict`, whose explanation now names
`review coverage declare`.

**Commands.** D-043's checks under one write lock: the account must be current, and account, document
and token are checked together. Coverage is not a financial value, so the commands print intervals,
and no amounts or descriptions.

**Distinguishable (D-041).** `documents` and `review show` show declared coverage apart from the claim
at import, and `totals` discloses documents whose coverage was declared after import on its own line.

**Tokens (D-040).** A ledger without declarations keeps its digests.

| Token | New inputs | Version |
|---|---|---|
| Item | Each document's declared coverage, and the effective end and pending rule from it | `r5` to `r6` |
| Transaction | The same, for one transaction's documents | `t3` to `t4` |
| Decision, correction and resolution undo | None: they read documents as matching does, now with effective coverage | `d5`, `c1`, `u1`, unchanged |
| Document coverage, new | The document's effective coverage | `v1` |
| Declaration undo, new | The review items derivation gives without it, for records whose items differ | `k1` |

**Cost.** One derivation per command. Measured where declaring complete coverage unblocks a whole
document's exact pairs, against an import making the same merges.

**Not in scope.** `partial` declarations, coverage for several documents at once, changing coverage
a document's metadata states other than withdrawing it, and coverage of documents of other accounts.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.8 on 2026-11-08:

- The declaration in effect is found with the shared chain rule (D-048), and `load_evidence` puts its
  kind, interval, basis and evidence in the document it gives `derive()`.
- `documents` now starts each line with `Document <ID>:`, and shows the coverage in effect, adding
  `declared after import, claimed at import: <kind>` when it differs from the claim.
- `review coverage show` gives `v1` to declare with, and while a declaration applies, its `k1` to undo
  it with, as `review show` gives `r6` and `review decision show` gives `d5`.
- `v1` covers the effective coverage only. The claim, the interpretation and the document never
  change. `v1-bb1b708a2ff2dd50` and `k1-141e501092a4533f` are pinned for fixed ledgers.
- `k1` and `u1` are computed by one helper, `reports/undo_items.py`. `u1-eef46741adfc3a9f` is
  unchanged by that.
- `r6-` and `t4-` read the digests pinned before M2.8.
- A declaration of a basis the stored interpretation does not offer is refused before the metadata
  rule, so a metadata document asked for an impossible basis hears about the basis.

## D-052 Pending to posted — Approved, implemented and accepted in M2.9

Approved by the owner on 2026-11-08, who asked for M2.9 to be built with the lead engineer's
recommendations, recorded here before its code, and reviewed with M2.7 and M2.8. Amends D-006 for
pending and posted rows sharing a reliable ID, carries out D-008's migration, and meets D-016.
Changes none of D-042 to D-051.

**Matching, rules version 2.** Each change is a change of behaviour the settings do not show, so
`RULES_VERSION` becomes 2 and every account reads as not current until `reconcile` (D-033).

| Evidence | Before | Now |
|---|---|---|
| Same reliable ID, one row pending and the other not, transaction dates agreeing where both are present | Possible duplicate, a status conflict | Confident duplicate, merged. The amount may differ, as with a tip, and the posted row supplies the values (D-030). A changed amount is disclosed |
| No reliable ID, one row pending and the other posted, in different documents, dates within the window, similar descriptions, the same direction, different amounts | Not a candidate | Candidate, with reason `pending_amount_changed`. Review only: `review confirm` joins them |
| A pending and a posted row of one document, flagged under D-021 | Cannot be acted on | `review confirm` can join them, the only way one transaction holds two records of one document |

A reliable ID under `stable_unique` already proves the rows are one event (D-026), so only status
and amount stood in the way. Without an ID, amount was the evidence that ruled pairs out, so a tip
gave a pending 20.00 and a posted 24.00 counted as 44.00 with no flag. It now raises a candidate and
never merges by itself.

**The D-008 migration.** Migration 0012 rebuilds `transaction_source`, replacing
`UNIQUE (transaction_id, source_document_id)` with a partial unique index exempting links with rule
`confirmed_same_event`. A confirmed unit may then hold two records of one document only when one is
pending and the other is not. Automatic matching still never does, and every other confirmation
rule of D-046 stands. A test shows the migration on populated data, as D-008 requires.

**Same-document items.** `review confirm` accepts a `same_document_pending_posted` item, with one
group holding a pending and a posted transaction of its document. Such an item stays open while its
records are in several transactions and is resolved while they are in one, so undoing the
confirmation reopens it.

**Stale pending (D-016).** A pending transaction dated more than 10 days before the latest date in
its account's records is disclosed in `totals` on its own line, and is never removed or changed.

**Disclosure (D-041).** `totals` and import summaries disclose transactions whose posted amount
differs from their pending amount, and stale pending transactions, on their own lines.

**Tokens (D-040).** No token's inputs change. The decision undo token covers the rules fingerprint,
so `d5` digests change with the rules version, keeping `d5`.

**Cost.** Pending rows are compared with posted rows in the date window only. Measured with many
pending and posted rows of one description block, against a later import.

As first built, every pending unit was compared with every posted unit in its window, whatever the
description: 2,000 pairs on one day took 35s to derive, and every later import paid it again. Since
descriptions can only be similar within a block (D-032), a pending unit is now compared only with
posted units sharing its description or its block. Distinct merchants are then linear. Many alike
descriptions in one block stay quadratic, as candidate discovery already is in distinct spellings per
block. See [status.md](status.md).

**Not in scope.** Pending and posted rows of one document without a D-021 flag, a pending row with
no posted counterpart ever arriving, automatic joining of same-document rows, and changed amounts
under unreliable IDs.

**How these were implemented,** where the rules above left a choice. The owner accepted all of them
with M2.9 on 2026-11-08, including the amendment of A34:

- For a reliable ID, a pending and a non-pending row are compatible when they agree in direction and
  in the transaction date where both have one. Two rows of the same status still need equal amounts.
- A unit is pending when all its rows are, and posted when any is, so a pending and a posted row
  already merged under one ID count as posted.
- One function decides the pending-to-posted link for discovery and for the direct-link check, so
  `review confirm` accepts exactly what discovery raised. Discovery looks it up by day and by
  description or block, and the direct-link check applies the same conditions.
- A same-document item is confirmed as exactly one group of two transactions, each one row, one
  pending and one not. Anything else, including a posted row already merged with another document,
  is refused with one message.
- `repoint_other_issues` resolves a same-document pending item while its records share a transaction,
  and reopens it when they do not.
- Stale pending uses 10 days, against the latest transaction or posting date of the account's
  transactions.
- A34, an accepted M1 criterion, said a status conflict was flagged. Its test and wording now say that
  holds for dates, and that D-052 made a pending and a posted row with one ID one event.
- The `d5` pin moved from `d5-2a1e1dd2ac99de82` to `d5-ecb0f4cc0ef102ac` only because it covers the
  rules fingerprint, checked by computing it under rules version 1. Every other pin is unchanged.

## D-053 Financial types — Approved, implemented and accepted in M3.1

Proposed for M3.1 on 2026-11-08, and approved by the owner the same day with no changes. Meets PRD §7 and §9's requirement that
income, spending, transfers, debt principal and investment contributions stay distinct, and D-014,
which puts financial type before categories. Builds on D-049, and changes none of D-042 to D-052.

```sh
pf review classify --db DB --account A TRANSACTION_ID --revision t5-… --type purchase \
   [--supersedes CLASSIFICATION_ID --supersedes-revision f1-…]
pf review classifications --db DB [--account A]
pf review classification show --db DB CLASSIFICATION_ID
pf review classification undo --db DB --account A CLASSIFICATION_ID --revision f1-…
```

**Recommendations, for the owner to approve or change:**

1. **Types.** `purchase`, `refund`, `income`, `fee`, `interest`, `transfer`, `card_payment`,
   `loan_payment` and `investment_contribution`, and `unclassified`, which every transaction is until
   a person says otherwise. Each type allows one direction except `transfer`, which allows either:
   a refund and income are money in, the others money out. A type against its direction is refused.
2. **Only a person classifies in M3.1.** No layout states a type, and a description alone never
   establishes one (D-011, D-032). Suggested types from rules belong to Phase 1B (D-014).
3. **A classification is a correction of a field with no source value.** It binds the records of its
   transaction when made, applies after derivation, is never read by matching, and follows D-049's
   rules: agreeing classifications apply, disagreeing ones or one whose records split leave the
   transaction `unclassified` and disclosed, chains follow D-048, and undo never refuses.
   `review confirm` and `review separate` refuse to leave one unsettled, as for corrections.
4. **Stored apart.** Migration 0013 adds append-only `type_classification`,
   `type_classification_record` and `type_classification_event`, and a derived
   `transaction_classification`. The correction tables are not widened, because changing their
   checks would mean rebuilding tables that others reference. The effective-value and chain code of
   D-049 is shared rather than copied.
5. **Totals.** `totals` keeps account movement exactly as now (D-010), and adds one line per type
   with its count and amount, and a line for unclassified transactions. Income, spending and
   transfers as reports wait for M3.4, once transfers can be confirmed across accounts.
6. **Tokens.** `r6` to `r7` and `t4` to `t5` add each transaction's classifications, left out while
   empty so digests are kept. `d5` and `c1` gain them like corrections, versions bumped. `f1` is the
   new classification undo token.
7. **Privacy.** A type is not an amount or a description, so routine output may show it. The new
   totals lines show aggregates only.

**Acceptance tests,** F1 to F14, are in [plan.md](plan.md).

**Open for M3.2, not decided here.** Transfers pair transactions of two accounts, and every rule so
far reconciles one account at a time, including what makes an account current (D-033) and the order
tests (A16). M3.2 needs its own decision on reconciling two accounts together.

**How these were implemented,** where the rules above left a choice, for the owner's review with
M3.1:

- Unclassified is never stored. A transaction is unclassified while no classification applies to it.
- Direction is that of the effective amount, a corrected amount where one applies (D-049), and a zero
  amount runs neither way, so it fits every type.
- A correction can change an amount's sign, so the derived row has a fourth state beside D-049's
  three, `against_direction`: a single agreeing type whose transaction now runs the other way leaves
  it unclassified and disclosed, like a disagreement. `review correct` refuses to cause it, as
  `review confirm` and `review separate` refuse to leave a classification unsettled. Undoing a
  correction never refuses (D-049), and says when it causes it.
- Classifications share `effective_field_corrections` as corrections of the field `financial_type`,
  whose value is the type. The walk to the newest of a chain, copied for decisions, corrections and
  declarations, moved to `supersession.successor_and_newest` and is shared by all four.
- A classified transaction can be superseded only while one classification applies there, as for
  corrections. Otherwise undo first.
- `totals` adds a "By financial type" section: each type that some transaction has, in the order of
  recommendation 1, with its count and net effective amount, and always an unclassified line. Types no
  transaction has are not listed. The unsettled counts are disclosed on their own lines, in `totals`
  and after an import.
- Tokens. `r7` and `t5` add each transaction's active classifications with their outcome there, left
  out while there are none. `d6` adds the outcome of every group holding a classified record in
  scope under both derivations, using each group's effective amount, left out while there are none.
  `c2` adds, for an amount correction only, the classifications of its transactions with and without
  it, because only an amount can turn a direction, so no other correction's token changes. `f1`
  covers the records of the transactions holding the bound records, and the outcome there with and
  without it. The outcomes give the classifications' types and bindings, so deliberate breaks showed
  those inputs noticed only by the pin, and they were removed before review. Ledgers without
  classifications keep every digest pinned before M3.1.
- Undoing a completion also waits for classifications binding its record, for D-050's reason: a
  binding record outside the ledger has no transaction.
- Decision undo, correction undo, resolutions and coverage declarations report the transactions they
  newly leave unclassified, as they report unsettled corrections.

**For the owner's review, found while building M3.1:**

- **Direction on the receiving account.** Recommendation 1 gives each type but `transfer` one
  direction, whatever the account. On a credit card, loan or investment account, the payment received
  is money in, which `card_payment`, `loan_payment` and `investment_contribution` refuse, so that side
  can only be stated as a `transfer` or left unclassified. It fails safe: it refuses, never miscounts,
  and allowing more later invalidates nothing stored. Recommended for M3.2 or M3.3: let the account
  type decide the direction of those three.
- `interest` is money out only, so interest earned on savings can only be `income`.
- The acceptance tests F1 to F14 share letters with follow-ups F1 to F4 in the handoff.

**Accepted** by the owner on 2026-11-08 as built, with no changes, including the implementation
choices and the three points above. The owner asked for M3.2 to follow the lead engineer's
recommendations, so direction on the receiving account is taken up there. Interest stays money out
only. Later acceptance tests use letters no follow-up uses.

## D-054 Transfers across accounts — Approved, implemented and accepted in M3.2

Proposed for M3.2 on 2026-11-08. The owner asked for M3.2 to be built on the lead engineer's
recommendations without a separate plan review, so these are approved in advance and open to change
when M3.2 is reviewed. Meets PRD §9's cross-institution transfers, different posting dates, manual
confirmation and reversal of incorrect matches, and D-011's rule that suspected transfers stay visibly
unresolved. Builds on D-053, and changes none of D-042 to D-053 except recommendation 7, which D-053
proposed for M3.2.

```sh
pf review transfers --db DB [--account A]
pf review transfer match --db DB --account A TRANSACTION_ID --revision t6-… \
   --counterpart COUNTERPART_ID --counterpart-account B --counterpart-revision t6-…
pf review transfer show --db DB MATCH_ID
pf review transfer undo --db DB --account A MATCH_ID --revision m1-…
```

**Recommendations:**

1. **Two accounts together, without joint derivation.** Each account still reconciles alone: derive(),
   what makes an account current (D-033) and the order tests are unchanged. A match is stated by a
   person over two transactions already derived, and its outcome is computed afterwards from both
   accounts' current state, so any order of imports and reconciles gives the same outcome. Matching
   and undoing need both accounts current, check both tokens, and run under one write lock.
2. **Candidates need a person's type.** Equal amounts are not proof (PRD §9, D-006), so a pair is a
   candidate only when one side's applied type is `transfer`, `card_payment`, `loan_payment` or
   `investment_contribution`, and: the other side is in another account, its effective amount is
   exactly the opposite and not zero, some effective date of each side is within 5 days of the other,
   neither side holds a record bound by an active match, and every applied type on either side fits
   the pair. A type fits when it is one of those four, and a type other than `transfer` needs one of
   the two accounts to be what it pays: a credit card, a loan, or an investment or retirement account.
   Candidates are computed when listed and never stored. They change no total and authorize nothing.
3. **Only a candidate can be matched.** A match binds the records of both transactions when made, as
   a classification does, and names its outflow and inflow sides. It is not superseded: undo it and
   match again. Undo never refuses for contradiction.
4. **Outcome.** A match applies while each side's bound records sit in one transaction, no transaction
   holds records of two active matches, the amounts still offset exactly, and every applied type
   fits the pair. Otherwise its state, checked in this order, is `basis_changed`, `conflict`,
   `amounts_differ` or `type_differs`, and it is disclosed. Migration 0014 adds append-only
   `transfer_match`, `transfer_match_side`, `transfer_match_record` and `transfer_match_event`, and
   a derived `transfer_match_effect`, rewritten for the whole ledger wherever classifications are.
5. **Commands that would unsettle a match refuse.** `review confirm`, `review separate`,
   `review correct` and `review classify` refuse to leave an applied match unsettled, as they refuse
   for classifications. Undos, resolutions and coverage declarations never refuse for it, and report
   the matches they newly leave unsettled. Undoing a completion waits for a match binding its record.
6. **Totals.** Account movement and "By financial type" are unchanged. A new section gives matched
   pairs and the amount they move, transactions in a candidate pair, transactions of a transfer type
   with neither a match nor a candidate, and unsettled matches by state. Income and spending wait for
   M3.4, and one-sided transfers and coverage warnings for M3.3.
7. **Direction on the receiving account,** recommended in D-053. `card_payment` on a credit card,
   `loan_payment` on a loan and `investment_contribution` on an investment or retirement account
   also allow money in. Allowing more invalidates nothing stored. A transaction left unclassified as
   against its direction may now fit, so migration 0014 marks as not current only the accounts of
   those kinds holding one, and `reconcile` settles them.
8. **Tokens.** `r7` to `r8` and `t5` to `t6` add each transaction's active matches, with their state
   and both sides' bound records, left out while there are none, so digests are kept. `m1` is the
   match undo token: the transaction tokens of every transaction holding its bound records. `d6`, `c2` and `f1` are unchanged: a match changes nothing a decision regroups, a
   correction corrects or a classification states, the commands that would unsettle one refuse, and
   the undos report it.
9. **Privacy.** `review transfers` shows IDs, accounts, types and states, never amounts or
   descriptions. `review transfer show` is the explicit inspection of one match. Totals show
   aggregates only.

**Not in M3.2:** one-sided transfers, card payments without card history and coverage warnings
(M3.3), fees apart from transferred principal, a transfer split over several transactions, and income
and spending reports (M3.4).

**Acceptance tests,** X1 to X14, are in [plan.md](plan.md).

**How these were implemented,** where the rules above left a choice, for the owner's review with
M3.2:

- A candidate reads each transaction's effective amount and dates, corrected where a correction
  applies (D-049), and its applied type. A transaction with no date is never a candidate. The outflow
  side is the one with money out, whichever is named first.
- `transfer_match_effect` has one row per active match, naming its two transactions only while it
  applies. Two unique indexes make "no transaction is a side of two applied matches" a schema rule,
  and triggers keep a match to two accounts and each side to its own account's records.
- `review transfer match` checks, in order: two different accounts, both current, each transaction
  found, in its account and at its token, then the candidate rules, each refused with its own
  message.
- `t6` adds, for each active match binding a transaction's records, its side, the outcome and both
  sides' bound records. The other side's transaction ID is immaterial, as IDs are. `r8` follows
  because items show transactions. `m1` covers the `t6` of every transaction holding a bound record,
  so a change to either side changes it. The outcome is in those tokens, so a deliberate break
  showed it covered twice, and it was removed.
- `review transfer undo` takes `--account` naming either of the match's accounts. Undoing a match
  only ever settles others, so it reports nothing more.
- For one account, `totals` counts the matches with a side there, the account's own transactions
  in a candidate pair, and the amount on the inflow side.
- Migration 0014 clears the marker of a card, loan, investment or retirement account holding any
  transaction against its direction, not only one of the three types, because the stored row no
  longer says which type it was.

**For the owner's review, found while building M3.2:**

- **A candidate needs a person's type first.** Without one, equal amounts on nearby dates raise
  nothing, so an unclassified transfer is invisible here. Raising candidates from amounts and dates
  alone would be easier to use and noisier, against D-006.
- **Matching does not classify the other side.** It stays unclassified in "By financial type" unless
  classified. M3.4 needs to decide whether a matched side counts as a transfer either way.
- The 5-day window is a constant, not part of `MatchingRules`, because candidates are never stored
  and so need no fingerprint (D-033).
- An import summary does not report matches the import leaves unsettled. `totals` does.

**Accepted** by the owner on 2026-11-08 as built, with no changes, including the plan itself,
the implementation choices and the four points above.

## D-055 Card payments, one-sided transfers and coverage warnings — Approved, implemented and accepted in M3.3

Proposed for M3.3 on 2026-11-08, and approved by the owner the same day with the lead engineer's
recommendations, including the four points for the owner's decision, with no changes.
Meets PRD §9's one-sided imported transfers and its warning for card payments without purchase
history, D-012, and D-011's rule that a suspected transfer stays visibly unresolved. Builds on
D-054, and extends its recommendations 3 and 4 only as recommendation 4 below says.

```sh
pf review transfer one-sided --db DB --account A TRANSACTION_ID --revision t7-… \
   --counterpart-account B
pf review transfers --db DB [--account A]       # now also lists one-sided transfers
pf review transfer show --db DB ID              # a match or a one-sided transfer
pf review transfer undo --db DB --account A ID --revision m1-…|o1-…
```

**Recommendations:**

1. **A one-sided transfer is a person's statement** that one transaction moves money between it and
   another owned account whose side is not in the ledger. It names that counterpart account, which
   must be registered with `pf account add` and may have no documents at all. The transaction needs
   a transfer-kind type applied, fitting its own and the counterpart account under D-054's rule, so a
   `card_payment` from checking names a credit card. It binds the transaction's records when made,
   is never superseded, and undo never refuses for contradiction.
2. **Refused while the other side may be in view.** Stating one refuses, each with its own message:
   the same account, an unknown or stale account on either side, a stale token, no transfer-kind
   type or one that does not fit, a transaction holding records of an active match or one-sided
   transfer, a candidate pairing it with a transaction of the counterpart account, and complete
   coverage of the counterpart spanning the window (recommendation 6). Both accounts must be
   current, under one write lock, as for a match.
3. **Outcome.** A one-sided transfer applies while its records sit in one transaction held by no
   other active statement, its type still fits, no candidate pairs it with the counterpart account,
   and the counterpart's coverage does not span the window. Otherwise its state, checked in this
   order, is `basis_changed`, `conflict`, `type_differs`, `counterpart_found` or
   `counterpart_covered`, disclosed, and settled only by undo. Migration 0015 adds append-only
   `one_sided_transfer`, `one_sided_transfer_record` and `one_sided_transfer_event`, and a derived
   `one_sided_transfer_effect`, rewritten wherever `transfer_match_effect` is. No account is made
   stale.
4. **Matches and one-sided transfers together** (extends D-054 recommendations 3 and 4). A
   transaction holding a one-sided transfer's records can still be in a candidate pair, so the other
   side's arrival shows. `review transfer match` refuses while either side holds an active one-sided
   transfer's records: undo it, then match. A match and a one-sided transfer reaching one transaction
   are both `conflict`, as two matches are.
5. **Commands that would unsettle one refuse,** as for a match (D-054 recommendation 5):
   `review confirm`, `review separate`, `review correct` and `review classify`. Undos, resolutions,
   coverage declarations and imports never refuse for it. Undos and declarations report the
   one-sided transfers they newly leave unsettled, and an import summary does not, as for matches.
6. **Counterpart coverage.** The window is every date within 5 days of any effective date of the
   transaction, D-054's window. Coverage spans it when every day of the window lies inside the
   counterpart's effective complete coverage, the same declared or metadata coverage its
   reconciliation reads (D-027, D-051), on either date basis. Only then is a missing counterpart a
   contradiction. Anything less is a warning, never a state.
7. **Coverage warnings and card payments (D-012).** `totals` gains, in its transfers section, the
   applied one-sided transfers with their count and amount out and in, split by whether the
   counterpart has no documents or has documents that do not span the window, and their unsettled
   states. A one-sided `card_payment` gets its own warning line: purchases on that card are not in
   the ledger for those dates, so spending is understated. Account movement and "By financial type"
   are unchanged. Unpaired transfer-kind transactions no longer count those in a one-sided transfer.
   For one account, `totals` counts the one-sided transfers held there or naming it.
8. **Card payments stay out of spending** whether matched or one-sided, as transfers between owned
   accounts (D-011, D-012). M3.3 computes no spending, so this is recorded here for M3.4 to read,
   and M3.3 only reports the warning.
9. **Tokens.** `r8` to `r9` and `t6` to `t7` add each transaction's active one-sided transfers, with
   their state, counterpart account and bound records, left out while there are none, so digests are
   kept. `o1` is the undo token: the `t7` of every transaction holding its bound records, as `m1`
   is. `m1`, `d6`, `c2` and `f1` are unchanged, for D-054's reasons.
10. **Privacy,** as D-054: lists show IDs, accounts, types and states, `review transfer show` is the
    explicit inspection of one, and totals show aggregates only.

**Not in M3.3,** each failing safe meanwhile, because an unmatched transfer-kind outflow stays
unpaired and disclosed and keeps reducing capacity (D-011): a fee netted into one side of a
transfer, a transfer split over several transactions, coverage warnings by reporting period, which
need M3.4's periods, and import summaries reporting unsettled matches. The handoff and status said
fees and split transfers would wait for M3.3, but plan.md's M3.3 never named them. This
recommends planning them when a real layout or M3.4 shows the need.

**Acceptance tests,** O1 to O14, are in [plan.md](plan.md).

**Decided with the plan, found while planning it:**

- **The counterpart must be a registered account,** even one never imported. Naming none would be
  simpler, but then no warning could say which card's spending is understated, and a later import
  of that account could not show the other side.
- **Only a candidate with the named counterpart refuses a statement.** A candidate in a third
  account does not, because equal amounts there may be coincidence (D-006). It still shows in
  `review transfers`.
- **Coverage is a state only when it spans the whole window,** which is conservative: a counterpart
  covered for part of the window gives a warning, and the one-sided transfer applies.
- Recommendation 4 changes the outcome of a match only where a one-sided transfer reaches its
  transaction, which cannot happen on a ledger made before M3.3.

**How these were implemented,** where the rules above left a choice, for the owner's review with
M3.3:

- A one-sided transfer needs a transfer kind applied on its own transaction. A match fits while a
  side is unclassified, but a one-sided transfer has no other evidence that it is a transfer, so
  one left unclassified, as after its classification's undo, is `type_differs`.
- The window is every day within 5 days of any effective date, corrected where a correction
  applies. A transaction with no date has no window, so coverage never spans it.
- Coverage spans the window when one date basis's spans of complete coverage in effect, joined
  across documents, hold every day of it. A span ends at its effective end (D-027), and a
  declaration replaces the claim at import (D-051). A layout's pending definition is not read,
  because a transfer posts in the end. The declared-coverage helpers moved from `apply` to a new
  `coverage_in_effect` module, because `apply` imports the transfer outcomes.
- `counterpart_found` uses D-054's candidate rule unchanged, against the counterpart account's
  transactions of the exactly opposite amount.
- `t7` names the counterpart by its display name, which is unique, because account IDs are random
  and immaterial: another counterpart is another statement, and changes the token. `o1` covers
  the `t7` of every transaction holding a bound record, as `m1` does.
- `review transfer show` and `undo` take either kind of ID, and an unknown one gives one message
  naming both. `unsettled_matches` became `unsettled_transfers`, so every command that refused or
  reported unsettled matches covers both kinds, on one line naming both.
- Undoing a match now reports the one-sided transfers it leaves unsettled, because freeing a side
  can bring a counterpart into view. This replaces D-054's choice that undoing a match reports
  nothing more. Undoing a one-sided transfer reports the same, and in practice only settles.
- Separating a one-sided transfer's transaction is refused by its classification first, because
  the type sits on the same transaction and a split leaves every part unclassified (D-053).
- For totals, "documents that do not cover" means the counterpart has any document, whatever its
  coverage. The card payment warning counts only one-sided `card_payment`s whose counterpart is a
  credit card, so a payment received on the card itself does not warn.

**For the owner's review, found while building M3.3:**

- **Every write rewrites every one-sided outcome,** and each searches its counterpart for
  opposite amounts, so a write anywhere costs one-sided transfers times equal opposite amounts in
  their counterparts: about 3.5 seconds for 1,000 against 1,000 (see benchmarks). Filtering the
  search by date in SQL would make the usual case linear. Not done, as nothing needs it yet.
- Matches without one-sided transfers rewrite about 40% slower at 4,000, from the shared
  bookkeeping, and stay linear.
- An import summary still reports no unsettled matches or one-sided transfers. `totals` does.

**Accepted** by the owner on 2026-11-08 as built, with no changes, including the implementation
choices and the three points above.

## D-056 Income and spending — Approved, implemented and accepted in M3.4

Proposed for M3.4 on 2026-11-08, and approved by the owner the same day with the lead engineer's
recommendations, including points A to C, with no changes. Meets PRD §9's required treatment (owned-account transfers are
neither income nor spending, card payments do not duplicate purchases, investment contributions are
separate from everyday spending, loan interest is an expense, full loan payments stay visible,
refunds reduce spending) and M3's milestone test, using D-011, D-012, D-053, D-054 and D-055. Changes
none of them, except D-055's note on reporting periods, as recommendation 6 says.

```sh
pf totals --db DB [--account A]       # gains "Income and spending"
```

**Recommendations:**

1. **Five groups, each transaction in exactly one,** read in this order:
   - **Confirmed transfers:** a side of an applied match, or the transaction of an applied one-sided
     transfer, whatever its own type. This answers D-054's open point: a matched side left
     unclassified counts as a transfer.
   - **Income:** applied type `income`.
   - **Spending:** applied `purchase`, `fee` and `interest`, less applied `refund`.
   - **Unconfirmed transfer kinds:** an applied transfer-kind type with no applied match or one-sided
     transfer, including those in a candidate pair and those whose match or one-sided transfer no
     longer applies.
   - **Unclassified:** no applied type, including those left unclassified by a disagreement, a
     changed basis or a direction (D-053).

   Their signed sums add exactly to net account movement, for the ledger and for one account. An
   applied match or one-sided transfer on a transaction whose applied type is not a transfer kind
   breaks D-054's fit rule, so it stops the report with an internal error rather than being counted.
2. **Confirmed transfers by type:** card payments, loan payments, investment contributions, other
   transfers, and matched sides left unclassified, each with its count and its amounts out and in,
   so loan payments and investment contributions stay visible apart from spending.
3. **Unconfirmed transfer kinds stand apart** (D-011): neither income, spending nor transfers, with
   their amounts out and in. A disclosure says spending may be understated by up to their outflows
   and the unclassified outflows, and income by up to their inflows and the unclassified inflows.
4. **Card payments** (D-012, D-055 recommendation 8): a confirmed card payment is out of spending,
   and purchases on a card account count as spending there, so a payment never duplicates them.
   D-055's warning for a card without purchase history stays.
5. **Loan payments without loan history:** an applied one-sided `loan_payment` to a loan account
   warns that the interest inside it is not in spending, as D-012 warns for cards. Splitting a
   payment into principal and interest is a fee netted into one side, which stays unplanned.
6. **No reporting periods in M3.4.** Totals cover the ledger or one account, as now. Periods belong
   to M4 with D-013's reporting date and the monthly reports, and coverage warnings by period go
   with them. This corrects D-055 and the handoff, which said periods wait for M3.4, against
   plan.md and D-013, which put them in M4.
7. **Nothing else in `totals` changes.** Account movement keeps D-010's wording and disclosure, and
   "By financial type" and the transfer sections stay as they are.
8. **Read-only and stored nowhere.** Computed when `totals` runs from `transaction_classification`,
   `transfer_match_effect` and `one_sided_transfer_effect`. No migration, no token change, no
   account made stale. Pending transactions count as now, under the existing disclosure.
9. **Privacy:** aggregates only, as D-054.

**Not in M3.4,** each failing safe as an unconfirmed transfer kind or unclassified: reporting
periods (M4), safe-to-spend, where D-011's capacity rule applies (Phase 1B), categories (Phase 1B),
fees netted into one side and transfers split over several transactions.

**Acceptance tests,** T1 to T12, are in [plan.md](plan.md).

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Unconfirmed transfer kinds** stand apart with the bound in recommendation 3. Alternatively
  their outflows count as spending, which is conservative for guidance but calls a stated transfer
  spending. Recommended apart, because D-011's conservatism is for safe-to-spend, which comes later.
- **B. Periods move to M4,** as recommendation 6. Alternatively M3.4 adds `--from` and `--to` and
  D-013's date now, which builds before M4 needs it.
- **C. M3 closes after M3.4** with fees separate from principal and split transfers recorded as
  open PRD §9 requirements, to plan when a real layout shows one (M6). Alternatively an M3.5 plans
  them now, on invented layouts only.

**How these were implemented,** where the rules above left a choice, for the owner's review with
M3.4:

- One query reads each transaction's effective amount, its applied type, and whether an effect row
  names it. Effect rows name their transactions only while they apply, so being named confirms a
  transfer. Each effect column is looked up by its own unique index.
- `totals` computes the groups before printing anything, so recommendation 1's internal error
  leaves no partial report.
- Income and spending print one net amount each, spending as money out less money in, so it can be
  negative. The other groups print their amounts out and in. Spending types and confirmed types
  print in the order of D-053's types, as "By financial type" does, with matched sides left
  unclassified last.
- The disclosure appears whenever an unconfirmed transfer kind or an unclassified transaction
  exists, even when both bounds are 0.00.
- The loan payment warning sits with D-055's card payment warning, and counts only an applied
  one-sided `loan_payment` whose counterpart is a loan. One received on the loan does not warn, and
  neither does a plain `transfer` to a loan.
- For one account, the groups hold that account's transactions only, so a match across two
  accounts puts one side in each account's confirmed transfers.
- Pending transactions count in their groups, as in account movement, under its disclosure.
- M1's test that `totals` never says "income" or "spending" now binds only the account movement
  lines, which D-010 governs. It was renamed, and A25 in `m1-acceptance.md` names the new test.

**For the owner's review, found while building M3.4:**

- **Writes fail above 32,766 transactions bound by transfers.** `write_transfer_effects` passes one
  SQL variable per transaction holding bound records, so at 16,000 matches and 16,000 one-sided
  transfers every write fails with "too many SQL variables", reported as a database error. It is
  M3.2 and M3.3 code, so it was not changed here. Recommended: read the facts in batches, before
  M4's 100,000-transaction benchmark.
- **`7a07bf4` fails one test on its own.** It renamed the test A25 names without gating on the doc
  checks, so `test_acceptance_matrix` fails there. `4c976d2` fixed it, and history is not
  rewritten.

**Accepted** by the owner on 2026-11-08 as built, with no changes, including the implementation
choices and the two points above. M3 closes with it (point C). The variable limit stays a known
limitation, for the next plan to take up.

## D-057 M4 plan: balances and reports — Approved, implemented and accepted in M4

Proposed on 2026-11-08, and approved by the owner the same day with the lead engineer's
recommendations, including points A to E, with M4.1 approved to build. Each later slice needs its
own approval, as in M3.
Delivers plan.md's M4 (balance observations, statement reconciliation, monthly reports with
disclosures, the 100,000-transaction benchmark) against PRD §17, §20 and §21 ("reports disclose
incomplete data and material review issues"), using D-013, D-034 and D-056. Changes none of D-042
to D-056. Acceptance tests, L1 to Z6, are in [plan.md](plan.md).

```sh
pf balance record --db DB --account A --date YYYY-MM-DD (--balance AMOUNT | --owed AMOUNT)
pf balance list   --db DB [--account A]
pf balance check  --db DB --account A
pf balance undo   --db DB --account A --observation ID --token TOKEN
pf report monthly --db DB [--account A] [--from YYYY-MM] [--to YYYY-MM]
```

**Slices:**

| Slice | Scope |
|---|---|
| M4.1 | The 32,766-variable limit, with no change in behaviour |
| M4.2 | Balance observations and statement reconciliation |
| M4.3 | Monthly reports with disclosures (D-013) |
| M4.4 | The 100,000-transaction benchmark and provisional resource targets |

**Recommendations:**

1. **M4.1 comes first.** The four unbounded `IN` lists (`transaction_facts`, `_separated` and both
   queries in `reports/import_summary.py`) pass their IDs as one JSON array parameter, read with
   SQLite's built-in `json_each`. One helper serves all four, since the pattern already repeats.
   The fixed-size lists over `MANAGED_RULES` and `TRANSFER_TYPES` stay. The 100,000-transaction
   benchmark would otherwise fail on any shape with more than 32,766 matched sides.
2. **An observation is a posted balance at the end of one day,** stated by a person. Stored in the
   ledger's sign convention (D-003): a credit card or loan takes `--owed`, stored negated, and
   refuses `--balance`; every other account type takes `--balance` and refuses `--owed`. Output
   shows `owed` for those two types. Only one active observation per account and date: a second is
   refused until the first is undone. Undo needs the account and its token, `b1`, as other undos.
3. **Observations are not transaction evidence.** Migration 0016 adds `balance_observation` and an
   append-only `balance_observation_event`. No account becomes stale, `derive()` never reads them,
   and every existing token keeps its digest. Recording or undoing needs no current account.
4. **Statement reconciliation** (`balance check`) compares each pair of consecutive observations:
   the later balance against the earlier plus the effective amounts of the account's transactions
   posted in between (after the earlier day, through the later one). Each interval says `agrees` or
   `differs by` the exact amount, and separately whether it is **covered**: complete coverage on the
   posting basis spans every day of it (`complete_coverage_by_basis`). Disclosed per interval, with
   counts and amounts: open review items with a transaction there, pending transactions (left out),
   `unknown` status (counted), and posted transactions with no posting date (counted by transaction
   date). Types, transfers and classifications do not enter it.
5. **Agreement is evidence, not coverage** (as D-024): it never declares coverage, settles a review
   item or changes any total. A difference is shown, never absorbed into an adjustment.
6. **Monthly reports** use D-013: a transaction's month is its effective transaction date, else its
   effective posting date, and the report counts how many used each. One line per month, for the
   ledger or one account: net account movement and D-056's five groups, adding to it as in T1.
   Transactions with neither date go on a `no date` line, so the months and that line add to
   `totals` exactly. `totals` itself is unchanged.
7. **Month disclosures,** per month: accounts whose complete coverage on the transaction basis spans
   the whole month, and those it does not; open review items with a transaction dated in the month;
   and transactions with an unsettled correction, classification, match or one-sided transfer. A
   matched transfer whose sides fall in different months counts in each side's month, so a month's
   ledger movement can be non-zero from it, disclosed by count.
8. **The benchmark** (M4.4) builds 100,000 transactions directly, as `--income` does, over 60 months
   and at least four accounts, with at least 20,000 matches so more than 32,766 matched sides reach
   M4.1's queries, plus one-sided transfers, classifications, coverage intervals and monthly balance
   observations. It measures `totals`, `report monthly`, `balance check`, one classification (which
   rewrites every match outcome) and one import, and prints the counts it reached, so a shape that
   misses a cost shows it. Targets are provisional, as D-034: below two seconds for each report
   (PRD §20) on the documented machine, never test assertions. A target missed is reported with the
   cost behind it, and a redesign is its own decision.
9. **Privacy:** observations hold amounts and dates only, with no free text, and are shown escaped.

**Not in M4,** each left visible rather than guessed: net worth (point B), statement balances read
from documents (point A), available balances including pending, a projected current balance,
storage reporting by kind (backups arrive in M5), and F3's merge-heavy benchmark, which stays in
the backlog.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Manual observations only.** No invented layout carries a balance, and PRD §5's extraction is
  planned when a real layout shows one (M6, M7). Alternatively M4.2 adds balance metadata lines to
  an invented layout now, which builds before a real layout needs it.
- **B. Net worth waits.** Accounts have no parent or subaccount relation, so PRD §17's rule against
  counting an aggregate loan twice cannot be enforced yet. Alternatively an M4.5 sums the latest
  observations with a mixed-date warning, and the double-counting rule is left to the person.
- **C. `json_each` for M4.1.** One parameter, no new dependency, already in SQLite 3.45.3.
  Alternatively chunk the lists at 32,766, which keeps plain `IN` lists but repeats each query.
- **D. Month coverage on the transaction basis only,** because D-013 dates months by transaction
  date and posting-basis coverage misses a transaction dated late in a month and posted the next.
  Alternatively either basis counts, as D-055, with the edge disclosed.
- **E. Posted balances only.** Alternatively observations also state an available balance with
  pending included, which no current layout shows.

**How M4.1 was implemented,** where recommendation 1 left a choice. Accepted by the owner as built
on 2026-11-08:

- `db/id_lists.py` holds `ids_as_json_array`. It refuses an ID that is not a string, because
  `json_each` would read a number as an integer that matches no TEXT ID, silently.
- The query plans are unchanged: `transaction_facts` still looks each ID up by primary key, and the
  import summary queries still scan `transaction_source`, as before.
- L3's write uses 32,767 one-sided transfers rather than matches. Inserting a match side runs
  `transfer_match_side_two_accounts`, whose lookup SQLite plans by `account_id`, so building many
  matches directly is quadratic in an account's sides (about 37 seconds for 16,384 matches). Each
  person's match pays one such scan. That is recorded in [status.md](status.md), and M4.4's shape
  pays it once, at build time.

**How M4.2 was implemented,** where recommendations 2 to 5 left a choice. Accepted by the owner as built
on 2026-11-08:

- Every transaction, pending ones too, is placed on its effective posting date, else its effective
  transaction date (D-049). That date decides the interval for activity and for every disclosure,
  including open review items. An interval runs after the earlier observation's day through the
  later one's, and coverage is checked over those days.
- `unknown` status and no posting date are disclosed within the activity, so one transaction can
  be in both lines.
- `balance list` shows each active observation's token, since D-057 names no `balance show`. The
  token `b1` covers the observation's day and balance and those of the active observations either
  side of it, whose intervals undoing it joins. It names no generated ID and reads no transaction,
  so undo needs no current account.
- A trigger also enforces one active observation per account and day. An amount owed whose
  negation leaves the INTEGER range is refused as an invalid amount.
- For a card or loan, `differs by` is in owed terms: observed owed less expected owed.
- Beyond recommendation 4's list, `balance check` also discloses the account's unresolved records,
  which are no transaction, so no interval counts them.
- The "every day inside a span" test moved to `spans_cover_every_day` in
  `reconcile/coverage_in_effect.py`, shared with D-055's coverage window, its second use.

**How M4.3 was implemented,** where recommendations 6 and 7 left a choice. Approved to build by
the owner on 2026-11-08, built the same day, and accepted as built:

- `pf report monthly` is read-only, needs no migration and changes no token. `totals` is unchanged.
  D-056's five groups are tallied by `IncomeAndSpendingTally` in `reports/totals.py`, which
  `income_and_spending` and the monthly report share, its second use.
- **No `no date` line.** Migration 0001 refuses a transaction with neither date, and no correction
  clears one, so that line would always be empty. A transaction without either date stops the
  report with an internal error instead, as T10 does. G1's "or `no date`" holds trivially.
- Without a range, the months run from the first month holding a transaction to the last, empty
  months between included, so a gap shows. With `--from` or `--to`, every month of the range is
  shown, a missing end defaulting to the data's, and transactions in months outside it are
  disclosed by count and amount, so the report still adds to `totals`.
- Pending transactions count, as in `totals`, and each month says how many.
- Coverage lists every registered account for the ledger, including one with no documents, as
  covered or not covered for each month.
- An unsettled match or one-sided transfer names no transaction, so it is disclosed in the month of
  the current transactions holding the records it binds. Each disclosure counts transactions.
- A matched side counts as crossing months when its other side, in any account, is dated in
  another month. Only the sides in the report's scope are counted, in the months shown.
- Unresolved records and accounts not reconciled under the current rules are disclosed once, for
  the whole report.

**How M4.4 was implemented,** where recommendation 8 left a choice. Approved to build by the owner
on 2026-11-08, built the same day, and accepted as built. Figures are in
[benchmarks.md](benchmarks.md):

- `measure_reconciliation.py --scale` imports one file per account and month, each declaring
  complete coverage of its month, then writes types, matches, one-sided transfers and observations
  directly, as `--income` does. The four accounts are checking, savings, a card and a loan, with an
  investment account, holding no documents, as the one-sided counterpart.
- The 20,000 matches run on four routes, so no account holds more than 10,000 sides. Inserting a
  side scans its account's sides (M4.1), and spreading them keeps the build to about 170s.
- Coverage is on the transaction basis for checking and savings and the posting basis for the card
  and loan, so both `report monthly` and `balance check` meet covered and not-covered cases.
- Reports are timed through the CLI with output discarded. The classification and the import are
  timed through their functions, and the rewrite of every match outcome inside each is timed apart.
- Rows are named by external IDs, and the classified transaction by one, never by generated IDs.
- Z3 ran on a copy of the source in `build/` with M4.1's source change reversed. No commit holds
  that code.
- Every target met, so nothing is redesigned. Writes have no target.

**Accepted** by the owner on 2026-11-08: M4.4 as built, including the choices above. M4 is
complete.

## D-058 M5 plan: the real-data gate — Approved, implemented and accepted in M5

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

   **Amended by the owner on 2026-11-09, approving M5.4.** The owner keeps the backup's encrypted
   disk image file in `~/CommonCents_LocalBackups`, on the same internal disk as the ledger's image.
   "Not on the ledger's own volume" means a different mounted volume: the backup's folder sits
   inside a mounted disk image other than the ledger's, passing points 2 and 3. Two images whose
   files share a disk are not detected. Such a backup survives a damaged ledger or image, a bad
   import or migration, and deletion, but not the loss of the disk or the Mac.
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
lead engineer's recommendations on 2026-11-09, built the same day on synthetic data, and accepted
as built. No migration: `import_attempt.failure_code` takes any code.

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

**How M5.4 was implemented,** under points 7 and 8, point 7 as amended. The owner approved M5.4,
with the lead engineer's recommendations for the choices points 7 and 8 left open, on 2026-11-09,
and it was built the same day on synthetic data, and accepted as built. Migration 0018 adds
`backup_record`.

- **`--to` names the new backup folder,** which must not exist. It is created `0700`, holding
  `ledger.db`, `originals/<sha256>` and `manifest.json`, each `0400`. For a real ledger, the folder
  holding it passes points 2 and 3 as a ledger's folder would, and its mount point must differ from
  the ledger's. A missing or altered original refuses the backup, naming `archive verify`. Only
  referenced originals are copied.
- **The copy is one step of SQLite's online backup API,** so it is one committed state, read under
  one lock while writers wait. The manifest describes the copy, not the live ledger, and the
  originals copied are the ones the copy references, rehashed as they are read.
- **The logical digest** covers `user_version`, every `sqlite_master` row, and every table's column
  names and rows, ordered by primary key, or by every column for `review_issue_subject`, which has
  none. Values carry their storage class, so `1`, `1.0`, `'1'` and `x'31'` differ.
- **The new backup is checked as `backup verify` would check it** before its `backup_record` row is
  written. Any failure, a busy ledger at that write included, removes the folder. A backup holds
  the rows of earlier backups, not its own. `storage` reports the recorded sizes and never reads a
  backup's volume.
- **`backup verify` refuses,** in this order: a manifest not of this shape, a missing or unlisted
  file, a file that is not regular or does not match its size and hash, SQLite's integrity check,
  its foreign key check, a schema version that differs from the manifest or is newer than the code,
  the digest, the real-ledger mark, and originals that differ from the documents the ledger
  references. It opens the copy read-only and immutable, writes nothing, and exits 1 when the
  backup is not intact.
- **`backup restore`** checks the backup, gates a real backup's new path as `init --real` does, and
  refuses a folder that already has `originals/`. It writes the originals and a `.partial` ledger,
  checks those written copies again, then links the ledger into place, so an existing path is never
  replaced. Any failure removes everything it wrote. An older schema restores unchanged and names
  `pf migrate`.
- **A synthetic ledger** is backed up and restored with no gates and no originals.
- **The code version** is `personal_finance.__version__`, now the one place it is written, read by
  `pyproject.toml`. It is recorded, not checked.
- **Not detected:** two disk images whose files share a disk (point 7 as amended), and a manifest
  rewritten together with the files it describes. The manifest is not signed.

**How M5.5 was implemented,** under points 9 and 10. The owner approved M5.5 on 2026-11-09 to be
built unattended, choosing the lead engineer's most fail-closed recommendation wherever a choice
was left open, and it was built the same day on synthetic data, and accepted as built. The owner ran [real-data-readiness.md](real-data-readiness.md) on 2026-11-09 on `/Volumes/CommonCents` and `/Volumes/CommonCentsBackup`, and reported every step verified.

- **W1 parses every module, never imports it,** and refuses more than point 9's list: `_socket`,
  `_ssl`, `asyncio`, `socketserver`, `xmlrpc`, `poplib`, `imaplib`, `nntplib`, `telnetlib`,
  `webbrowser`, `multiprocessing`, `concurrent`, `pty` and `ctypes`, every `os` call that runs a
  program, and every dynamic import (`__import__`, `importlib.import_module`), whatever it names.
  Module aliases are resolved. The allowance is `subprocess` in `db/volume_probes.py` alone, and
  the test also requires that module to make one `subprocess.run` call and name only `diskutil` and
  `hdiutil`.
- **The checklist ends where M6 begins.** No real layout exists, so the owner's ledger is created,
  backed up and restored empty, and the statements are moved into the image for M6 to import.
  Deleting the copies outside the image is recommended, and left to the owner.
- **The walkthrough ran in-process,** with the probes answered by the suite's recordings and the
  work tree above `build/` ignored, as the tests do. Mounting an image writes outside the
  repository, so none was mounted, and the macOS steps (`hdiutil create` and `attach`, `diskutil
  enableOwnership`) were not run. Each is followed in the checklist by a `pf` step that checks it.
- **Point F's tripwire** is not built, as recommended. The security proposal stays unapplied
  (point E): the checklist asks the owner.

## D-059 M6 plan: first real CSV layouts — Approved with points A to F, implemented in M6

Directed by the owner on 2026-11-09, to be built unattended overnight with each slice gated on the
full suite and committed locally: the sequence Capital One (card and bank), U.S. Bank, American
Express, then BFSFCU; `--account` stays required (D-015); fees as their own transactions linked to
a parent or batch reference, and split transfers as individual transfers sharing a transfer group;
identity by hashing account, date, amount, raw description and position in the file, so identical
rows in one file stay distinct; fixtures keeping each format's structure and inventing every value.
Points A to F are where a direction meets an earlier rule. Each says what was built and why, for
the owner's review. Acceptance tests, J1 to J8 for every layout, are in [plan.md](plan.md).

**Slices:**

| Slice | Scope |
|---|---|
| M6.1 | Capital One: `capital_one_card_v1` and `capital_one_bank_v1` |
| M6.2 | U.S. Bank: `us_bank_v1`, its CSV activity list. Its PDF is M7 (point D) |
| M6.3 | American Express: `amex_card_v1` |
| M6.4 | BFSFCU: waits for a redacted header and two invented rows (point E) |

**Points for the owner's review:**

- **A. No sample reached the repository, so every layout is unverified.** No session may read the
  owner's statements (D-019), and none was supplied redacted. Each layout is written from the lead
  engineer's knowledge of the institution's export, and its fixtures in
  `tests/fixtures/synthetic/statements/` are wholly invented, so they sit under the existing
  `.gitignore` exemption rather than a new one in `tests/fixtures/statements/`, which would loosen a
  privacy control. A layout's header must match exactly, so a different column set fails the file
  as `header_mismatch` and imports nothing. What a header cannot show, the sign of money, which
  date a column holds and whether pending rows appear, is checked within a row where the export
  allows it and otherwise stated as an assumption in [layouts.md](layouts.md). **A layout stays
  unverified until point F passes on one real file of it.**
- **B. Position does not enter cross-document identity.** Hashing a row's position in its file
  concretely contradicts D-026 and M1's required case that overlapping files do not double-count:
  an export starting one day earlier shifts every position, so the same transaction gets another
  hash, and an identifier that differs establishes distinctness, counting it twice. What the
  direction asks within one file already holds: every row is its own source record, kept with its
  document, row number, raw fingerprint and occurrence, and identical rows in one file are separate
  transactions. Each layout declares no external ID guarantee. A guarantee needs two overlapping
  real exports to show it, and a new layout version (D-026).
- **C. Fees and split transfers are recorded, not built.** None of these exports carries a parent
  or batch reference, so nothing would fill the link (working principle 1). Each fee row already
  imports as its own transaction, classifiable as `fee` (D-053) and counted as spending (D-056). A
  transfer group crosses D-054's one-to-one match and needs a migration, so it is planned as its
  own slice, on the owner's model, when a real export shows one.
- **D. U.S. Bank's PDF is M7.** M6.2 is the CSV activity list. PDF parsing and CSV-to-PDF
  matching stay in M7, as planned.
- **E. BFSFCU is not built.** Its export format is not known to the lead engineer, and inventing
  one would test a guess against itself. M6.4 starts from the header row of a real export and two
  invented rows in its format, supplied by the owner. PRD §5 names three institutions, and BFSFCU is
  the owner's addition.
- **F. Verifying a layout on a real file, the owner's step.** Not into the real ledger, since
  imports are never deleted: `init --real` a second ledger in a new `0700` folder on
  `/Volumes/CommonCents`, import one real statement period with `--declare-complete-coverage`,
  record its statement's opening and closing balances with `balance record`, and run `balance
  check`. Agreement to the cent verifies the sign, the dates and completeness. A difference, or
  any unresolved row, means the layout is wrong: the folder is removed, and the layout corrected
  under a new version before any real import.

**The owner's review, on 2026-11-09.** Points A to F approved as written, and M6.1 to M6.3 found
sound. Points A to D are resolved. Point E stays open: M6.4 is approved to build once the header
and two rows of a BFSFCU export reach this repository, which they had not when this was recorded.
Point F is the owner's to run, with the steps in [layout-verification.md](layout-verification.md).
The owner supplied a BFSFCU export's header and four rows the same day, and M6.4 was built from their
format, with every value invented: `bfsfcu_v1`, the one layout that states its status, so it is the
exception to the common rule below.

**Formats confirmed, and M6 complete, on 2026-11-09.** The owner supplied the header and three rows of
a Capital One card export and of an American Express export. Both match `capital_one_card_v1` and
`amex_card_v1` as built: columns, date formats and signs, including Amex's positive charge, so no
parser changed. Both list newest first, and their fixtures were reordered to match, keeping every
value invented. The owner recorded all four slices as complete. Still not confirmed from a real
export: the formats of `capital_one_bank_v1` and `us_bank_v1`. Point F still runs for every layout
before its first real import.

**Layout rules common to M6:** coverage by user declaration only; settlement status `unknown`,
since no export states it, which D-006 never reads as `posted` and `balance check` discloses; a
column named only `Date` is the posting date, as in `synthetic_card_v1`; an institution's
category, card number and running balance stay in the raw cells, unread (D-014, D-057).

## D-060 M7 plan: text PDF statements, and CSV and PDF counting once — Approved, points 1 to 3 and 5 amended, implemented in M7

Proposed on 2026-11-09, for the owner's review. Delivers plan.md's M7 row (text PDFs and CSV-to-PDF
matching, "same activity in both formats counts once") against PRD-backend §5 (statements with
selectable text, extracting "account metadata, transactions, and available balances", balances
never fabricated) and §21 ("overlapping CSV/PDF records count once when confidently matched").
Changes none of D-042 to D-059. One fallback in point 4 would amend D-006, and is proposed only if a
format sample needs it. Point 1 adds the first runtime dependency, a D-020 decision for the owner.
Plan only: nothing is built until it is approved, and then each slice separately. Acceptance tests,
D1 to D14 and I1 to I11, are in [plan.md](plan.md).

**Slices:**

| Slice | Scope |
|---|---|
| M7.1 | Reading a PDF's text: the dependency, `ingest/pdf_reader.py`, `pf pdf text`, W1 extended (point 1). Needs the owner's D-020 approval and one network use, for the install |
| M7.2 | U.S. Bank's statement, `us_bank_statement_v1`: the first PDF layout, its stated period and balances (point 3), its in-document check (point 5), migration 0019. Waits for the owner's format sample (point 2) |
| M7.3 | U.S. Bank's CSV and PDF counting once (point 4) |
| M7.4 | Several accounts in one statement. Built only if U.S. Bank's statement holds them (point 3) |
| M7.5 | Capital One's card statement, `capital_one_card_statement_v1`, matched with `capital_one_card_v1` |

**Recommendations, each with its alternatives:**

1. **Text extraction: pypdf, pinned, as the first runtime dependency.**
   - pypdf is pure Python, BSD-licensed, with no required dependency on Python 3.12, each to be
     confirmed from its metadata at install. A release at least two weeks old, pinned by version and
     hash in a new `requirements.txt`, installed with `--require-hashes`, and declared in
     `pyproject.toml`. One network use, for that install.
   - Imported by one module, `ingest/pdf_reader.py`, which turns bytes into pages of text lines in
     one fixed extraction mode: pypdf's layout mode where the pinned release offers it, since
     statements separate money in and out by column. Nothing else sees pypdf, and its errors are
     caught at that one boundary.
   - W1 is extended to parse the installed pypdf modules with the same refusals. A release that
     imports a network module, `subprocess` or `ctypes`, or runs a program, fails the suite and is
     not adopted.
   - The extractor's version joins the stored parser version (`1+pypdf-<version>`), so an upgrade is
     a new interpretation of new documents, never a silent rereading of stored ones (D-026). The
     same bytes are still skipped on reimport (D-022).
   - Refused, each as a file failure: an encrypted PDF (`encrypted_pdf`, since AES needs a further
     cryptography dependency), one with no text layer (`no_text_layer`, a scan), and one the library
     cannot read (`unreadable_pdf`). If U.S. Bank's statement is encrypted (point 2c), this point
     returns to the owner before M7.1.

   Alternatives: **a standard-library reader** (zlib for streams, and its own parsing of objects,
   content streams, font encodings and character maps) needs no dependency, but is on the order of a
   thousand lines (principle 5) and would be designed blind: a statement's fonts are internal to the
   real file, which no session may read (D-019), and a wrong character map garbles text without
   failing. Recommended only if the owner refuses any dependency. **The owner converting outside
   the app** (Preview's export as text) needs no PDF code, but adds a manual step per statement,
   archives the text rather than the statement (D-017), and leaves line order to macOS.
   **pdfminer.six** brings further dependencies. **pdftotext**, or any program, is refused by W1
   (D-058 point 9), and macOS's PDFKit needs PyObjC.

2. **Layouts, in order: U.S. Bank's statement, then Capital One's card statement.** U.S. Bank first,
   as promised (D-059 point D), paired with `us_bank_v1`. Capital One's card second, because its CSV
   format is confirmed from a real export, so M7.5 tests matching against a known format. Amex,
   Capital One bank and BFSFCU statements are each a later slice on the same pattern, on request.
   What the owner supplies for each, format and structure only, every value invented, as D-059
   point E did:
   - a. **The lines `bin/pf pdf text STATEMENT.pdf` prints** (M7.1) for one statement, run by the
     owner on the image. It writes nothing and opens no ledger. From the account summary to the end
     of the last transaction section, plus one repeated page header and footer. Keep word for word
     every heading, column heading and label (the opening and closing balance labels, section
     names, subtotals), the date format, how money out is shown (a minus sign, its own column, a
     trailing `-`, parentheses), and how a long description wraps. Replace every name, address,
     account number beyond its last four digits, amount, date and description with invented ones of
     the same shape.
   - b. Whether the statement holds more than one account, and if so the lines where the next
     begins.
   - c. Whether it asks for a password, or Preview shows it as secured. **This one is needed before
     M7.1.**
   - d. Two or three transactions as they appear in both the CSV export and the PDF of the same
     period, values invented, each description's wording pattern kept: prefixes, suffixes,
     reference numbers, truncation. This decides point 4.
   - e. For U.S. Bank, the CSV header and a row or two, confirming `us_bank_v1`, as already awaited.

   Each layout is built from that format alone. Its tests read the supplied line structure
   directly, and a PDF generated in the test from those lines checks the reader. Neither shows that
   pypdf reads the real file the same way. Point 5's check does, on every import.

3. **What a statement adds, without reopening D-005, D-027 or D-057:**
   - **The stated period is coverage evidence:** `complete`, `document_metadata`, on the posting
     basis, as D-005's validated layout metadata, since the layout declares that its period lists
     every transaction posted in it. Recorded only when point 5's check agrees with no unresolved
     row, otherwise `partial` with the period, as D-005 asks of a period that does not prove
     completeness. A statement states no generation date, so under D-027 its closing day is not
     established: rows on that day stay possible duplicates against a CSV, disclosed. Reading the
     closing balance as proof of that day would reopen D-027, and is not proposed. A declaration on
     a PDF is refused as `coverage_conflict`, as for any document stating coverage.
   - **The opening and closing balances are neither coverage nor observations.** They are document
     evidence, stored per document and account by migration 0019, append-only, in the ledger's sign
     convention (a card's owed amount negated, D-057). The import's check and `trace` read them.
     `derive()`, `balance check` and every token never do. D-057 keeps observations to what a person
     states, so the owner may still `balance record` them. Making them observations is a later
     decision.
   - **Several accounts in one document are neither:** they are structure. D-005 already keeps
     coverage per account, and each source record carries its account. Until M7.4, a statement
     listing more than one account fails as `multiple_accounts`, importing nothing. M7.4, only if
     needed: one import names each section's account by its printed last four digits (`--account
     NAME --statement-account LAST4`, repeated), every section must be named or the file fails as
     `unmapped_statement_account`, and each section gets its own coverage and check. Importing the
     file once per account is not an option, since D-022 rejects the same bytes under another
     account.
   - A layout states the account types it fits, since a card's balance runs the other way to a
     bank's, and another type fails the file as `account_type_mismatch`.

4. **Matching a PDF row to its CSV counterpart:**
   - **Both sides ID-less, the expected case.** No CSV layout reads an ID (D-059 point B), and a
     statement prints none. D-006's exact rule applies unchanged: the same dates, amount, folded
     description and status class, both documents complete on the same basis over the day, inside
     both effective intervals, not a boundary date, and no unresolved row that could affect the
     count, paired one-for-one by count. The PDF layout states `posted`, as a statement lists posted
     activity, and D-006 compares it as compatible with the CSV's `unknown`. `us_bank_v1` reads only
     the posting date, as a checking statement prints, so the keys align.
   - **Descriptions.** The layout joins a wrapped description with one space, so `fold` sees the
     CSV's text wherever the bank prints the same words. If point 2d shows the PDF adds or drops
     words, exact matching never fires and every overlapping row goes to review: correct, but not
     counting once. Then, and only then, M7.3 asks the owner to amend D-006: under the same coverage
     conditions, a CSV row and a PDF row are a confident pair when each is the only row of that
     account, posting date and amount in its document. Uniqueness makes the pairing unambiguous.
     Two rows of one amount on one day stay possible duplicates, and similarity still never merges
     (D-032). Alternative: a description mapping per pair of layouts, which fails silently when a
     bank changes its wording. Not recommended.
   - **Dates.** Where two layouts read different dates, such as a card CSV with both against a
     statement with one, D-006's material-field rule is applied to the exact key: the basis date
     must be present on both and equal, the other date equal where both have it. Documents of one
     layout have the same dates present, so existing outcomes are unchanged, which a test shows.
     Built in M7.5 only if Capital One's statement needs it.
   - **One side with an ID: D-026's temporary limitation is settled by keeping it.** A row with a
     validated ID pairs only by ID, and against an ID-less row it can only be a possible duplicate,
     as `test_an_id_bearing_row_against_an_id_less_row_can_only_be_a_candidate` pins. No real layout
     reads an ID and none in M7 will, so real data never reaches the case. Letting such a row also
     pair by count would mix ID pairing and count pairing in one transaction, for no layout that
     needs it. It becomes D-026's rule, revisited when a real layout gains
     a guarantee, which needs two overlapping real exports (D-059 point B). Alternative: pair it by
     the exact rule, treating its ID as absent for that comparison.
   - **M1's case still holds.** Nothing merges without D-006's evidence, so each row stays its own
     transaction until confidently matched, and an unmatched overlap is a disclosed possible
     duplicate, never a lost row. Reimporting a PDF changes nothing (D-022). The CSV and PDF of one
     period counting once in either order is I1, by A16's comparison, and a CSV export overlapping
     two statements is I3.

5. **Point F on a PDF layout.** The statement carries its own check, so every PDF import runs it:
   - **Every line of a transaction section is accounted for:** a transaction, a continuation of one,
     or a line the layout names (a heading, a page header or footer, a subtotal). Any other line
     there is an unresolved row, `unrecognized_line`, keeping its text. A line the parser silently
     skips is a PDF's characteristic failure, so none is skipped.
   - **The in-document check.** With no unresolved row, the opening balance plus the parsed rows
     must equal the closing balance to the cent, and any subtotal the layout names must agree. A
     difference fails the file as `statement_out_of_balance`, importing nothing (principle 3): with
     every row parsed, a difference means the layout is wrong. With unresolved rows the check is not
     run, the period is `partial`, and the import says why.
   - **The owner's step,** added to [layout-verification.md](layout-verification.md) in M7.2: import
     one real statement into the throwaway ledger. It passes when it imports with complete coverage
     and no unresolved row, so the check agreed. Then import the CSV export of the same period into
     the same account, declaring that period: `totals` must be unchanged, with no open review group
     but closing-day rows. That verifies point 4 on real data. A PDF layout stays unverified until it
     passes.

6. **Where it is built.** A PDF layout parses a document's lines into rows, the stated period,
   balances and accounts, beside the CSV layouts. `import_files` chooses the reader by the layout and
   stores `format = 'pdf'`, which migration 0001 allows. A row's raw cells are its lines of text and
   its page, so fingerprints and occurrences work as for CSV, and identical rows in one statement
   stay separate (D-008). A date printed without a year takes the one year that places it in the
   period. One that places nowhere leaves the row `invalid_date`. New file failures:
   `encrypted_pdf`, `no_text_layer`, `unreadable_pdf`, `statement_structure_mismatch` (an expected
   heading or label missing, the PDF's `header_mismatch`), `statement_out_of_balance`,
   `multiple_accounts`, `account_type_mismatch` and, in M7.4, `unmapped_statement_account`. New
   unresolved reason: `unrecognized_line`.

**Not in M7:** scanned PDFs and OCR; encrypted PDFs; balances as observations (D-057); the closing
day as covered (D-027); IDs from PDFs, and ID-bearing rows pairing by count; detecting a layout
(`--layout` stays required); a PDF holding several periods; statement lines outside the transaction
sections beyond the balances and the period (rewards, payment due, minimum payment, year-to-date
totals), which stay unread; investment and loan statements; fee parents and split transfers (D-059
point C); the local UI (M8).

**The owner's review, on 2026-11-09.** D-060 approved, with pypdf as the dependency under D-020, and
M7.1 approved to build and commit locally. U.S. Bank's statement opens with no password and Preview
shows it not secured (point 2c), so point 1 stands.

**Point 1, as amended the same day.** The newest pypdf release at least two weeks old, 6.21.2,
failed point 1's own test: its `filters.py` imports `subprocess`, which its JBIG2 image decoder uses
to run `jbig2dec` when that program is on the path. The owner chose to adopt it with a fenced
allowance rather than look for an older release or write a standard-library reader: W1 allows
`subprocess` in pypdf's `filters.py` alone, and only as `run` calls inside its JBIG2 decoder, and
the reader runs pypdf with `jbig2dec` unset, so the program never runs. `jbig2dec` is not installed
on the owner's Mac.

**How M7.1 was implemented:**

- **The dependency.** pypdf 6.21.2, uploaded 2026-10-21, BSD-3-Clause, pure Python, needing
  `typing_extensions` only below Python 3.11, all confirmed from PyPI's metadata. Pinned with its
  wheel's SHA-256 in `requirements.txt`, installed with `--require-hashes --no-deps`, and declared
  in `pyproject.toml`. The network was used for PyPI's release list and that one install, and is
  closed.
- **`ingest/pdf_reader.py`** returns each page's lines in pypdf's layout mode, which keeps columns
  placed apart, where plain mode joins them with one space. Trailing spaces and blank lines are
  dropped, and a blank page keeps its place. An encrypted PDF is refused before any page is read,
  even one that opens with an empty password. Any error inside pypdf is `unreadable_pdf`, and a PDF
  whose pages hold no text is `no_text_layer`. `EXTRACTOR_VERSION` names the pypdf release, for the
  stored parser version from M7.2.
- **pypdf's log.** Its warnings can quote a file's bytes, such as `invalid pdf header: b'Date,'`,
  and Python prints them to stderr when no handler takes them. The reader gives pypdf's logger a
  null handler and stops it propagating. Its `warnings.warn` calls are API deprecations only, so
  nothing filters warnings. D-037's source rule refuses `logging` in `src/`, so it now allows it in
  `pdf_reader.py` alone, and a test pins that its only uses are that null handler and propagation,
  so no record is ever written.
- **The launcher tests** (D-038) gave each copied checkout a standard-library-only environment, to
  show the application needed no package. Each now gets the declared runtime dependencies copied
  from the project's `.venv`, with no network, showing it needs nothing more.
- **`pf pdf text FILE`** prints each page's lines, escaped as D-037, opening no ledger and writing
  nothing. A failure prints only its code, with exit code 2.
- **Tests.** PDFs are written by `tests/synthetic_pdf.py`, standard library only. The JBIG2 fence is
  shown with `subprocess.run` replaced by a failure: under a configuration naming a program, the
  decoder runs it without the reader and refuses inside it, and a PDF holding a JBIG2 image reads
  without running anything. pypdf's text extraction never decodes an image, so no file reaches the
  decoder through the reader: the promised test "fails as `unreadable_pdf`" became these two.
  pytest attaches its log capture to pypdf's logger, so the log is tested by running `bin/pf` in a
  subprocess, whose stderr must be the error line alone.
- **Moved to M7.2:** D2's import of a failing PDF and D4's stored parser version, since no PDF layout
  exists to import with.


**Points 2, 3 and 5, as amended for U.S. Bank's printout, on 2026-11-09.** The owner supplied the
structure of U.S. Bank's document, values redacted, and asked for M7.2, M7.3 and M7.5 to be built
unattended. The document is a credit card's Recent Activity List printed from the website, not a
statement: one account, unencrypted, each entry on one line with its account line below, a
printout header on every page, and no period or balance. So, without reopening D-005, D-027 or
D-057:

- **Coverage is a user declaration,** on the posting basis, as for the CSV layouts. Point 3's
  stated period and point 5's in-document check have nothing to read, so neither is built, nor
  migration 0019 for balances (principle 1). D8 to D11 of the plan fall away for this layout, and
  point F uses the card statement's balances, as in M6.
- **Every line is still accounted for** (point 5): a line the layout does not know is an
  `unrecognized_line` row, and an entry with no account line a `missing_account_line` row. The
  page header and `Posted` are required, else `statement_structure_mismatch`.
- **Several accounts are refused by the account line:** every entry names its card, which must be
  the account's `--last4`, as D-061 and the owner directed. `multiple_accounts` is not needed, and
  M7.4 is not built.
- **The CSV counterpart is not `us_bank_v1`.** The owner's card CSV rows hold a date `MM/DD/YYYY`,
  the description, a signed amount with a charge positive, and the account, where `us_bank_v1`
  expects `Date, Transaction, Name, Memo, Amount` with ISO dates. Its header was not supplied, so no
  production layout is written for it (D-059 point E). M7.3 shows the matching with a test-only
  layout of those fields.
- **M7.5 is not built:** no Capital One card PDF's structure has been supplied.

**How M7.2 was implemented:**

- **`us_bank_card_activity_pdf_v1`** in `ingest/layouts.py`, described in
  [layouts.md](layouts.md). A layout now states its `file_format`, how `group_lines` turns a PDF's
  pages into rows of cells, the `account_types` it fits, and `row_account_number`, which replaced
  D-061's column name so a row can name its account inside a line. Capital One bank's check reads
  the same way.
- **`ingest/pdf_documents.py`** reads a PDF layout's document, and `csv_reader.raw_records`, now
  shared, numbers rows and fingerprints their cells, so identical PDF entries stay separate
  (D-008). `import_files` reads by the layout's format and stores it in `source_document.format`.
- **Checks before rows are stored:** the account type (`account_type_mismatch`), then the
  structure, then each row's account number. Each fails the file, importing nothing.
- **Tests:** `tests/scenarios/test_us_bank_activity_pdf.py`, on printouts written in the test with
  invented values, positioned as the owner's, with an account line after a page break. D2's
  import half and D4's stored parser version are tested here.
- **Breaks:** 16 applied, 13 caught. `$` stripping was dead code, since `parse_cents` reads `$`, and
  was deleted. A branch for an account line without digits was unreachable and was removed. A last
  entry with no account line was a test gap, now closed and caught.

**How M7.3 was implemented.** No code: D-006's exact rule already counts the same activity once.
The owner's samples show the CSV and the printout with the same date, the same description and the
same signed amount, so point 4's amendment of D-006 and its date rule are not needed, and I7 and I11
fall away. `tests/scenarios/test_csv_pdf_matching.py` pairs the printout with a test-only CSV
layout of the owner's CSV fields, under an invented header, both declared complete on the posting
basis: I1 in either order by A16's comparison, I2 for a missing declaration, another basis, a row
outside an interval and an unresolved row, I3 for a CSV spanning two printouts, I4 for identical
rows, I5 for D-026's limitation as kept, and I6 for unchanged `totals` and `report monthly` output.
A declaration vouches for its whole end date (D-007), so no closing-day row stays a possible
duplicate. Breaks: 8 applied to the rules it relies on, 6 caught here. The different-basis and
boundary-date checks cannot change this pairing, since the CSV's rows carry no transaction date and
declared coverage has no boundary day, and both are caught by `tests/unit/test_cross_document.py`.
The real pairing waits for a production layout of U.S. Bank's card CSV, then one I1 test on it.

**M7 complete, on 2026-11-09.** The owner recorded M7 complete as built: M7.1, M7.2, M7.3 and the
amendments above for the activity printout. The owner holds no U.S. Bank card CSV, so the printout
has no CSV counterpart in practice, and M7.3's test-only CSV layout stays the proof that one would
count once. The owner holds no Capital One card PDF, so M7.5 is not built, and M7.4 was not needed.
The CSV the owner sampled last is a Capital One card export, matching `capital_one_card_v1` as
built. `us_bank_card_activity_pdf_v1` stays unverified until D-059 point F passes on a real
printout.

## D-061 Capital One bank format confirmed, and its rows' account number checked — Approved, implemented

Directed by the owner on 2026-11-09, outside M7's slices, with the header and two rows of each of
two real Capital One exports, a 360 Performance Savings account and a 360 Checking account. No
value from them is kept in this repository: the fixtures invent every value, keeping the format.

**The format matches `capital_one_bank_v1` as built,** so no parser changed: the exact header,
`MM/DD/YY` dates, `Transaction Amount` never negative with `Transaction Type` `Debit` or `Credit`
giving its direction, and `Balance` a running balance after each row, newest first. Amounts drop
trailing zeros (`1400`, `14.1`), which the parser already read. The fixture now lists newest first
in that style, with a Zelle receipt and a web payment in the wording the exports showed. Still
assumed: the date is the transaction date, and the export holds posted transactions only, which
D-059 point F checks.

**The owner's choices on the account layer,** each recommended by the lead engineer:

1. **The Account Number is checked.** Each row names its account's last four digits. A layout may
   name such a column, and `capital_one_bank_v1` names `Account Number`. Every row of a new
   document must name the importing account's registered last four digits (`pf account add
   --last4`), or the file fails as `account_number_mismatch`, importing nothing, so the savings
   export cannot import into checking. A row too short to hold the column is unresolved as before,
   and is not checked. An account registered without last four digits fails the file as
   `account_number_unknown`: nothing would show which account the file belongs to. A repeat import
   of identical bytes is unchanged (D-022). Files that pass are read exactly as before, so the
   layout keeps its ID and parser version: the check refuses files, and changes no meaning.
2. **A transfer between the two accounts uses M3.2 unchanged.** The savings export's "Withdrawal
   to 360 Checking" row, classified `transfer`, is a candidate against the checking deposit of the
   opposite amount, and `review transfer match` matches them (D-054). A scenario test shows it on
   invented exports. The checking side's wording is a guess, which matching never reads.

**Open:** `pf` has no command to change an account, so an account added without last four digits
cannot gain them. If the real ledger holds such a Capital One bank account, setting them once, never
changing them after, is a follow-up for the owner's approval.

**Tests:** `tests/scenarios/test_capital_one_accounts.py`, and the layout's J1 to J7 case on the
new fixture, with its account's last four digits. Seven deliberate breaks of the check, all caught.
