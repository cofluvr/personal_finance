# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-063 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-064 | M10 plan: categorization rules — Approved with A to H, M10.1 built |

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
| Rule tokens | `rule add` needs the `p1` preview of every change. `r11`, `t9`, `d8`, `c4` and `g2` add rules, keeping digests while none reaches | D-064 |
| Backups | A new folder, on a mounted volume other than a real ledger's and gated as its folder is, holding the ledger, its referenced originals and a manifest of hashes, sizes, versions and a logical digest. Restore never overwrites, and checks every file, integrity, foreign keys, schema and digest first | D-058 |

## Not yet decided

From `shared-contract.md` §6: safe-to-spend details and loan projection assumptions
(Phase 1B), and pairing protocol and snapshot compatibility (Phase 1C). Transfer matching
was decided in D-054, resource benchmarks in D-057, and backup and recovery in D-058.

## D-064 M10 plan: categorization rules — Approved with A to H, M10.1 built

Proposed on 2026-11-10. M10 is the second Phase 1B milestone of D-063 point 2: **categorization
rules**, meeting PRD §10's correction actions "apply a rule to future matches", "apply a rule to
matching historical transactions", "preview affected records" and "undo changes", and its
requirement that "explicit transaction corrections must take precedence over general rules". It
makes categorizing a real ledger's history practical, which D-063 left one transaction at a time.
Builds on D-063's categories and categorizations, and changes none of D-042 to D-063. **No
security control changes,** no dependency is added, and the UI stays read-only. Plan only: nothing
is built until it is approved, and then each slice separately. Acceptance tests, RA1 to RC4, are in
[plan.md](plan.md).

"Rule" alone already means D-033's matching rules (`reconcile/rules.py`, `MatchingRules`, the rules
fingerprint). These are **category rules** everywhere, in names, tables, commands and messages, so
the two never read as one.

```sh
pf category rule preview --db DB --category NAME --description-contains TEXT \
   [--account A] [--type TYPE] [--from DATE]
pf category rule add     --db DB --category NAME --description-contains TEXT \
   [--account A] [--type TYPE] [--from DATE] --preview p1-…
pf category rules        --db DB [--account A]
pf category rule show    --db DB RULE_ID
pf category rule undo    --db DB RULE_ID --revision q1-…
```

**Slices:**

| Slice | Scope |
|---|---|
| M10.1 | Category rules: migration 0021, matching, `preview`, `add`, `rules` and `rule show`, the derived outcome on every write, precedence, and the token versions (points 1 to 7) |
| M10.2 | Undoing a category rule with its `q1` token, and `rule show`'s undo outlook (point 4) |
| M10.3 | Spending by category counting rules' outcomes, their disclosures, the source of a category in `review show` and `review transaction show`, the UI's parity, and the benchmark row (points 8 and 9) |

**Recommendations, each with its alternatives:**

1. **What a rule matches, deterministic and explainable.**
   - **One required test: the effective description contains a text,** both normalized by a fixed
     function: Unicode NFKC, `casefold()`, every run of whitespace made one space, trimmed. The
     effective description is a corrected one where a description correction applies (D-049), else
     the primary source's (D-030), so a rule sees what `transactions` shows. The text is stored as
     typed, with its normalization's version, and code refuses a version it does not know rather
     than reading an old rule a new way. A text that normalizes to nothing is refused.
   - **Optional narrowing:** `--account` (else every account), `--type`, one of D-063's spending
     types (`purchase`, `fee`, `interest`, `refund`), and `--from DATE`, on or after the effective
     transaction date, else the effective posting date, as a month is chosen (D-057). Direction
     follows from the type: only a refund is money in. All given tests must hold.
   - **Deterministic:** a rule's outcome depends only on the rule and the transaction's effective
     values now, never on import order, generated IDs or when the rule was added, so D-045's order
     independence holds. It never reads `MatchingRules` or D-032's similarity, which are candidate
     heuristics tied to the rules fingerprint: changing matching configuration never changes a
     category. **Explainable:** every outcome names the rules that matched, each a sentence such as
     "description contains 'trader joe', any account, purchase, from 2026-01-01".
   - Alternatively **starts-with and exact match too,** each a flag: more precise, but three modes
     where one covers both, and none is needed until a contains test proves too loose (principle
     1). Or **an amount range,** for one merchant charging two kinds of things: left out until the
     owner names a case. Or **regular expressions:** most expressive, least explainable, and a
     pattern a person cannot predict. Or **D-032's normalized merchant:** ties categories to
     matching configuration, and D-032 lists its known misses.

2. **A rule assigns a category only, and only to spending a person has typed.** Types come first
   (D-014), a type is stated by a person only (D-053 point 2), and a description alone never
   establishes one (D-011, D-032). A rule reaches only D-056's spending group, through D-063's
   `spending_transactions`, so a type change or a confirmed transfer takes a transaction out of
   every rule's reach with nothing to disclose: no person's statement is lost. **The cost, stated
   plainly:** on a real ledger rules reach only transactions already classified, so classifying
   stays one transaction at a time. Alternatively **a rule that also states a type,** limited to
   `purchase` and `fee`, never a transfer kind: removes that bottleneck, but breaks D-053's "stated
   by a person only", lets text decide what counts as spending at all, and needs its own precedence
   against classifications and its own `f` token inputs. If the owner wants it, it is better its
   own decision after M10, on type rules, with M10's machinery reused.

3. **Precedence, and disagreement.**
   - **A person's categorization comes first, in every state.** If any active categorization
     reaches a transaction, `applied`, `conflict`, `basis_changed` or `not_spending`, no rule
     applies there. A rule never fills in an outcome a person left unsettled, which would choose
     between statements on the person's behalf. Undoing the person's categorization lets the rules
     apply again, and its `g` token says so (point 6).
   - **Rules that agree apply. Rules that disagree leave the transaction uncategorized,** in a
     state `rule_conflict`, disclosed with the rules' IDs, by D-049's reason: deterministic,
     independent of order, and never choosing between two statements a person made. The person
     settles it by narrowing or undoing a rule, or by categorizing that transaction, which comes
     first.
   - **Disclosed:** `totals` and `report monthly` give the count and amount categorized by rules and
     in `rule_conflict` (point 8). `rule show` gives, per rule, the transactions it categorizes,
     those where it disagrees and with which rules, and those where a person's categorization takes
     precedence.
   - Alternatively **an order stated by the person,** the higher rule winning: no conflicts, but a
     mutable priority over an append-only list needs reordering events and tokens, and a new rule
     can silently change transactions far from its own text. Or **the most specific wins:** no
     agreed measure across text, account, type and date, and hard to explain. Either can be added
     later over the same storage if conflicts prove common.

4. **Historical application derives outcomes, never writes categorizations.**
   - A rule is stored once, append-only, with `made` and `undone` events. Its outcome is **derived**
     into `transaction_rule_category` wherever categories are already rewritten, at the end of
     `write_transfer_effects` and by categorization commands, for every transaction a rule reaches,
     historical or new. No categorization is written, so nothing binds records, and a person's
     statements stay exactly the person's.
   - **"Historical" and "future" are one rule and dates:** a rule applies to every matching
     transaction by default, and `--from DATE` limits it to transactions dated on or after a day.
     "Only future matches" is a rule from today.
   - **Preview before anything is written:** `rule preview` opens the ledger read-only, derives the
     outcome with and without the proposed rule, and lists every transaction whose effective
     category would change, with its ID, date, amount and effective description, escaped as
     D-040, the category before and after, and why (applies, `rule_conflict` with rule IDs, or
     resolved). A person's categorization taking precedence is counted, not listed, since it does
     not change. It prints a `p1` token over the rule's definition and that whole list. `rule add`
     needs it: under one write lock, every account the rule can reach must be current (D-033), the
     list is recomputed, and a token that no longer matches refuses, changing nothing (D-043, M2.1
     qualification 2). An active rule with the same definition is refused.
   - **Undo reverses only what the rule did:** `rule show` gives the undo outlook, the transactions
     whose category undo would change, and a `q1` token over the rule's state and that list. `rule
     undo` checks the accounts are current and the token, appends `undone`, and re-derives. Since
     outcomes are derived, the result equals a ledger in which the rule was never added (D-043): its
     transactions return to uncategorized or to the other rules' outcome, a conflict it caused
     resolves, and no person's categorization changes. Undo never refuses for contradiction, as
     rules constrain no identity (D-049), and the output says when the outcome differs from its
     preview because evidence arrived since.
   - **No superseding in M10:** changing a rule is undo then add, each previewed. Alternatively
     D-048's chains for rules: one step instead of two, but a chain walk and its tokens for an
     action that two previews already make safe.
   - Alternatively **applying a rule writes categorizations,** one per matching transaction, bound
     to its records: reuses M9's code, but new imports then need a hook writing statements on the
     person's behalf, a person's precedence needs a source column on every statement, undo means
     undoing thousands of statements one by one, and every categorized transaction's token changes.

5. **New imports, repeat imports, merges, splits and chains.**
   - **New imports:** an import already ends by rewriting categories, so rules reach new
     transactions on that write, with no hook and no step for the person. A rule is general by
     intent, so unlike a decision (D-048) reaching a record that did not exist when it was made is
     its purpose, and the PRD's. A repeat import of identical bytes changes nothing (D-022), so no
     outcome changes.
   - **Merges and splits:** a rule binds no records, so it has no `basis_changed`. A merge evaluates
     the one transaction on its effective values (D-030's primary source, or a correction), and a
     split evaluates each part. `review confirm` and `review separate` never refuse for a rule's
     outcome, because nothing a person stated is left unsettled, and `totals` discloses the result.
   - **Chains:** only the newest of a categorization chain is active (D-048), so only it takes
     precedence. Rules have no chains (point 4).

6. **Tokens, left out while empty, and the byte-for-byte guarantee.**

   | Token | Adds, while a rule's outcome reaches there | Version |
   |---|---|---|
   | Item | Each transaction's rule outcome: state, category name and the matching rules' IDs | `r10` to `r11` |
   | Transaction | The same, for one transaction | `t8` to `t9` |
   | Decision undo | Rule outcomes of the groups either side, since membership decides the effective description | `d7` to `d8` |
   | Correction undo | Rule outcomes of its transactions with and without it, for every field, since description, dates and an amount's sign all change what a rule reaches | `c3` to `c4` |
   | Categorization undo | The rule outcome its transaction takes once the categorization is undone | `g1` to `g2` |
   | Rule preview, new | The definition and every change the rule would make | `p1` |
   | Rule undo, new | The rule's state and every change undo would make | `q1` |

   `f`, `m` and `o` stay as they are, as M9 left categories out of them: their effect on spending is
   disclosed by `totals`. `p` and `q` are free: `b`, `c`, `d`, `f`, `g`, `k`, `m`, `o`, `r`, `t`,
   `u` and `v` are taken. Every new input is left out while no rule's outcome reaches the
   transaction, so a ledger without rules, or with every rule undone, keeps every digest, and the
   tests pinning `r10`, `t8`, `d7`, `c3` and `g1` move to the new versions with each digest
   unchanged, as M9.2 did. **Proved as CB5 and CC4 were:** the suite's ledgers before M10, kept with
   `--basetemp` under `build/`, read by M9's code and, migrated to 21, by each M10 slice's code,
   running the same per-ledger commands as M9.3 plus `review categorizations` and categorization
   shows, capped at 50 per kind, all identical once versions move. On generated ledgers with rules,
   removing the new lines leaves the reports with rules switched off, and undoing every rule leaves
   them byte for byte as never having had one.

7. **Storage, migration 0021 and the real ledger.**
   - Migration 0021, with M10.1, adds append-only `category_rule` (ID, an optional account, the
     category, the text as typed, its normalization version, an optional type and from date, and
     when it was made) and `category_rule_event`, with update, delete and replace triggers as 0020,
     and the derived `transaction_rule_category` (transaction, state `applied` or `rule_conflict`,
     category, cascading with its transaction). Matching rule IDs are recomputed for display, not
     stored. `transaction_category` is not widened, so M9's derived rows and their code stay as
     they are, and reports read a person's outcome first, then a rule's.
   - The tables are empty when made, so no account goes stale, and no digest, total or report
     changes. Migration is explicit (D-035): a ledger at 20 is refused until `migrate`.
   - **On the real ledger:** the owner runs `pf backup create` to a verified backup, then `pf
     migrate` to version 21. The M5 gate is unchanged and checks the ledger on every open as now.
     Backups and restore cover the new tables with no change, since the manifest's logical digest
     hashes every table, and a restore test keeps rules as CB6 keeps categorizations.
   - **Older migration tests:** 0021 is the newest migration, so `drop_category_tables` in
     `test_decisions.py` drops its tables first, and `tests/unit/test_migrations.py`,
     `test_review_show.py` and `test_backups.py` list them. `category rule` is a new command group
     for the test `Ledger.run` helper.

8. **Reports and explanations, with M10.3.** Spending by category counts a transaction's effective
   category, a person's first and a rule's otherwise, and still adds exactly to D-056's Spending for
   the ledger, one account and each month. Two disclosures, shown only while a rule's outcome
   reaches a transaction: categorized by rules, and `rule_conflict`, each with count and amount.
   `review show` and `review transaction show` say where a category comes from, the
   categorization's ID or the rules' IDs and sentences. The UI's pages follow through the builders,
   with M8's parity tests on ledgers with rules. Nothing else in either report changes.

9. **Performance, and its own benchmark row.** Every write already rewrites every categorized
   account's categories (M9.2), and rules add a test of each active rule against each spending
   transaction not categorized by a person: linear in both, about 50,000 transactions times a few
   hundred rules on the 100,000 shape, on every import, classification and categorization, and
   twice for a preview. That cost is new and cannot be reached by the current shape, which holds no
   rule, so **rules get their own row:** `measure_reconciliation.py --scale --category-rules 300`,
   300 rules over descriptions the shape actually holds, asserting how many transactions they
   categorize, how many conflict and how many a person's categorization takes first, so the shape
   provably reaches the cost. Timed: `totals` and `report monthly` (target below two seconds, as
   D-057), `rule preview`, `rule add`, `rule undo`, one classification and one import of one row
   (no target). **If a rule preview or add costs more than twice an import of one row there, or a
   report misses two seconds, the work stops and is reported** before any optimization, such as
   rewriting only the accounts a write touched (principle 4).

10. **What does not change, and the security boundaries.** No security control changes: W1, the UI,
    the gate and D-037 are untouched. The UI stays read-only, so rules are terminal commands with
    D-043's checks. A rule's text is the owner's label, escaped wherever printed, and `rule
    preview` and `rule show` show descriptions and amounts only of the transactions they list, as
    `transactions` and `review show` already do. No dependency, no network, synthetic fixtures
    only.

**Not in M10:** rules that state a type, amount ranges, starts-with, exact or regular-expression
matching, rule priorities, editing or superseding a rule, rules made or undone from the UI, income
categories, a normalized merchant, rules proposed by local AI or from existing categorizations
(PRD §10), rules reaching only files imported after them, tags, fixed and discretionary classes,
renaming, merging or deleting a category, household attribution and splits (M11), and budgets.

**Inputs needed from the owner** (PRD §22):

- Whether "future matches" means future dates, as point 4's `--from`, or files imported later,
  which point 1 leaves out because it would make outcomes depend on import order.
- About how many rules the owner expects, so that point 9's 300 is a fair shape.
- How much of the real ledger's spending is classified, from the owner's own `pf totals`, to judge
  point 2's bottleneck. Nothing here reads the real ledger.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Rules derive their outcome, and never write categorizations** (point 4). Alternatively a
  rule writes one categorization per match.
- **B. A rule assigns a category only, to spending a person has typed** (point 2). Alternatively a
  rule states `purchase` or `fee` too, then or as its own later decision.
- **C. A rule matches a normalized "description contains", narrowed by account, type and from
  date** (point 1). Alternatively starts-with and exact modes, an amount range, or regular
  expressions.
- **D. A person's categorization first in every state, agreeing rules apply, disagreeing ones leave
  `rule_conflict`, disclosed** (point 3). Alternatively a person-ordered priority, or the most
  specific rule.
- **E. Preview with a `p1` token required by `add`, undo with `q1`, no superseding** (point 4).
  Alternatively D-048's chains for rules.
- **F. Migration 0021, and tokens `r11`, `t9`, `d8`, `c4` and `g2` keeping every digest,** proved by
  a CB5 and CC4 comparison (points 6 and 7).
- **G. Rules' own benchmark row on the 100,000 shape,** with point 9's stopping rule.
- **H. The slices M10.1 to M10.3,** in that order.

**The owner's review, on 2026-11-10.** Decisions A to H approved as written. On the inputs:
"future matches" means files imported later, with every outcome deterministic and independent of
import order. Point 4's derivation gives exactly that, since every import rewrites the rules'
outcomes, so a rule reaches each matching transaction whenever it arrives, and no scope by import
time is built: it would depend on import order. 20 to 50 active rules are expected, so point 9's
300 is a stress test. The owner's real spending is already classified, so B stands. M10.1 to M10.3
approved to build in order, each gated on the full suite and committed locally, with CB5 and CC4
compared as M9 compared.

**How M10.1 was implemented:**

- Migration 0021 adds `category_rule` and `category_rule_event`, append-only by triggers as 0020's
  tables are, and the derived `transaction_rule_category`. Checks refuse a blank text, a version
  below 1, a type outside spending and a date that is not one.
- `reconcile/category_rule_effects.py` matches and derives: each spending transaction's effective
  description, type, account and date, D-063's spending group read from the derived types and
  transfer effects, and whether a person's categorization reaches it. `write_rule_category_effects`
  runs after a person's categories, at the end of `write_transfer_effects` and in every
  categorization command, so every write rewrites the outcomes. With no active rule it deletes
  nothing that exists and reads nothing else.
- `reconcile/category_rules.py` adds a rule under one write lock: every account it can reach is
  current, one account's or every account's, then the category, text and date, then an active rule
  of the same meaning, texts compared normalized, then the `p1` token. An unknown account is the
  CLI's refusal, and a type outside spending argparse's, both exiting with code 2.
- `reports/category_rule_evidence.py` derives the outcome with and without one rule over the
  evidence held now, for the preview and, in M10.2, for undo. A change is a change of state or
  category: which rules disagree does not change a category, so it is not listed. `p1` covers the
  definition by names and every change by its records' document hashes and rows.
- **Tokens:** `r11` and `t9` add, on a transaction a rule's outcome reaches, the matching rules by
  what they say, with the outcome. A rule's ID is immaterial, as every stored ID is. `d8` adds the
  rules a description in scope can match, parsed or corrected, since groups, records, corrections
  and types are already covered. `c4` adds, for any field, the rules its transactions' source or
  corrected descriptions can match and the rules' outcome there now. `g2` adds the outcome its
  transactions would take from rules with no person's categorization. All are left out while
  empty, and tests pinning `r10`, `t8`, `d7`, `c3` and `g1` moved to the new versions with every
  digest unchanged.
- A confirmed transfer leaves a transaction out of every rule's reach through D-063's definition of
  spending. No command reaches that state on spending, since a matched side is unclassified or of a
  transfer kind (D-054), so it is kept as M9 keeps it, untested by a command.
- **Compared as CB5:** the suite's 2,477 ledgers before M10, kept with `--basetemp` under `build/`,
  read by the code at `19ee858` and, migrated to 21, by M10.1's: 51,379 runs, M9.3's list plus
  `category list`, `review categorizations` and categorization shows. 51,344 are identical once
  token versions move, every digest kept. 32 are two ledgers stamped schema 21 to mean newer than
  the code, which reads them as current. 3 are the comparison's own rewriting of a stored
  description holding "t8-", identical compared exactly.
