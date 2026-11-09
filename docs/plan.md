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

## M1 and M2

Complete and accepted. Their slices and acceptance criteria are in
[archive/plan-m1-m2.md](archive/plan-m1-m2.md): M1's A1 to A46, mapped to tests in
[m1-acceptance.md](m1-acceptance.md), and M2's S, C, P, N, V, U, K and Q. Later slices must keep
them passing. The rules are D-040 to D-052.

## M3 plan

Proposed on 2026-11-08. M3.1 was approved the same day with no changes. Each later slice needs its
own approval. M3.2 was built on the lead engineer's recommendations and accepted with no changes,
and M3.3 and M3.4 were accepted as built with no changes. **M3 is complete** (D-056, point C), with fees
separate from transferred principal and transfers split over several transactions left as open
PRD §9 requirements, to plan when a real layout shows one (M6).

| Slice | Scope | Status |
|---|---|---|
| M3.1 | Financial types, stated by a person (D-053) | Accepted |
| M3.2 | Transfer candidates across accounts, and reconciling two accounts together (D-054) | Accepted |
| M3.3 | Card payments, one-sided transfers and coverage warnings (D-012, D-055) | Accepted |
| M3.4 | Income and spending, with disclosures of unconfirmed transfers (D-056) | Accepted |

### M3.1 acceptance criteria

| ID | Test |
|---|---|
| F1 | Every transaction is `unclassified` until classified, and account movement is unchanged by any classification |
| F2 | Classifying a purchase adds it to that type's totals line by exactly its amount. Source evidence and `ledger_transaction` are byte-identical |
| F3 | `derive()` output is identical with and without classifications |
| F4 | Refused, with nothing changed: wrong account, unknown transaction, stale token of any kind, stale account, an unknown type, a type against the transaction's direction, a type it already has, a classified transaction without `--supersedes` |
| F5 | A stale account is not reconciled by the refused command |
| F6 | A classification survives repeat imports, `reconcile`, unrelated files and a rules change |
| F7 | Agreeing classifications apply once. Disagreeing ones leave the transaction `unclassified`, disclosed apart from duplicates, conflicts and corrections |
| F8 | An automatic split of a classified transaction leaves every part `unclassified`, disclosed |
| F9 | `review confirm` joining disagreeing classifications and `review separate` splitting a classified transaction refuse atomically |
| F10 | Chains: only the newest applies, undo steps back one link, and a superseded classification is refused naming the newest |
| F11 | Tokens: versions pinned, digests kept on ledgers without classifications, `f1` pinned, an unrelated file leaves `f1` unchanged |
| F12 | Equivalent classifications made at different valid points in the import sequence give the same outcome, exhaustively for four files |
| F13 | Migration 0013 works on a populated ledger, makes no account stale and is atomic on failure. Classification tables are append-only |
| F14 | S, C, P, N, V, U, K and Q still pass, and classifying is measured on many classified transactions against a later import |

### M3.2 acceptance criteria

| ID | Test |
|---|---|
| X1 | A transfer-kind transaction with an exactly opposite one in another account within 5 days is a candidate. No type on either side, another amount, a date outside the window, the same account, or a type that does not fit the pair is not |
| X2 | Matching changes no account movement and no type totals. Source evidence, `ledger_transaction` and `derive()` output are byte-identical |
| X3 | Refused, with nothing changed: wrong account on either side, unknown transaction, the same account, a stale token of either kind, a stale account on either side, a pair that is not a candidate, a side already matched |
| X4 | A stale account is not reconciled by the refused command |
| X5 | A match survives repeat imports, `reconcile`, unrelated files, a re-export joining either side, and a rules change |
| X6 | An automatic split of a matched side gives `basis_changed`, two matches reaching one transaction `conflict`, an amount that stops offsetting `amounts_differ`, and a type that stops fitting `type_differs`, each disclosed |
| X7 | `review confirm`, `review separate`, `review correct` and `review classify` refuse atomically to unsettle an applied match. Undos report it, and undoing a completion waits for a match |
| X8 | Card, loan and investment payments accept money in on the account they pay and refuse it elsewhere |
| X9 | Undo keeps the match on record, needs both accounts current and its token, and never refuses for contradiction |
| X10 | Tokens: `r8`, `t6` and `m1` pinned, digests kept without matches, an unrelated file leaves `m1` unchanged |
| X11 | Equivalent matches made at different valid points in the import sequence of two accounts give the same outcome, exhaustively for four files |
| X12 | Migration 0014 works on a populated ledger, marks as not current only the accounts of recommendation 7, and is atomic on failure. Match tables are append-only |
| X13 | `totals` reports matches, candidates, unmatched transfer-kind transactions and unsettled matches, for the ledger and for one account |
| X14 | S, C, P, N, V, U, K, Q and F still pass, and the outcome is measured on many matches against a later import |

### M3.3 acceptance criteria

Approved with D-055 on 2026-11-08.

| ID | Test |
|---|---|
| O1 | A one-sided transfer on a transfer-kind transaction naming another registered account applies, including one with no documents |
| O2 | Stating one changes no account movement and no type totals. Source evidence, `ledger_transaction` and `derive()` output are byte-identical |
| O3 | Refused, with nothing changed: the same account, an unknown account, a stale token, a stale account on either side, no transfer-kind type, a type that does not fit the counterpart, a side already in a match or one-sided transfer, a candidate with the counterpart account, and counterpart coverage spanning the window. A stale account is not reconciled by the refused command |
| O4 | A one-sided transfer survives repeat imports, `reconcile`, unrelated files, a re-export joining it, and a rules change |
| O5 | An automatic split gives `basis_changed`, a match or second one-sided transfer reaching the transaction `conflict` on both, a type that stops fitting `type_differs`, a counterpart import in the window `counterpart_found`, and a coverage declaration spanning it `counterpart_covered`, each disclosed |
| O6 | Coverage spanning is exact at the window's edges, on either date basis, and coverage of part of the window gives a warning and leaves the transfer applied |
| O7 | `review confirm`, `review separate`, `review correct` and `review classify` refuse atomically to unsettle an applied one-sided transfer. Undos and coverage declarations report it, and undoing a completion waits for it |
| O8 | `review transfer match` refuses a side holding an active one-sided transfer, and matches once it is undone |
| O9 | Undo keeps it on record, accepts either account, needs both current and its token, and never refuses for contradiction |
| O10 | `totals` reports one-sided transfers by counterpart coverage, the card payment warning and unsettled states, for the ledger and for one account, and unpaired transfer-kind counts leave them out |
| O11 | Tokens: `r9`, `t7` and `o1` pinned, digests kept without one-sided transfers, `m1` digests kept, and an unrelated file leaves `o1` unchanged |
| O12 | Equivalent statements made at different valid points in the import sequence of two accounts give the same outcome, exhaustively for four files, including the counterpart's arrival |
| O13 | Migration 0015 works on a populated ledger, makes no account stale, and is atomic on failure. One-sided transfer tables are append-only |
| O14 | S, C, P, N, V, U, K, Q, F and X still pass, and the outcome is measured on many one-sided transfers whose counterpart holds many opposite amounts on nearby dates and many coverage intervals, against a later import |

### M3.4 acceptance criteria

Approved with D-056 on 2026-11-08.

| ID | Test |
|---|---|
| T1 | Every transaction is in exactly one of confirmed transfers, income, spending, unconfirmed transfer kinds and unclassified, and their signed sums equal net account movement, for the ledger and for one account, over generated ledgers |
| T2 | Account movement, "By financial type" and the transfer sections are unchanged. `totals` writes nothing, and source evidence, `ledger_transaction`, `derive()` output and every token are byte-identical |
| T3 | Both sides of an applied match are confirmed transfers, including an unclassified side. Undoing it moves a transfer-kind side to unconfirmed and an unclassified side to unclassified |
| T4 | An applied one-sided transfer is a confirmed transfer. Each state that no longer applies leaves it an unconfirmed transfer kind, or unclassified once its type is undone |
| T5 | A matched or one-sided card payment is out of spending, card purchases count once as spending, and D-055's warning stays |
| T6 | Spending is purchases, fees and interest less refunds, income is `income` only, and a refund larger than the purchases gives negative spending, shown as such |
| T7 | Unconfirmed transfer kinds and unclassified transactions are in neither income nor spending, and the disclosure gives both bounds exactly |
| T8 | Confirmed transfers are reported by type with counts and amounts out and in, and loan payments and investment contributions stay apart from spending |
| T9 | An applied one-sided loan payment to a loan account warns that its interest is not in spending, and one to another account kind does not |
| T10 | A match or one-sided transfer on a transaction whose applied type is not a transfer kind stops the report with an internal error |
| T11 | The groups are the same at every valid point of the existing exhaustive import-order tests for two accounts |
| T12 | S, C, P, N, V, U, K, Q, F, X and O still pass, and `totals` is measured on a ledger with many transactions in every group, including many matches and one-sided transfers, with the new section's cost shown apart from the candidate search |

## M4 plan

Approved on 2026-11-08 as D-057, with the lead engineer's recommendations, including points A to
E. Every slice was approved, built and accepted as built. **M4 is complete.**

| Slice | Scope | Status |
|---|---|---|
| M4.1 | The 32,766-variable limit, with no change in behaviour | Accepted |
| M4.2 | Balance observations and statement reconciliation | Accepted |
| M4.3 | Monthly reports with disclosures (D-013) | Accepted |
| M4.4 | The 100,000-transaction benchmark and provisional resource targets | Accepted |

### M4.1 acceptance criteria

| ID | Test |
|---|---|
| L1 | `transaction_facts`, `_separated` and both import summary queries succeed at 32,767 IDs, each test failing on the current code |
| L2 | Their results are identical to the current code's below the limit, on generated ledgers |
| L3 | An import run of 32,767 files, a write with 32,767 transactions bound by one-sided transfers and `totals` with 32,767 active separations succeed, built directly |
| L4 | Every existing criterion still passes, with no token, migration or output change |

### M4.2 acceptance criteria

| ID | Test |
|---|---|
| B1 | Opening balance plus activity equals closing balance: an interval agrees exactly, and a one-cent change on either side gives `differs by` that cent |
| B2 | Activity counts posted transactions after the earlier day through the later one, exactly at both edges, using effective amounts and posting dates |
| B3 | Refused, with nothing changed: unknown account, a second active observation for one date, `--owed` on a non-liability, `--balance` on a card or loan, an invalid amount or date, and undo with a wrong account or stale token |
| B4 | `--owed` stores the negation, shown as owed, and a credit balance on a card round-trips |
| B5 | Covered only when complete posting-basis coverage spans every day of the interval. Transaction-basis coverage, partial coverage and a one-day gap at either edge are not covered |
| B6 | Pending transactions are left out and counted, `unknown` status and posted without a posting date are counted and disclosed, and open review items in the interval are disclosed |
| B7 | Agreement declares no coverage, settles no review item, and changes no total. Source evidence, `ledger_transaction`, `derive()` output and every token are byte-identical with and without observations |
| B8 | Migration 0016 works on a populated ledger, makes no account stale, and is atomic on failure. Observation tables are append-only |
| B9 | An observation survives repeat imports, `reconcile` and a rules change. A later import inside an interval changes its outcome |
| B10 | Tokens: `b1` pinned. Undo restores the earlier intervals exactly |

### M4.3 acceptance criteria

The schema guarantees every transaction a date, so the `no date` line of G1 is not built (D-057,
"How M4.3 was implemented").

| ID | Test |
|---|---|
| G1 | Every transaction is in exactly one month or `no date`, and their lines add to `totals` exactly, per group, for the ledger and for one account, over generated ledgers |
| G2 | A month uses the effective transaction date, else the effective posting date, and the counts of each are right. A date correction moves a transaction between months, and its undo moves it back |
| G3 | Within each month, D-056's five groups add to net account movement |
| G4 | A month is covered for an account only when complete transaction-basis coverage spans every day of it, exact at the first and last day. Posting-basis coverage does not count |
| G5 | Open review items and unsettled corrections, classifications, matches and one-sided transfers are disclosed in the month of their transactions |
| G6 | A match whose sides fall in different months counts each side in its month, and the cross-month count is disclosed |
| G7 | `--from` and `--to` are inclusive, and an invalid or reversed range is refused. `report monthly` writes nothing, and `totals` output is unchanged |
| G8 | The months are the same at every valid point of the existing exhaustive import-order tests for two accounts |

### M4.4 acceptance criteria

| ID | Test |
|---|---|
| Z1 | The shape reaches 100,000 transactions, 60 months, four accounts, at least 20,000 matches and more than 32,766 matched sides, and prints those counts |
| Z2 | It measures `totals`, `report monthly`, `balance check`, one classification and one import into that ledger, each apart |
| Z3 | A run on the code before M4.1 fails at the variable limit, showing the shape reaches it |
| Z4 | Figures and the machine go in [benchmarks.md](benchmarks.md). Targets are provisional and not test assertions (D-034, D-057) |
| Z5 | A missed target is reported with the cost behind it, not redesigned within M4.4 |
| Z6 | S, C, P, N, V, U, K, Q, F, X, O, T, L, B and G still pass |

## M5 plan

Approved on 2026-11-08 as D-058, with the lead engineer's recommendations, including points A to F.
M5.1 was approved, built and accepted as built the same day. M5.2 was approved with the owner's amendments to point
3, built the same day, and accepted on 2026-11-09, with a second amendment accepting images encrypted as files.
M5.3 was approved and built on 2026-11-09, and accepted as built the same day. M5.4 was approved on 2026-11-09, with the
owner's amendment to point 7, and M5.5 the same day. Both were built that day, and await review.

| Slice | Scope | Status |
|---|---|---|
| M5.1 | Real ledgers, their location and file permissions | Accepted |
| M5.2 | Encryption: an encrypted volume, checked on every open (D-002) | Accepted |
| M5.3 | Archiving originals, and storage by kind (D-017) | Accepted |
| M5.4 | Backup, verification and restore | Built, awaiting review |
| M5.5 | Network and dependency behaviour, and the readiness checklist | Built, awaiting review |

### M5.1 acceptance criteria

| ID | Test |
|---|---|
| H1 | `init --real` marks a ledger real. Plain `init` and every ledger before 0017 are synthetic. Only a ledger holding no account and no import run can be marked, each refusal with a control that succeeds, and the mark is never changed or removed |
| H2 | `init --real` refuses, creating nothing: a missing folder, a folder in a git work tree (a `.git` folder or file), in each synced folder, reached through a symbolic link, open to group or others, or owned by someone else. A private folder gives a `0600` ledger |
| H3 | Every kind of command on a real ledger, read-only ones and `migrate` included, refuses with nothing changed once its folder or database is open to others, a `.git` appears above it, or it is reached through a symbolic link, and opens once safe |
| H4 | A real ledger refuses an import with any file inside a git work tree, followed through links, importing nothing. A synthetic ledger imports from anywhere |
| H5 | A synthetic ledger in a git work tree with shared modes opens as before, and every earlier criterion passes with no token or output change |
| H6 | Migration 0017 works on a populated ledger, leaves it synthetic, makes no account stale, and is atomic on failure |

### M5.2 acceptance criteria

| ID | Test |
|---|---|
| E1 | A real ledger opens, and `init --real` creates one, only in a folder inside a mounted disk image honouring ownership, whose volume diskutil reports encrypted or whose image hdiutil reports encrypted. The startup volume, FileVault or not, is refused. Not encrypted, an unknown answer, a missing key and a failed probe each refuse with nothing changed |
| E2 | The probe reads `diskutil info -plist` output for the folder's volume, and `hdiutil info -plist` for its image, tested on recorded synthetic outputs. The suite never mounts a volume |
| E3 | A real ledger runs with `temp_store = MEMORY`, and a sort larger than the page cache writes nothing to the temp folder |
| E4 | Its rollback journal sits beside the database and is created `0600` |
| E5 | No probe runs for a synthetic ledger, and every earlier criterion passes |

### M5.3 acceptance criteria

| ID | Test |
|---|---|
| Y1 | Importing into a real ledger copies each new document to `originals/` under its SHA-256, byte-identical and `0400`, before the import commits. A repeat import copies nothing |
| Y2 | A failed copy fails the file as `archive_failed`, keeping nothing. A copy left by a rolled-back import is reported as not referenced |
| Y3 | Archiving changes no transaction, token or provenance, and no identity reads a location. A synthetic ledger archives nothing |
| Y4 | `archive verify` reports missing, altered and unreferenced originals exactly, and passes an intact archive |
| Y5 | `pf storage` reports software, database with its journal, originals and backups apart, in bytes and files |

### M5.4 acceptance criteria

| ID | Test |
|---|---|
| R1 | `backup create` writes a new folder on a gated volume other than the ledger's, and refuses an existing folder, the ledger's own volume and an unsafe destination, writing nothing |
| R2 | The manifest holds each file's hash and size, the schema and code versions, and the logical digest |
| R3 | `backup restore` writes only to a new path passing every gate, and refuses any altered or missing file, a failed integrity or foreign-key check, a newer schema and a digest difference, leaving nothing |
| R4 | Every report, list and token of a restored ledger matches the original's byte for byte, over generated ledgers holding decisions, corrections, classifications, matches, one-sided transfers and observations, and every original matches by hash |
| R5 | `backup verify` runs R3's checks without restoring, and a backup taken while another connection writes is consistent |

### M5.5 acceptance criteria

| ID | Test |
|---|---|
| W1 | No module under `src/` imports a network module or `subprocess`, outside the `diskutil` and `hdiutil` calls in `db/volume_probes.py`, and an added import fails the test |
| W2 | [status.md](status.md) states the network and dependency behaviour, once |
| W3 | `docs/real-data-readiness.md` lists each step with its command and expected output, moving the owner's statements into the image among them, walked through on synthetic data in `build/` |
| W4 | Every earlier criterion still passes |

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
