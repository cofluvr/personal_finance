# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-056 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
holds the index, the rules in brief, and the newest decisions in full, once there are any. When a
decision here is accepted and the next one is written, move its full text to the end of that file
and keep its index line.

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
| D-055 | Card payments, one-sided transfers and coverage warnings — Approved, implemented and accepted in M3.3 |
| D-056 | Income and spending — Approved, implemented and accepted in M3.4 |
| D-057 | M4 plan: balances and reports — Approved, M4.1 implemented and accepted |

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
| Income and spending | Five groups, each transaction in one, adding to net account movement: confirmed transfers, income, spending, unconfirmed transfer kinds and unclassified | D-056 |
| Confirmed transfers | A side of an applied match or one-sided transfer, whatever its own type | D-056 |
| Unconfirmed transfer kinds | Neither income, spending nor transfers, disclosed as a bound on both | D-011, D-056 |
| Reporting periods | In M4, with D-013. Totals cover the ledger or one account | D-056 |
| ID lists | One JSON array parameter read with `json_each`, never one SQL parameter per ID | D-057 |

## Not yet decided

From `shared-contract.md` §6: transfer-matching rules (M3), safe-to-spend details
and loan projection assumptions (Phase 1B), pairing protocol and snapshot
compatibility (Phase 1C), backup and recovery design (M5), resource benchmarks
(M4).

## D-057 M4 plan: balances and reports — Approved, M4.1 implemented and accepted

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
