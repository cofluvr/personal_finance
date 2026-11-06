# Implementation Plan

The PRDs are the source of truth. This document records how they are delivered.
Reasons for each rule are in [decisions.md](decisions.md), and progress is in
[status.md](status.md).

Approved by the owner on 2026-11-05, with the amendments now folded in below.

## Architecture

A single local Python package with a CLI, backed by one SQLite file. The browser
UI arrives later and calls the same core code. The data has three layers:

1. **Source documents and source records:** each document's fingerprint plus
   every raw row exactly as read, never edited.
2. **Logical transactions:** one per real-world event, linked to every source
   record that supports it. Totals read only this layer.
3. **Decisions and overrides:** user corrections stored separately and applied
   on top of parsed values, so re-parsing cannot overwrite them (M2).

## Milestones

| Milestone | Scope | How it is tested |
|---|---|---|
| **M1** Foundation | Scaffolding, data model, synthetic CSV import, provenance, duplicate handling, CLI | Synthetic import scenarios |
| **M2** Review and corrections | Confirm, reject and undo decisions; correction overrides; pending-to-posted matching; CLI review queue | Decisions survive re-imports or are flagged; undo restores totals |
| **M3** Transfers and card payments | Financial types, transfer candidates, one-sided transfers, fees, coverage warnings | Confirmed transfers and card payments stay out of income and spending; suspected transfers stay unresolved |
| **M4** Balances and reports | Balance observations, statement reconciliation, monthly reports with disclosures, 100,000-transaction benchmark | Opening balance plus activity equals closing balance |
| **M5** Real-data gate | Data location outside the repo, encryption, file permissions, archiving, backup and restore | Restore test; refuses unsafe locations |
| **M6** First real CSV layouts | Only layouts supplied as redacted samples, one at a time | Each layout has fixture tests |
| **M7** PDF parsing | Text PDFs and CSV-to-PDF matching | Same activity in both formats counts once |
| **M8** Local review UI | Loopback-only import results, review queue, transactions | Host and CSRF checks; UI totals match the CLI |

M5 is mandatory before any actual financial document is processed. Phase 1B
planning, Phase 1C sync and iOS are planned once Phase 1A passes.

## Required financial test cases

| Required case | Milestone |
|---|---|
| Reimporting the same file does not change totals | M1 |
| Overlapping files do not double-count confidently identified duplicates | M1, with CSV-to-PDF in M7 |
| Legitimate identical purchases stay distinct | M1 |
| Ambiguous candidates stay visible | M1, with resolving them in M2 |
| Missing information is not fabricated | M1 |
| Every transaction traces to its source | M1 |
| Pending and posted versions reconcile | M2 |
| User corrections survive repeat imports | M2 |
| Confirmed transfers are not income or spending | M3 |
| Card payments do not duplicate purchases | M3 |

## M1 slices

Each slice stops for review.

1. Scaffolding, `.gitignore`, money module, schema and migrations, decision log,
   status document.
2. Two invented CSV layouts, coverage metadata, provenance, idempotent import:
   - `synthetic_checking_v1`: external IDs, signed amounts.
   - `synthetic_card_v1`: no IDs, separate debit and credit columns.
   Includes the CLI needed to exercise it: `init`, `account add`, `import`,
   `documents`, `transactions`, `trace`, `review list`, `totals`. Each new row
   becomes a new transaction, and output warns that overlaps are not checked.
3. Cross-document duplicate handling (D-005 to D-008).
4. Complete import summaries, log checks, a `pf` entry point, setup documentation.
   Results are in [m1-acceptance.md](m1-acceptance.md).

Out of scope for M1: real institution layouts, PDFs, the browser UI, transfer
logic, categories, archiving, encryption, resolving review items.

M1 totals are labelled **account inflows**, **account outflows** and **net
account movement** (D-010).

## M1 acceptance criteria

The slice column shows where each test is first expected to pass. "Part" means
the slice proves the rule at the module or schema level and a later slice proves
it end to end.

### Import and identity

| ID | Scenario | Expected result | Slice |
|---|---|---|---|
| A1 | Import a byte-identical file twice, under any coverage | No new records or transactions; totals and open review items unchanged; attempt recorded | 2 |
| A2 | Re-export of the same rows in a different order, both documents with confirmed complete coverage | No new transactions; the extra sources are linked | 3 |
| A3 | Two files with confirmed complete coverage that overlap | Rows in the overlap count once and both sources are kept | 3 |
| A4 | Two identical purchases in one file | Two transactions, even after importing an overlapping file | 3 |

### Coverage and confidence

| ID | Scenario | Expected result | Slice |
|---|---|---|---|
| A5a | 2 identical rows in one file, 3 in another, both with confirmed complete coverage of that date on the same date basis | Exactly 3 transactions, no review item for the pairing | 3 |
| A5b | The same rows where either file has partial or unknown coverage | All 5 records stay as separate transactions, flagged together as one open review item. Summaries say totals may be overstated, without presenting an exact adjustment | 3 |
| A6 | Near-match with a date one day off and a matching description | Both kept and counted, and shown in `review list` | 3 |
| A7 | Same external ID, different amount | Flagged, never merged | 3 |
| A8 | Same rows in two different accounts | Never matched | Part 1, 3 |
| A20 | Same reliable external ID and amount in two files with unknown coverage | Confident duplicate: coverage is not needed when identity is proven | 3 |
| A21 | External ID from a layout that does not declare its IDs reliable, using a test-only synthetic layout | Treated as description-level evidence only; not sufficient alone. No production layout is added or claimed | 3 |
| A22 | Identical-looking ID-less purchases on a date where the two files' shared coverage is that single date | Kept separate and flagged, even when both claim complete coverage, including `user_declared`. Intentional conservative policy (D-007) | 3 |
| A23 | Coverage dates derived only from the earliest and latest rows | Never recorded as complete; recorded as unknown | Part 1, 2 |
| A24 | Same rows, coverage stated on different date bases (transaction versus posting) | Not treated as confirmed overlap; flagged | 3 |
| A26 | User declaration of complete coverage | Needs account, inclusive dates, date basis and the explicit flag; stored as `user_declared` | 2 |
| A27 | Rows with no counterpart in another document, coverage unknown | Not flagged: unknown coverage alone never enters review | 3 |
| A28 | Overlapping candidate groups | Summaries show no single exact adjustment figure | 3 |
| A32 | ID-less match on the inclusive end date, both documents `user_declared`, shared coverage longer than one date | Confident, with no generation date needed | 3 |
| A33 | Match on the end date of a `document_metadata` claim with no generation date, or generated that day | Possible duplicate: the end date is not assumed complete | 3 |
| A34 | Same reliable external ID with a conflicting date or status, or repeated within a document | Flagged, never merged | 3 |
| A35 | Exact match where an unresolved row could affect the count | Possible duplicate, with the unresolved disclosure kept | 3 |
| A42 | Unrelated purchases with the same date and amount in different documents | No candidate and no review item | 3 |
| A43 | Plausible merchant or description variations within the date window | Creates a review item, and never merges automatically | 3 |
| A44 | Reliable-ID matching alongside heuristic discovery | Each runs on its own evidence: an ID match does not need a similar description, and similarity never produces a merge | 3 |
| A45 | Reliable external ID with compatible fields on a single-day overlap | Confident: the single-day policy applies only to ID-less matching | 3 |
| A46 | Reliable ID match where one record has `unknown` status and the other `posted` | Not a status conflict. Both source statuses are preserved, and `unknown` is not filled in | 3 |
| A29 | One external ID repeated within a document | Kept, counted and flagged | 2 |
| A30 | Pending and posted versions within a document | Kept, counted and flagged, with each record's status preserved | 2 |

### Missing and malformed values

| ID | Scenario | Expected result | Slice |
|---|---|---|---|
| A9 | Blank amount or date | Row goes to the unresolved queue with no transaction created | Part 1, 2 |
| A10 | Amount of `0.00` versus blank; blank posting date | Zero stays zero; missing values stay missing | Part 1, 2 |
| A11 | Sub-cent or malformed amounts | Goes to the unresolved queue, never rounded | Part 1, 2 |
| A12 | 1,000 rows of `0.10`, and both sign conventions | Exactly `100.00`; both layouts normalize correctly | Part 1, 2 |

### Provenance, robustness and privacy

| ID | Scenario | Expected result | Slice |
|---|---|---|---|
| A13 | Every transaction | Links to at least one source record, with its document, row number and the unaltered original row | Part 1, 2 |
| A14 | One bad file among good ones | Good files commit; the bad file leaves no partial data and is reported | 2 |
| A31 | Failure or process crash partway through a file | No records or transactions remain, and the file can be imported again | 2 |
| A36 | Merged transaction | Every source record stays linked and traceable, and no raw evidence changes | 3 |
| A37 | Failure or crash during matching | No partial merge state; the file can be imported again | 3 |
| A38 | Repeat imports after merges and flags | No new links, transactions or review items | 3 |
| A39 | Large synthetic dataset | Candidate discovery uses indexed lookups, not all-pairs comparison, and stays practical | 3 |
| A40 | Byte-identical file under a different account | Rejected and explained; existing import preserved | 2 |
| A41 | Complete coverage with an unresolved row | Disclosure stays, and no transaction is created for the row | 2 |
| A15 | Two simultaneous imports | Ledger stays consistent with no double-counting | 2 |
| A16 | Property test: random import order and repeats, across complete, partial and unknown coverage | Financial totals, source associations and unresolved candidate relationships are equivalent for every order. Generated IDs and display order are not compared | 3 |
| A17 | Import summary | Import summaries report counts with explicit units. Where counts form a partition, they reconcile within that unit. File outcomes reconcile to files attempted, and row outcomes reconcile to rows read under the documented parsing definitions. Transaction matches, review flags, and review groups are reported separately because they may overlap and must not be added into a single row total. Disclosure of unresolved records and failed files is preserved, and row counts are not fabricated when a file cannot be read | 4 |
| A18 | Logs during import | Contain no sentinel merchant names or amounts | 4 |
| A19 | Network calls during tests | Sockets blocked; the full suite still passes | 1 |
| A25 | `totals` output | Uses the labels from D-010 and never says income or spending | 4 |

M1 is finished when all tests pass, a new-setup run works from the README, and
the decision log records the database, parser and deduplication rules.

## M2 plan

M2.1 is accepted. The M2.2 plan is approved and not implemented. **M2.3 to M2.9 are provisional**:
a direction, not approval to implement, and each needs its own approval. D-041 lists requirements
they must meet.

| Slice | Scope | Status |
|---|---|---|
| M2.1 | Review evidence: `review list` IDs, `review show`, revision tokens. Read-only, no migration | Accepted |
| M2.2 | Decision core: stable-ID storage, precedence over automatic reconciliation, pair rejection and undo | Plan approved, not implemented |
| M2.3 | Confirm, including part of a group | Provisional |
| M2.4 | Separating machine-made merges | Provisional |
| M2.5 | New evidence that touches a decided record, and superseding a decision | Provisional |
| M2.6 | Correction overrides | Provisional |
| M2.7 | Resolving incomplete records | Provisional |
| M2.8 | Coverage correction with history | Provisional |
| M2.9 | Pending to posted, including tips, changed descriptions and the D-008 migration | Provisional |

Direction from planning, not yet decisions:

- Identity decisions anchor on `source_record.id`. A merge deletes the retired
  `ledger_transaction` row, so transaction IDs can only be snapshots. Field corrections are a
  separate layer that matching never reads.
- Precedence has to land with the first stored decision, because the next reconcile would
  otherwise undo it. So storage and survival across imports cannot be separate slices.
- A group can hold several records from one document, which `transaction_source` refuses to
  merge, so confirming needs more than yes or no. Reject is settled by D-042.
- Undoing a decision re-derives from current evidence. Undoing a machine-made merge is a new
  decision, because otherwise the next reconcile would merge the records again.

### M2.1 acceptance criteria

| ID | Scenario | Expected result |
|---|---|---|
| R1 | `review list` | Gives an item ID for every item. No amounts, descriptions, cells or revision |
| R2 | `review show` on each item type | Candidate, external-ID, both same-document rules and unresolved items each show useful evidence |
| R3 | The six kinds of evidence (D-040) | Stay visibly separate |
| R4 | Missing values | Shown as missing. Zero stays zero, and no transaction is shown for an unresolved row |
| R5 | Records sharing a document | Identified in a summary and on each record |
| R6 | Ambiguous group | States that no exact adjustment exists, and shows no computed figure |
| R7 | Revision token | Stable across repeat imports, `reconcile` and unrelated files. Changes with any material field. Equal across import orders |
| R8 | Read commands | Open read-only, and leave every table and the file unchanged |
| R9 | Outdated schema | Explains `migrate`, and writes nothing |
| R10 | Privacy | Explicit inspection shows data. Routine output, refusals and unexpected errors do not |

### M2.2 scope

The rules are D-042 (rejection and constraints), D-043 (validation and undo) and D-044 (conflicts).
Planning replaced three earlier ideas: decisions are pair constraints rather than partitions, only
stated pairs are bound rather than pinning decided records, and conflicts have their own kind
rather than sharing `possible_duplicate`.

In scope:

- Migration 0005: decision, constraint and event tables, append-only with triggers, and the
  `decision_conflict` kind. A new `decision_id` column on `transaction_link_history`.
- Constraints in `derive()`, withheld merges and both conflict reasons.
- `review reject`, `review decisions`, `review decision show`, `review undo`.
- Revision version 2. `review show` gains an account line and an "already decided" section.
- Rejection applies to `cross_document_candidates` items only. Others are refused with an
  explanation.

```sh
pf review reject --db DB --account A ITEM_ID --revision R --pair T1 T2 [--pair T1 T3]
pf review undo --db DB --account A DECISION_ID --revision R
```

`--pair` repeats so that one decision stays atomic, since a first rejection would otherwise change
the token for a second.

Deferred: confirm and partitions, superseding, separating machine merges, external-ID and
same-document items, fingerprint hints, corrections.

Candidate discovery uses union-find and stores no pairs (D-031), so one link cannot simply be
removed. Direct links are recomputed only inside groups a constraint touches.

### M2.2 acceptance criteria

| ID | Test |
|---|---|
| S1 | Migration 0005 works on a populated ledger, keeps every issue and subject, and foreign keys still hold. Decision tables refuse update, delete and replace |
| S2 | With no constraints, `derive()` output is identical to today, and A16 still passes |
| S3 | Reject leaves totals unchanged and moves no records, and source evidence is byte-identical |
| S4 | A two-member item closes. A three-member item keeps the undecided pair open |
| S5 | Refused, with nothing changed: wrong account, wrong item, matching token on the wrong item, old token, stale account, pair outside the item, repeated pair, unsupported item type |
| S6 | A stale account is not reconciled by the refused command |
| S7 | A decision survives repeat imports, `reconcile`, unrelated files and a rules change |
| S8 | A third document that would merge a rejected pair gives three transactions and a `decision_conflict` |
| S9 | Conflicts are counted apart from possible duplicates in `totals`, summaries and `review list` |
| S10 | A decision in one overlapping item applies in the other, and that item's token changes |
| S11 | Exact re-export of a bound row: the decision does not transfer, and the new pair stays undecided |
| S12 | An automatic split of a bound transaction raises `decision_basis_changed` |
| S13 | Undo equals a ledger built without the decision, with no imports since and with imports since |
| S14 | Decision and undo history stay append-only, and retired IDs revive with their `created_at` |
| S15 | Property test: import order does not change the outcome for any fixed decisions |
| S16 | Link recomputation matches union-find components, with a measured cost on dense groups |
| S17 | Privacy: `reject`, `undo` and `review decisions` show no amounts or descriptions. Escaping tests stay |

## Backlog benchmarks

Not scheduled, and not part of A39 acceptance.

- **Merge-heavy overlapping exports:** complete overlapping exports with confirmed
  coverage, so that most rows merge. Measure reconciliation computation and database
  application separately, because the fixtures behind D-034 merge nothing and so never
  exercise link, history and retirement writes at scale.

## Phase 1B backlog

Recorded for later planning. None of this is in M1 scope.

- **Financial scenarios:** a local UI for named scenarios with dated income and
  expense changes, compared with the baseline after the user requests
  recalculation. Inputs, comparison outputs and safeguards are in
  [PRD-backend.md](PRD-backend.md) §15, "Scenario Inputs and Comparison".
