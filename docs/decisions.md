# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-054 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-054 | Transfers across accounts — Approved, implemented and accepted in M3.2 |
| D-055 | Card payments, one-sided transfers and coverage warnings — Approved, implemented in M3.3, awaiting review |

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

## D-055 Card payments, one-sided transfers and coverage warnings — Approved, implemented in M3.3, awaiting review

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

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
