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

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
