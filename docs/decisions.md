# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-062 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
holds the index, the rules in brief, and the newest decisions in full, once there are any. When a
decision here is accepted and the next one is written, move its full text to the end of that file
and keep its index line.

## Index

| Decision | Title and status |
|---|---|
| D-001 | Database: SQLite through the standard library — Approved |
| D-002 | Encryption — Approved in D-058, implemented and accepted in M5.2 |
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
| D-057 | M4 plan: balances and reports — Approved, implemented and accepted in M4 |
| D-058 | M5 plan: the real-data gate — Approved, implemented and accepted in M5 |
| D-059 | M6 plan: first real CSV layouts — Approved with points A to F, implemented in M6 |
| D-060 | M7 plan: text PDF statements, and CSV and PDF counting once — Approved, points 1 to 3 and 5 amended, implemented in M7 |
| D-061 | Capital One bank format confirmed, and its rows' account number checked — Approved, implemented |
| D-062 | M8 plan: the local review UI — Approved with A to E, read-only, implemented in M8, verified by the owner |
| D-063 | M9 plan: spending categories — Pending, for the owner's review |

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
| Balance observations | A posted balance at the end of one day, stated by a person. A card or loan states what it owes, stored negated. One active per account and day. Never transaction evidence | D-057 |
| Statement reconciliation | Consecutive observations, activity after the earlier day through the later one, by effective posting date else transaction date. Agreement is evidence, not coverage, and a difference is never absorbed | D-057 |
| Scale benchmark | 100,000 transactions, 60 months, four accounts, 20,000 matches. Below two seconds per report, provisional, never a test assertion | D-034, D-057 |
| Monthly reports | A transaction's month is its effective transaction date, else its effective posting date. Months add to `totals`, D-056's groups add to each month, and a month is covered only by complete transaction-basis coverage of every day | D-013, D-057 |
| Real ledgers | Real or synthetic, fixed at `init`. Only a real ledger is checked, on every open, and a synthetic one is never promoted | D-058 |
| Real ledger location | Refused inside a git work tree or a synced folder, through a symbolic link, not owned by the user, or open to group or others. Checked, never repaired. Its imports never come from a git work tree | D-019, D-058 |
| Originals | A real ledger keeps each new document's bytes in `originals/` under its SHA-256, `0400`, before the import commits. Never overwritten or deleted. Identity never reads it | D-017, D-058 |
| Encrypted volume | A real ledger's folder is inside, never at the root of, a mounted disk image whose APFS volume honours ownership, and which diskutil reports encrypted or hdiutil reports encrypted as an image. FileVault on the startup volume does not count. Any other answer refuses. Temporary files stay in memory | D-002, D-058 |
| Account number in rows | A layout whose rows name the account's last four digits refuses a file naming another, or an account with none registered, importing nothing | D-061 |
| PDF layouts | A layout groups a PDF's lines into rows, keeping each. A line it does not know is an unresolved row, never skipped. A document stating no period takes a declaration, as a CSV | D-060 |
| CSV and PDF | One event in both counts once only by D-006's exact rule, unchanged. An ID-bearing row against an ID-less one stays a possible duplicate | D-006, D-026, D-060 |
| Report text | `totals`, `report monthly`, `documents`, `transactions`, `review list` and `review show` are built as lines in `reports/report_text.py`, which the CLI prints and the UI renders. A page computes nothing of its own | D-062 |
| Local UI | `pf ui` serves read-only pages on `127.0.0.1` at a port the system picks, with no option to change it. Exact Host, a one-use launch key for an `HttpOnly`, `SameSite=Strict` cookie, `GET` only, no script, no logging, the ledger opened read-only through the gate on every request. Decisions stay in the terminal | D-062 |
| W1 and `http` | Only `ui/server.py` imports from `http`, and only `http.server`'s `BaseHTTPRequestHandler` and `HTTPServer` | D-058, D-062 |
| PDF text | pypdf alone reads it, pinned by hash, imported by `ingest/pdf_reader.py` only, with `jbig2dec` unset and its log silenced. W1 parses pypdf too, allowing only its JBIG2 decoder's `subprocess` | D-020, D-060 |
| Backups | A new folder, on a mounted volume other than a real ledger's and gated as its folder is, holding the ledger, its referenced originals and a manifest of hashes, sizes, versions and a logical digest. Restore never overwrites, and checks every file, integrity, foreign keys, schema and digest first | D-058 |

## Not yet decided

From `shared-contract.md` §6: safe-to-spend details and loan projection assumptions
(Phase 1B), and pairing protocol and snapshot compatibility (Phase 1C). Transfer matching
was decided in D-054, resource benchmarks in D-057, and backup and recovery in D-058.

## D-063 M9 plan: spending categories — Pending, for the owner's review

Proposed on 2026-11-09. **M1 to M8 deliver every Phase 1A item** of PRD-backend §3, so M9 opens
Phase 1B, which plan.md leaves to be planned once Phase 1A passes (point 1). M9 is the first of its
features, and the one the rest stand on: **categories** (PRD §10), stated by a person and totalled
within spending, so that budgets, goals and reserves later have something to count. Builds on D-053's
financial types and D-056's spending group, as D-014 ordered: type before category. Changes none of
D-042 to D-062. **No security control changes,** no dependency is added, and the UI stays read-only.
Plan only: nothing is built until it is approved, and then each slice separately. Acceptance tests,
CA1 to CC5, are in [plan.md](plan.md).

```sh
pf category add  --db DB NAME [--parent NAME]
pf category list --db DB
pf review categorize --db DB --account A TRANSACTION_ID --revision t…  --category NAME \
   [--supersedes CATEGORIZATION_ID --supersedes-revision g1-…]
pf review categorizations      --db DB [--account A]
pf review categorization show  --db DB CATEGORIZATION_ID
pf review categorization undo  --db DB --account A CATEGORIZATION_ID --revision g1-…
pf totals / pf report monthly       # gain "Spending by category"
```

**Slices:**

| Slice | Scope |
|---|---|
| M9.1 | The category list: migration 0019, PRD §10's starting set, `pf category add` and `list` |
| M9.2 | Categorizing one transaction: D-053's model, extracted to serve types and categories alike (point 4), migration 0020, tokens, `review show` |
| M9.3 | Spending by category in `totals` and `report monthly`, and so on the UI's pages |

**Recommendations, each with its alternatives:**

1. **Phase 1A passes, and M9 starts Phase 1B.** CSV and PDF ingestion, account identification,
   normalization, deduplication, transfers and card payments, the review interface, and balances and
   reports are M1 to M8. Of §21's criteria, five are Phase 1B's (splits, annual reserves, third
   paychecks, goal allocations and graduated payments), and "backups restore records, rules,
   corrections, and goals" holds for all but goals, which do not exist yet. The rest pass. Still open, and not blocking categories: point F
   on one real file of each layout (D-059), which only the owner can run. Alternatively **an M9 of
   Phase 1A hardening** (point F for every layout first, and any correction it finds) before any
   Phase 1B work: recommended only if the owner wants real-file confidence before new features.

2. **Phase 1B, in the order each needs the last,** as a proposed sequence, each milestone planned
   on its own as M9 is here:

   | Milestone | Scope | Needs first |
   |---|---|---|
   | M9 | Spending categories, by a person | Financial types (D-053) |
   | M10 | Categorization rules: future and historical matches, preview, undo, a person's category first (PRD §10) | M9 |
   | M11 | Household members, attribution by account and transaction, splits by amount or percentage summing exactly (PRD §6, §21) | M9, and the owner's household and account assignments (§22) |
   | M12 | Budgets, spending allowances and safe-to-spend (PRD §12) | M9 to M11, and shared-contract §6's safe-to-spend decision |
   | M13 | Goals, the emergency fund, annual and irregular reserves (PRD §13) | M12 |
   | M14 | Graduated loans, scenarios and the tax reserve (PRD §14 to §16) | M12, M13, and the owner's loan documents (§22) |

   Only M9 is proposed for approval now. Alternatively **household first** (M11 as M9), if
   attribution matters more to the owner than categories: it needs the owner's household and
   account assignments before it can start.

3. **A category list, stored, starting from PRD §10.**
   - Migration 0019 adds `category`: an internal ID, a unique name, an optional parent, and when it
     was made. Append-only: no rename, merge or delete in M9, so every assignment keeps meaning what
     it meant (principle 1: those wait until needed, each with its own rules for history).
   - It starts with PRD §10's list: Housing, Utilities and communications, Food, Transportation,
     Health, Shopping and household, Entertainment, Travel, Gifts and donations, Insurance, Interest
     and financial fees, and Other. "Uncategorized" is never stored: it is the absence of a category
     that applies, as `unclassified` is (D-053).
   - `pf category add NAME [--parent NAME]` adds one, one level deep: a subcategory's parent is a
     top-level category. Names are compared exactly, shown as typed and escaped as D-040.
   - Alternatively **an empty list,** every category added by the owner: no assumed names, but a
     ledger with no categories until set up. Or **a fixed list in code,** with no `category` table:
     less schema, but PRD §10 asks for configurable subcategories.

4. **A categorization is D-053's classification of a second field,** and its code is extracted, not
   copied (principle 2: this is the second use).
   - It binds the records of its transaction when made, applies after derivation, is never read by
     matching, and follows D-049's rules: agreeing categorizations apply, disagreeing ones or one
     whose records split leave the transaction uncategorized and disclosed, chains follow D-048,
     undo never refuses, and `review confirm` and `review separate` refuse to leave one unsettled.
   - **Only spending is categorized:** a transaction whose applied type is `purchase`, `fee`,
     `interest` or `refund` and that is in D-056's spending group. Anything else is refused,
     changing nothing. If its type later changes, or it becomes a confirmed transfer, the
     categorization stays on record and does not apply, in a fifth state, `not_spending`, disclosed
     like D-053's `against_direction`. Income categories, such as salary and side income, belong to
     PRD §11's later work.
   - **Stored apart:** migration 0020, with M9.2, adds append-only `category_assignment`,
     `category_assignment_record` and `category_assignment_event`, and a derived
     `transaction_category`, mirroring 0013's tables. M9.1's 0019 adds only `category`, so no table
     waits unused for a slice not yet approved.
     `type_classification` is not widened, since changing its checks means rebuilding tables others
     reference (D-053 point 4).
   - **The extraction:** `reconcile/classifications.py`, `classification_effects.py` and
     `reports/classification_evidence.py` become one implementation taking a description of the
     field (its tables, its values, its fit rule), used for types and categories. Every types
     command's output, token and refusal must stay byte for byte as now, compared on every ledger the
     suite builds, as M8.1 did.
   - **Tokens:** `r`, `t`, `d` and `c` add each transaction's categorizations, left out while empty
     so existing digests are kept, with their versions bumped. `g1` is the new categorization undo
     token: `b`, `c`, `d`, `f`, `k`, `m`, `o`, `r`, `t`, `u` and `v` are taken.
   - Alternatively **one assignment to a category per transaction, overwritten:** far less code, but
     no history, no undo and no protection against stale evidence, which D-043 and D-049 require of
     every decision.

5. **Spending by category, adding exactly to spending.** `totals` and `report monthly` gain, under
   Spending, one line per category with a categorized transaction, subcategories indented under
   their parent and included in its line, then an `uncategorized` line. Their sum is D-056's
   Spending exactly, for the ledger, one account and each month, tested as M3.4's and M4.3's
   invariants are, on generated ledgers. A disclosure gives the count and amount of uncategorized
   spending, and the categorizations that do not apply, by reason. Nothing else in either report
   changes. The UI's pages show them with no UI change, through the builders, and M8's parity tests
   are run on categorized ledgers too.

6. **What does not change, and the security boundaries.**
   - No security control changes: W1, the UI, the gate and D-037 are untouched. The UI stays
     read-only, so categorizing is a terminal command, with D-043's checks.
   - A category name is the owner's label, like an account name: routine output may show it, and
     amounts by category are aggregates, as `totals` already shows (D-037). Names are escaped
     wherever printed.
   - Migrations 0019 and 0020 are explicit (D-035). On the real ledger the owner runs `pf backup
     create`, then `pf migrate`. Backups and restore cover the new tables with no change, since the manifest's
     logical digest hashes every table.
   - No dependency, no network, synthetic fixtures only.

**Not in M9:** rules and bulk categorization (M10), household attribution and splits (M11), tags,
fixed and discretionary classes, income categories, renaming, merging or deleting a category,
categorizing from the UI, a normalized merchant, local AI (PRD §10), and budgets. Categorizing is
one transaction at a time, which is slow for a real ledger's history until M10's rules.

**Inputs needed from the owner** (PRD §22): whether PRD §10's starting list stands as named in
point 3, and any subcategories wanted at the start.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Phase 1A passes, and M9 is spending categories** (points 1 and 2). Alternatively Phase 1A
  hardening first, or household first.
- **B. A stored list starting from PRD §10,** append-only, one level of subcategories (point 3).
- **C. Categorizations as D-053's model, extracted for both fields,** only on spending (point 4).
- **D. Spending by category in `totals` and `report monthly`** (point 5).
- **E. The slices M9.1 to M9.3,** in that order.
