# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-053 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-054 | Transfers across accounts — Approved in advance, implemented in M3.2, awaiting review |

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

## D-054 Transfers across accounts — Approved in advance, implemented in M3.2, awaiting review

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

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).
