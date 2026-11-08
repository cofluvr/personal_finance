# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-052 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
holds the index, the rules in brief, and the newest decisions in full. When a decision here is
accepted and the next one is written, move its full text to the end of that file and keep its
index line.

## Index

| Decision | Title and status |
|---|---|
| D-001 | Database: SQLite through the standard library — Approved |
| D-002 | Encryption — Pending, by M5 |
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

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
