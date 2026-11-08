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
own approval.

| Slice | Scope | Status |
|---|---|---|
| M3.1 | Financial types, stated by a person (D-053) | Built, awaiting review |
| M3.2 | Transfer candidates across accounts, and reconciling two accounts together | Provisional |
| M3.3 | Card payments, one-sided transfers and coverage warnings (D-012) | Provisional |
| M3.4 | Totals by financial type, with disclosures of unconfirmed candidates | Provisional |

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
