# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-064 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-063 | M9 plan: spending categories — Approved with A to E, implemented and accepted in M9 |
| D-064 | M10 plan: categorization rules — Approved with A to H, implemented and accepted in M10. Real ledger not yet migrated |
| D-065 | M11 plan: household members, attribution and allocations — Pending, proposed for the owner's review |
| D-066 | Roadmap to a finished backend: M12 to M21 — Pending, proposed for the owner's review |

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
| Categories | Append-only, one level of subcategories, PRD §10's twelve to start. Names exact, never `uncategorized` | D-063 |
| Categorizations | D-053's model through one shared implementation. Spending only: an applied purchase, fee, interest or refund with no transfer confirmed. Otherwise `not_spending`, disclosed | D-063 |
| Spending by category | Under Spending, adding to it exactly, while a categorization reaches a transaction. `g1` undo token, and `r10`, `t8`, `d7`, `c3` keeping digests | D-063 |
| Category rules | Spending whose normalized effective description contains a text, narrowed by account, spending type and first date, takes a category. Derived wherever categories are, from the evidence held now, binding no records, so later imports are reached in any order | D-064 |
| Rule precedence | A person's categorization first, in every state. Agreeing rules apply, disagreeing ones leave `rule_conflict`, disclosed | D-064 |
| Rules in reports | Spending by category counts a person's category, else the rules'. Rules' disclosures show only while a rule's outcome reaches a transaction | D-064 |
| Rule tokens | `rule add` needs the `p1` preview of every change, and `rule undo` the `q1` outlook of every change. `r11`, `t9`, `d8`, `c4` and `g2` add rules, keeping digests while none reaches | D-064 |
| Backups | A new folder, on a mounted volume other than a real ledger's and gated as its folder is, holding the ledger, its referenced originals and a manifest of hashes, sizes, versions and a logical digest. Restore never overwrites, and checks every file, integrity, foreign keys, schema and digest first | D-058 |

## Not yet decided

From `shared-contract.md` §6: safe-to-spend details and loan projection assumptions
(Phase 1B), and pairing protocol and snapshot compatibility (Phase 1C). Transfer matching
was decided in D-054, resource benchmarks in D-057, and backup and recovery in D-058. D-066,
proposed, places the four still open: safe-to-spend in M16, loan projections in M15, snapshot
compatibility in M19 and pairing in M20.

## D-065 M11 plan: household members, attribution and allocations — Pending, proposed for the owner's review

Proposed on 2026-11-10. M11 is the third Phase 1B milestone of D-063 point 2: **household members,
attribution by account and by transaction, and allocations by amount or percentage summing
exactly**, meeting PRD §6's "Household Attribution", §7's "accounts and household members",
"transactions and transaction splits" and "household allocations", and §21's "all transaction
splits reconcile exactly". It gives M12's budgets the "household allowance with personal
allocations" of PRD §12 something to count, in M13 of D-066's proposed sequence. Builds on D-049, D-053, D-056, D-063 and D-064, and
changes none of D-042 to D-064. **No security control changes,** no dependency is added, and the UI
stays read-only. Plan only: nothing is built until it is approved, and then each slice separately.
Acceptance tests, HA1 to HC5, are in [plan.md](plan.md).

"Split" already means records leaving a merged transaction: D-029's automatic splits, D-047's
separations, F8 and D-064 point 5. PRD §6's splits are **allocations** everywhere, in names,
tables, commands and messages, and their pieces are **parts**, so the two never read as one.

```sh
pf household member add   --db DB NAME
pf household members      --db DB
pf household share show   --db DB
pf household share set    --db DB --part NAME=PERCENT --part NAME=PERCENT ... --revision h1-…
pf household share undo   --db DB --revision h1-…
pf household account show --db DB --account A
pf household account set  --db DB --account A (--member NAME | --shared) --revision a1-…
pf household account undo --db DB --account A --revision a1-…
pf review allocate --db DB --account A TRANSACTION_ID --revision t10-… \
   (--member NAME | --shared | --percent NAME=PERCENT ... | --amount NAME=AMOUNT ...) \
   [--supersedes ALLOCATION_ID --supersedes-revision s1-…]
pf review allocations     --db DB [--account A]
pf review allocation show --db DB ALLOCATION_ID
pf review allocation undo --db DB --account A ALLOCATION_ID --revision s1-…
pf report household       --db DB [--account A] [--from YYYY-MM] [--to YYYY-MM] \
   [--member NAME | --shared]
```

**Slices:**

| Slice | Scope |
|---|---|
| M11.1 | Members, the household share and account attribution: migration 0022, the allocation function, `household` commands, tokens `h1` and `a1`, and each transaction's attribution in `review show` and `review transaction show` (points 2 to 4, 7) |
| M11.2 | Allocating one transaction: migration 0023, D-063's stated model extended to a value of several parts, `review allocate`, chains, `s1`, and `r12`, `t10`, `d9`, `c5` (points 1, 5 and 6) |
| M11.3 | `pf report household`: personal, shared and side-by-side views adding exactly to the household's, its UI page with parity, and the benchmark row (points 8 and 9) |

**Recommendations, each with its alternatives:**

1. **An allocation divides one transaction's effective amount among members, and nothing else.**
   - **Type and category stay the transaction's.** A part has no type and no category of its own:
     each part counts in the D-056 group of its transaction, and in spending under its
     transaction's effective category, a person's first, else the rules' (D-063, D-064). So
     spending by category, the rules and their precedence are untouched by M11, and a member's
     spending by category adds exactly to that member's spending, as the household's does today.
     A rule or categorization changing a category moves every part with it and changes no
     allocation. An allocation changes no type, no category, no outcome of a rule and no line of
     `totals` or `report monthly`.
   - **Every transaction can be allocated, whatever its type,** income and transfers included, so
     a member's five groups add to that member's share of net account movement. A confirmed
     transfer from one member's account to another's stays a confirmed transfer, out for one and
     in for the other, never income or spending. Since an allocation is valid on every type, a
     classification, match or one-sided transfer never unsettles one, and `f`, `m`, `o`, `g`, `p`
     and `q` stay as they are.
   - **Stored apart, never read by matching** (D-049). A transaction's allocation statements live in
     their own append-only tables, bind the records of their transaction when made, and apply
     after derivation: `derive()` reads `record_parse` only and its signature is unchanged.
     `ledger_transaction`, source evidence and `derive()` output are byte-identical with and
     without them. A percentage part is stored in basis points, an amount part in signed cents,
     both integers. The cents of a percentage allocation are never stored: one pure function
     computes them from the effective amount wherever they are needed (point 4).
   - Alternatively **parts with their own categories,** as for a receipt holding food and household
     goods: meets a common need, but a part then becomes a target of categorizations and rules,
     with its own precedence, tokens and the question of what a rule matching a transaction does
     to its parts. Better its own later decision, reusing M11's parts. Or **parts with their own
     types,** such as a loan payment's principal and interest (D-056's warning) or a fee within a
     transfer (PRD §9): left with those open requirements, to plan when a real layout shows one.

2. **Members, the household share and account attribution.**
   - **Members** are stored append-only, by name: an integer ID in the order added, a unique name
     compared exactly, shown as typed and escaped as D-040, never `unattributed` or `shared`. No
     rename or removal in M11, so every allocation keeps meaning what it meant, as categories
     (D-063 point 3). A member is the owner's label, as an account name: an initial will do.
   - **The household share** says how `shared` divides: two or more members, each a percentage,
     summing to exactly 100.00. One share is active at a time, applying to every transaction
     attributed `shared`, past and future. Changing it is undo then set, each with the `h1` token,
     and its output says how many transactions and how much moves between members. PRD §6's
     proposed default, 50/50, is what the owner would type: nothing is assumed. A member added later
     is in no share until a new one names them.
   - **Account attribution** is each account's default: one member, or `shared`. One active per
     account. Changing it is undo then set, with the `a1` token, which covers the account's
     attribution and how many transactions and how much it moves. Setting `shared` while no share is
     active is refused.
   - **What PRD §6's three concepts become:** account attribution is the default by account,
     a statement on a transaction is the override, and the share and an allocation's parts are the
     allocation of shared expenses. **Account ownership,** as a fact about who holds an account, is
     not stored in M11: no report needs it until net worth by member, which D-066 places in M15, and storing
     it now would be a second answer to "whose is this account" with nothing reading it
     (principle 1).
   - Alternatively **dated defaults and shares,** each holding from a date, so a change of who
     pays for what never rewrites earlier months: more faithful when a household's arrangement
     changes, but needs non-overlap rules, a date basis and tokens over intervals. Recommended only
     if the owner says the arrangement has changed within the ledger's history (an input below).
     Or **a fixed 50/50 in code:** less schema, but PRD §6 asks for a configurable split.

3. **Precedence: a person's statement on the transaction, then the account's default, then
   `unattributed`.**
   - An `applied` statement on the transaction decides its allocation. Otherwise, if any active
     statement reaches it, in `conflict`, `basis_changed` or `amount_differs`, it is
     **`unattributed`**, disclosed by reason: the account's default never fills in what a person
     left unsettled, by D-064 point 3's reason. Otherwise the account's default applies. An account
     with no default, or `shared` with no active share, leaves its transactions `unattributed`,
     disclosed by reason.
   - `unattributed` is never stored as a member, as `unclassified` and `uncategorized` are not
     (D-053, D-063). In every view it is a column of its own, so members and `unattributed` add to
     the household exactly.
   - A statement is one of: one member, `shared` (by the share active now), parts by percentage, or
     parts by amount. Statements agree when their kind and parts are equal, so `--shared` and
     `--percent A=50 B=50` disagree: the first follows a later change of share and the second does
     not.
   - Alternatively **the account's default under an unsettled statement:** every transaction
     always attributed, but a person's two statements would be overruled by a setting neither
     named. Or **attribution rules by description,** as D-064's category rules: useful for one
     member's subscriptions on a joint card, but its own decision once the owner names the need.

4. **Exact sums in integer cents, rounding deterministically.**
   - **By amount:** the parts are magnitudes in cents, signed by the transaction's direction, and
     must sum exactly to its effective amount (D-049) when stated, or the command refuses. If a
     correction or its undo later changes the effective amount, the statement no longer sums and is
     **`amount_differs`**, leaving the transaction `unattributed`, disclosed, until undone or
     superseded. A percentage allocation follows the effective amount instead.
   - **By percentage, and the share:** each part in basis points, typed with at most two
     decimals, each above zero, summing to exactly 10,000. A third is typed 33.34, 33.33 and 33.33.
     No floating point anywhere (D-003).
   - **One function, `allocate_cents`,** divides a magnitude M by weights w summing to 10,000 by
     largest remainder: each part takes floor(M × wᵢ / 10,000), then the L cents left over, fewer
     than the number of parts, go one each to the parts with the largest remainder
     (M × wᵢ mod 10,000), ties to the member added first. The transaction's sign is applied after,
     so a refund's allocation is exactly the negation of its purchase's, and a full refund nets to
     zero for each member. Every part is within one cent of its exact share, and the parts sum to
     the amount exactly. The result depends only on the amount, the weights and member order,
     never on the order parts were typed, generated IDs or import order.
   - **The cost, stated plainly:** with 50/50, every odd-cent shared transaction gives its cent to
     the first member, at most one cent each. Alternatively **the odd cent alternating,** by month
     or by transaction date: fairer over time, but harder to explain and to check by hand.
     Recommended only if the owner finds the drift material. Or **rational weights** such as
     `--equal`: thirds without typing 33.34, but a second kind of weight with nothing yet needing it.
   - **Proved:** for every transaction, the parts sum to its effective amount, tested over generated
     amounts and weights with Hypothesis, including 1 cent, negative amounts and three or more
     members; and in every report, each row's members and `unattributed` add to the household's.

5. **Statements follow D-053 and D-063's model, extended to a value of several parts,** and
   survive as categorizations do.
   - **The extraction:** `reconcile/stated_fields.py` holds what types and categories share over a
     `StatedField` whose value is one column. An allocation's value is a kind and a set of parts, so
     the shared code compares a canonical value: the kind, then parts sorted by member ID. This is
     the third use, so the extension goes in the shared code rather than a copy (principle 2).
     Every types and categories command's output, refusal and token stays byte for byte as now,
     compared as CB5.
   - **Repeat imports:** identical bytes change nothing (D-022). **New evidence:** no statement
     transfers to a record that did not exist when it was made (D-048). A re-export that merges
     automatically keeps it applied, binding only the old records. The account's default, which
     binds no records, reaches every new import, as a category rule does (D-064 point 5).
   - **Merges and separations:** `review confirm` joining disagreeing statements, and `review
     separate` splitting a statement's records, refuse atomically with
     `LEAVES_ALLOCATION_UNSETTLED`, after the types and categories checks. An automatic split gives
     `basis_changed`, disclosed. Decision undo reports what it leaves unsettled and never refuses for
     it (D-049).
   - **Chains (D-048):** allocating an allocated transaction needs `--supersedes` naming the one
     statement applying there, with its `s1` token. Only the newest of a chain applies, undo steps
     back one link and never refuses for contradiction, and refusing a superseded statement names
     the newest. A transaction in `conflict`, `basis_changed` or `amount_differs` refuses
     superseding: undo one first.
   - **Commands:** D-043's checks under one write lock: the account must be current, then account,
     transaction and `t` token together. A statement changes no membership, so the command rewrites
     the derived allocations without deriving.
   - Alternatively **one allocation per transaction, overwritten:** far less code, but no history,
     no undo and no protection against stale evidence, which D-043 and D-049 require of every
     statement a person makes.

6. **Tokens, left out while empty, and the byte-for-byte guarantee.**

   | Token | Adds, while an allocation statement reaches there | Version | Slice |
   |---|---|---|---|
   | Household share, new | The active share, its parts by member name, and how many transactions and how much it moves | `h1` | M11.1 |
   | Account attribution, new | The account's default, and the transactions and amounts it moves | `a1` | M11.1 |
   | Item | Each transaction's active statements by kind and parts, by member name, with state and bound records | `r11` to `r12` | M11.2 |
   | Transaction | The same, for one transaction | `t9` to `t10` | M11.2 |
   | Decision undo | Statements of the groups either side, by agreement, as `d7` added categorizations | `d8` to `d9` | M11.2 |
   | Correction undo | For an amount, the outcome of statements on its transactions with and without it, since `amount_differs` turns on it | `c4` to `c5` | M11.2 |
   | Allocation undo, new | Its kind, parts, the transactions holding its bound records, and the outcome there with and without it | `s1` | M11.2 |

   **The account's default and the share join no `r`, `t`, `d` or `c` token:** they are the same
   for every transaction of an account, so no decision or correction changes which applies, and
   they bind no record. They join only `h1`, `a1` and the reports. `a`, `h` and `s` are free:
   `b`, `c`, `d`, `f`, `g`, `k`, `m`, `o`, `p`, `q`, `r`, `t`, `u` and `v` are taken. Every new
   input is left out while no statement reaches the transaction, so a ledger without statements
   keeps every digest, and the tests pinning `r11`, `t9`, `d8` and `c4` move to the new versions
   with each digest unchanged, as M9.2 and M10.1 did.

   **`totals` and `report monthly` do not change at all,** with or without members, defaults or
   statements: household views are their own report (point 8). **Proved as CB5 and CC4 were:** the
   suite's ledgers before M11, kept with `--basetemp` under `build/`, read by M10's code at
   `6a0c42f` and, migrated to 22 and then 23, by each M11 slice's code, running M10's per-ledger
   commands plus `household members`, `review allocations` and allocation shows, capped at 50 per
   kind, all identical once versions move. On generated ledgers with members, defaults and
   statements, `totals` and `report monthly` are byte for byte those of the same ledger with the
   household tables emptied, and undoing every statement leaves every `r`, `t`, `d` and `c` digest
   as never having had one.

7. **Storage, migrations 0022 and 0023, and the real ledger.**
   - **Migration 0022, with M11.1:** append-only `household_member`, `household_share` with its
     parts and events, and `account_attribution` with its events, with update, delete and replace
     triggers as 0021. No derived table: the default and the share are resolved when read, so no
     write rewrites a row per transaction (point 9).
   - **Migration 0023, with M11.2:** append-only `allocation_statement`, its parts,
     `allocation_statement_record` and `allocation_statement_event`, mirroring 0020's tables, and a
     derived `transaction_allocation` holding each statement outcome: state, kind and parts,
     cascading with its transaction and rewritten wherever categories are. Two migrations, as
     0019 and 0020 were, so no table waits for a slice not yet approved.
   - The tables are empty when made, so no account goes stale, and no digest, total or report
     changes. Migration is explicit (D-035).
   - **On the real ledger,** once M11 is accepted: the owner runs `pf backup create` to a verified
     backup, then `pf migrate` to version 23, one atomic step per migration. **M10's own migration
     to 21 comes first,** verified on its own, so a problem is traced to one milestone. The M5 gate
     is unchanged and checks the ledger on every open as now. Backups and restore cover the new
     tables with no change, since the manifest's logical digest hashes every table, and the backup
     tests' rich ledger gains members, a share, defaults and statements, compared after restore as
     CB6 and RB3.
   - **Older migration tests:** `drop_category_tables` in `test_decisions.py` drops 0023's and
     0022's tables first, and `tests/unit/test_migrations.py`, `test_review_show.py`'s and
     `test_backups.py`'s `LEDGER_TABLES` and `test_pending_posted_migration.py` list them.
     `household` is a new command group for the test `Ledger.run` helper.

8. **Views, in their own report, with M11.3.** `pf report household` reads the effective
   allocation of every transaction and gives D-056's five groups, Spending by type and spending by
   category:
   - **Side by side,** the default: one column per member, then `unattributed`, then the
     household, each row adding exactly across. The household column equals `totals`' lines for
     the same scope and months, tested.
   - **Personal,** `--member NAME`: that member's parts only, as one column, with personal,
     shared and allocated parts counted apart.
   - **Shared,** `--shared`: transactions allocated to more than one member, whole, with each
     member's part.
   - `--account` and `--from` and `--to` months as `report monthly`, a month chosen as D-057's.
     Disclosures: `unattributed` by reason, statements that do not apply by state, and for the
     scope asked, the share and account defaults in effect.
   - **Its UI page** renders the builder's lines through `reports/report_text.py` and gets M8's
     parity test against the command, with a member's name holding HTML shown as text. A new
     read-only `GET` page under D-062's protections, unchanged: no security control changes.
   - Alternatively **columns added to `totals` and `report monthly`:** one place to look, but every
     existing line and the CC4 guarantee move, and `totals` is already within 0.1s of its two
     second target (point 9).

9. **Performance, and its own benchmark row.** The default and the share are resolved when read,
   so a write rewrites only statements' outcomes, linear in statements, and `totals` and `report
   monthly` read nothing new. `report household` reads every transaction once and runs
   `allocate_cents` on each shared one, but needs no transfer candidates, which `totals` computes.
   That cost is new and the current shape holds no member, so **allocations get their own row:**
   `measure_reconciliation.py --scale --household`, with two members, a 50/50 share, two personal
   accounts and the card and one checking account `shared`, 5,000 statements of every kind, some
   in `conflict` and `amount_differs`, asserting how many transactions each member, `shared` and
   `unattributed` hold, so the shape provably reaches the cost. Timed: `totals` and `report
   monthly` (unchanged, below two seconds), `report household` side by side, `--member` and
   `--shared` (target below two seconds, as D-057), `review allocate`, `review allocation undo`,
   `household account set`, `household share set`, one classification and one import of one row
   (no target). **If `report household` misses two seconds, or an allocation costs more than twice
   an import of one row, the work stops and is reported** before any optimization (principle 4).

10. **What does not change, and the security boundaries.** No security control changes: W1, the
    gate and D-037 are untouched, and the UI gains one read-only page under D-062's protections.
    Allocating stays a terminal command with D-043's checks. A member's name is the owner's label,
    escaped wherever printed, and amounts by member are aggregates as `totals` shows (D-037).
    `review allocation show` prints no amounts or descriptions, as `review correction show`. No
    dependency, no network, synthetic fixtures only.

**Not in M11:** categories or types per part, dated defaults or shares, account ownership and net
worth by member, attribution rules by description, allocations from the UI, who owes whom or
settling up, renaming or removing a member, separate logins or multi-user access (PRD §2, later),
budgets and personal allowances, and members in sync snapshots. D-066 proposes where the later of
these go.

**Inputs needed from the owner** (PRD §22, "household and account assignments"):

- The household's members, by the names or initials to store.
- Each account's default: one member, or `shared`. Nothing here reads the real ledger: the owner
  lists accounts with `pf` themselves.
- The share for `shared`: PRD §6 proposes 50/50.
- Whether the arrangement has changed within the ledger's history, to judge point 2's dated
  alternative.
- About how many transactions the owner expects to allocate by hand, so point 9's 5,000 is fair.
- Whether receipts holding several categories are common, to judge point 1's alternative.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Allocations, never "splits", divide a transaction's effective amount among members only:**
  type and category stay the transaction's, and every type can be allocated (point 1).
  Alternatively parts with their own categories, or types.
- **B. Members append-only, one active household share, one active default per account,** each
  changed by undo then set (point 2). Alternatively dated defaults and shares, or a fixed 50/50.
- **C. A person's applied statement first, then the account's default, then `unattributed`;** an
  unsettled statement leaves `unattributed`, never the default (point 3). Alternatively the default
  under an unsettled statement.
- **D. Basis points and cents, largest remainder with ties to the member added first, the sign
  applied after;** an amount allocation that stops summing is `amount_differs` (point 4).
  Alternatively the odd cent alternating, or rational weights.
- **E. Statements on D-053 and D-063's model, extended in the shared code,** binding records,
  D-048's chains, `s1`, and `review confirm` and `review separate` refusing to leave one unsettled
  (point 5).
- **F. Migrations 0022 and 0023, tokens `h1`, `a1`, `s1`, `r12`, `t10`, `d9` and `c5` keeping
  every digest, and `totals` and `report monthly` unchanged,** proved by a CB5 and CC4 comparison
  (points 6 and 7).
- **G. `pf report household` with side-by-side, personal and shared views, and its UI page**
  (point 8). Alternatively columns in `totals` and `report monthly`.
- **H. Its own benchmark row on the 100,000 shape,** with point 9's stopping rule.
- **I. The slices M11.1 to M11.3,** in that order.

## D-066 Roadmap to a finished backend: M12 to M21 — Pending, proposed for the owner's review

Proposed on 2026-11-10, at the owner's request, after D-065. **A sequence, not a plan:** approving
it approves the order and the definition of done below, and no milestone. Each milestone still gets
its own decision in D-063 to D-065's shape (slices, recommendations with alternatives, inputs,
lettered decisions and acceptance criteria) and the owner's approval before anything is built.
It replaces D-063 point 2's sequence from M12 on, which left out PRD §11's income and recurring
expenses, §17's net worth, §18's remaining UI and Phase 1C, and placed safe-to-spend before the
protected funds it subtracts. No security control changes here: the milestones that would change
one, M17 and M20, say so and need their own approval as security changes.

**What "the backend is finished" means.** Every **must** of PRD-backend through Phase 1B, and the
backend's half of Phase 1C: snapshots and their secure sync, by shared-contract §3 to §5. Every box
of PRD §21 checked by a named test. Every item of shared-contract §6 recorded as a decision. Each
phase meeting shared-contract §10's definition of done, and point F passed on a real file of each
layout. **Not included:** PRD §3's "Later, subject to approval" items (institution connections,
XLSX, receipt images, local AI, cloud hosting, multi-user access), anything behind shared-contract
§7's approval gates, and the iOS application itself.

**The sequence:**

| Milestone | Scope | PRD | Needs first | Owner's inputs (PRD §22) |
|---|---|---|---|---|
| M11 | Household members, attribution, allocations (D-065) | §6, §7 | M9, M10 | Household and account assignments |
| M12 | Income and recurring obligations: confirmed salary sources and cadence, expected against actual deposits, three-paycheck months, side-income labels, recurring expenses proposed from history and confirmed by a person, fixed and discretionary | §10, §11 | M9, M11 | Salary accounts and cadence, side-income labels |
| M13 | Budgets and spending allowances: calendar-month targets, a household allowance with personal allocations, optional category allowances, fixed apart from discretionary, actual against target, revised daily and weekly allowances, pace, no rollover | §12 | M11, M12 | Monthly targets and personal allocations |
| M14 | Goals, reserves and the tax reserve: goals and fund allocations never allocated twice, the emergency fund, annual and irregular reserves consumed once by their purchase, the tax reserve on labelled income | §13, §16 | M12, M13 | Initial goals, emergency minimum, tax reserve percentage, house against debt |
| M15 | Balances, net worth and loans: net worth from observed balances with valuation dates, loan subaccounts counted once, retirement and contribution history, graduated loan schedules, actual against schedule, payoff orders, projections labelled as such | §13, §14, §17 | M4, M11, M14 | Graduated-loan documents |
| M16 | Safe-to-spend and the cash-flow constraint: protected funds in PRD §12's order, near-term liquidity apart from budget capacity, the limiting constraint shown, provisional labels | §12 | M12 to M15 | Checking buffer |
| M17 | The local UI completed: dashboard, accounts and members, budgets, goals and settings sections, the required visuals, CSV export, and decisions and planning inputs from the browser | §18 | M16 | Which writes the browser may make |
| M18 | Financial scenarios: a baseline and named alternatives, dated inputs entered in the UI, side-by-side comparison, promotion only on confirmation, actual history never altered | §15 | M16, M17 | None beyond earlier milestones |
| M19 | Snapshots: versioned, from one consistent state, holding shared-contract §3's contents and none of its exclusions, with a compatibility policy | Contract §3, §4 | M16, M18 | Transaction window, 90 days proposed |
| M20 | Pairing and local-network sync: explicit sync mode, pairing before access, authenticated encryption, atomic install with acknowledgement, revocation, read-only from the phone | §19, contract §5 | M19 | The phone, and the network it syncs on |
| M21 | Backend acceptance: point F on every layout, PRD §21 closed by named tests, D-025 decided, readiness and recovery documents current, shared-contract §10 checked per phase | §19, §21 | M11 to M20 | Point F runs with the owner |

**Where §21's open boxes and shared-contract §6's open decisions close:**

| Item | Milestone |
|---|---|
| All transaction splits reconcile exactly | M11 |
| Third paychecks do not increase normal spending targets | M12, held by M13 |
| Annual reservations and purchases are not double-counted | M14 |
| Goal allocations cannot silently exceed available funds | M14 |
| Graduated payments follow the configured schedule | M15 |
| Backups restore records, rules, corrections, and goals | Goals in M14. The rest hold now (D-063 point 1, D-064) |
| Safe-to-spend calculation details | M16 |
| Loan projection assumptions | M15 |
| Snapshot compatibility policy | M19 |
| Pairing protocol | M20 |

**Recommendations, each with its alternatives:**

1. **Income and obligations before budgets.** PRD §12's targets must not rise in a three-paycheck
   month, and the cash-flow constraint needs the next paycheck and upcoming obligations, so M12
   comes before M13. Alternatively **D-063's order, budgets first:** targets typed by hand sooner,
   but the third-paycheck rule and the fixed and discretionary split would then be retrofitted.
2. **Safe-to-spend last of the planning milestones.** Its protected funds are the tax reserve,
   bills and minimum debt payments, annual reserves, the checking buffer, emergency-fund restoration
   and goals, which M12, M14 and M15 make. M13 gives the budget's own allowances and pace without
   them, labelled as budget pace, never as safe to spend. Alternatively **a provisional safe-to-spend
   in M13,** labelled provisional as PRD §12 allows: a number sooner, but one that would change
   meaning milestone by milestone.
3. **One planning layer, apart from the ledger.** Targets, allocations, reserves, goals, schedules
   and scenarios are stored apart, append-only with undo, and never change a transaction, a
   category or an actual total. Reports keep actual, projected, reserved and allocated values
   distinct and labelled (shared-contract §4). The shared model is extracted at its second use, M14
   (principle 2), not designed ahead in M13.
4. **Proposals a person confirms, never applied unconfirmed.** Salary cadence and recurring
   expenses in M12 are deterministic proposals from history, each confirmed or dismissed by a
   person before anything relies on it (PRD §11), with D-043's checks. No model, no network:
   local AI stays a later, approved item. Alternatively **manual entry only:** simpler, but PRD §11
   asks for inference and the owner's history would make it laborious.
5. **The UI's writes as one security decision, before scenarios.** M8 is read-only by the owner's
   choice, and PRD §15 requires scenario input in the UI. M17 revives M8.4's criteria, UD1 to UD4,
   for every write the browser makes, as one security change for the owner's approval. Scenarios
   follow in M18 on that footing. Alternatively **scenarios entered in the terminal first,** with
   the UI read-only for longer: no security change until M18, but against PRD §15's wording.
6. **Snapshots before sync, and sync as a security change.** M19 writes a snapshot file and tests
   its contents, consistency and exclusions with no network. M20 adds pairing and a listener that
   runs only in an explicit sync mode, with shared-contract §7's proposal written out: data leaving
   the Mac, credentials, scope, failure and revocation, and the local-only fallback. That fallback is
   M19's file, carried to the phone by the owner. Alternatively **the file alone for the first
   release:** no listener beyond loopback at all, far less to secure, but Phase 1C names
   local-network sync.
7. **Phase 1C sooner, if the phone matters more than planning breadth.** M19 and M20 need only
   M16's numbers to be worth showing, so they could follow M16, ahead of M17 and M18, with
   scenarios added to snapshots later. Not recommended by default: a snapshot without scenarios
   would need its schema bumped once they arrive.
8. **Performance at each milestone,** as M10 and M11: every new report on the 100,000 shape below
   two seconds, its own benchmark row when it adds a cost the shape cannot reach, and the stopping
   rule before any optimization. `totals` sits at 1.9s (D-064), so a milestone that adds to it
   reports the margin, and the owner decides whether `totals`' candidate search should move out of
   it before M17's dashboard reads it.

**Small items placed where first needed:** a normalized merchant in M12, if recurring detection
needs one beyond D-064's normalization. Tags in M17, with search. Income categories in M12. Fees
apart from transfers and loan principal and interest in M15, where loan schedules need them.

**Inputs needed from the owner:** a delivery deadline, if any (PRD §22), and whether the phone
should come sooner (point 7). Each milestone's own inputs are in the table and are asked for again
when it is planned.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. The sequence M12 to M21,** replacing D-063 point 2 from M12 on. Alternatively D-063's
  order, budgets before income (point 1).
- **B. "Finished" as defined above:** Phase 1B and the backend's half of Phase 1C, PRD §21 and
  shared-contract §6 closed, approval-gated items excluded. Alternatively finished at Phase 1B,
  with Phase 1C a project of its own.
- **C. Safe-to-spend in M16, after every protected fund exists** (point 2). Alternatively a
  provisional figure in M13.
- **D. Browser writes as one security decision in M17, before scenarios** (point 5).
  Alternatively scenarios in the terminal first.
- **E. Sync as M19's file, then M20's explicit sync mode** (point 6). Alternatively the file alone,
  or Phase 1C after M16 (point 7).
