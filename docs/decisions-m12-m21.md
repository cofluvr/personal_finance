# Decisions D-067 to D-077: M12 to M21

Proposed on 2026-11-10, and **approved by the owner the same day, as written,** with D-065 and
D-066. That includes the security changes of M17 (D-073) and M20 (D-076), and `segno` as M20's
dependency. **Plans only:** nothing here is built yet. Each slice is built in order and stops for the
owner's review, as D-063 to D-065. The owner implements these
milestones. This document gives each one the full shape of D-065: commands, slices, recommendations
with their alternatives, schema, tokens, byte-for-byte parity, performance, security, inputs,
lettered decisions and acceptance criteria.

**Assumptions, both met on 2026-11-10.** These decisions rest on the following, and each one says
where an assumption matters:

- D-065 approved as recommended, with migrations 0022 and 0023, tokens `h1`, `a1`, `s1`, `r12`,
  `t10`, `d9` and `c5`.
- D-066 approved as recommended, A to E, in that order.

If M11 changes, the migration numbers, the token versions and the criteria that name members shift
with it. Nothing else does.

| Decision | Milestone | Status |
|---|---|---|
| D-067 | Cross-milestone guardrails for M12 to M21 | Approved |
| D-068 | M12 Income and recurring obligations | Approved |
| D-069 | M13 Budgets and spending allowances | Approved |
| D-070 | M14 Goals, reserves and the tax reserve | Approved |
| D-071 | M15 Net worth and loans | Approved |
| D-072 | M16 Safe-to-spend and the cash-flow constraint | Approved |
| D-073 | M17 The local UI completed, with browser writes (security change) | Approved |
| D-074 | M18 Financial scenarios | Approved |
| D-075 | M19 Snapshots | Approved |
| D-076 | M20 Pairing and local-network sync (security change) | Approved |
| D-077 | M21 Backend acceptance, stress testing and the security audit | Approved |

D-067 holds the guardrails every later milestone cites, so the milestones run D-068 to D-077. Each
milestone's criteria are added to [plan.md](plan.md) when it starts, and each decision's full text
moves to [decisions-d001-d052.md](decisions-d001-d052.md) once its milestone is accepted, by the
"Keeping these docs small" rules.

---

## D-067 Cross-milestone guardrails for M12 to M21 — Approved

Rules every milestone from M12 on follows, written once so the milestone decisions only cite them.
None of them changes D-042 to D-066. Each one extends a rule that already holds.

### G1. The planning layer, apart from the ledger

D-066 point 3, made concrete.

- **Planning tables never write ledger tables.** Income sources, obligations, budgets, funds, loan
  terms, settings, scenarios, snapshots and devices are kept in their own tables.
  - No planning command inserts into, updates or deletes from `ledger_transaction`, source
    evidence, decisions, corrections, classifications, transfers, categorizations, rules,
    allocations or observations.
  - A test helper, `evidence_digest`, hashes every pre-M12 table in canonical order. Every planning
    write must leave it unchanged. This is the planning layer's "byte-identical evidence" check,
    and the analogue of F2's and CB5's source-evidence checks.
- **Two exceptions, both statements on a transaction:** fund consumption (D-070) and loan payment
  breakdowns (D-071). Each binds the records of its transaction, as a categorization does, and
  follows D-063's stated model. They live in their own tables, so they too leave `evidence_digest`
  unchanged.
- **Actual, projected, reserved and allocated values stay distinct** (shared-contract §4).
  - Every report line that is not an actual total says which of the other three it is, in its
    label.
  - No line adds values of two kinds without saying so.
  - A test parses every new report's labels and fails on an unlabelled planning figure.

### G2. Planning entries: one model, append-only

Every planning object a person states (an income source, an obligation, a budget plan, a fund, a
fund assignment, loan terms, a setting, a liquidity designation, a scenario and its inputs) follows
the same storage pattern. Balance observations (0016) and category rules (0021) already use it:

| Part | Holds | Mutability |
|---|---|---|
| `<entry>` | The definition: an ID (TEXT, UUID4 as now), kind, the fields that do not change over time, and `created_at` | Append-only: no-update, no-delete and no-replace triggers, each with a control insert that succeeds |
| `<entry>_terms` (where values change over time) | Dated values: `effective_from` (a date or month), and the amounts, cadence or rate | Append-only. A later `effective_from` takes over from that date. Past months are never rewritten (G7) |
| `<entry>_event` | `made`, `undone`, and `superseded_by` where chains apply. Integer ID, `UNIQUE (entry_id, event)` | Append-only, the same three triggers |
| `<entry>_outcome` (derived, only where an entry reaches transactions) | The entry's derived outcome per transaction | Rewritten inside every write that changes its inputs, cascading with its transaction, as `transaction_rule_category` |

- **Changing an entry** is a new terms row (for dated values), or undo then add, or a supersession
  (G4). No entry is edited in place.
- **Terms rows and their effective dates.** Each change gets a new terms row with an
  `effective_from` date. Terms rows are never undone one by one: undoing the entry undoes all of
  them. A terms row whose `effective_from` lies in a closed month is refused, unless D-069 point 6's
  correction flag is given.
- **Extraction schedule (principle 2).** The shared helper for definition, events and triggers is
  extracted at its second use, which is M12.2's obligations after M12.1's income sources.
  `planning/entries.py` holds it. M12.1 writes income sources directly.

### G3. Concurrency: D-043 for every write, from any channel

"Zero-trust" here means that no caller is believed. Every write proves itself against the current
state under the write lock:

1. Open through the gate (D-058). A real ledger is checked on every open.
2. `BEGIN IMMEDIATE`, with the 5-second busy wait. `database_busy` explains what to do and leaves
   nothing partial (as now).
3. Check that every account the write can reach is current. Never reconcile on the person's behalf
   (D-043, qualification 2).
4. Recompute the token over the evidence the person was shown, and compare it with
   `hmac.compare_digest`. On mismatch, refuse and change nothing.
5. Validate the inputs, then refuse on any rule, before any insert.
6. Insert the entry and its `made` event, and rewrite the derived outcomes the write changes.
7. Commit. One transaction per command. An error rolls everything back.

Read commands open the ledger read-only (`mode=ro`) and write nothing. Every new report adds a test
that its logical digest is unchanged.

- **The browser (M17) and the sync listener (M20) call these same functions.** No channel has its
  own write path, its own checks or a way to skip step 3 or 4.
- **Tests for every new write:**
  - a stale-token refusal for each input the token covers;
  - a race test, in which a second connection commits between showing and writing, and the write
    refuses;
  - an atomicity test, in which a fault is injected after the first insert and the logical digest
    is unchanged afterwards.

### G4. Chains (D-048) for planning entries

Some entries carry history that a person may want to step back through: income source terms,
obligation terms, budget plans, fund terms and loan terms. These supersede by D-048's rule:

- Superseding names the one entry it replaces, with that entry's token.
- Only the newest entry in a chain applies.
- Undo steps back one link and never refuses for contradiction.
- A superseded entry is refused, and the refusal names the newest one.

Some entries do not chain:

- **Settings, liquidity designations and account links** are undo-then-set, as M11's defaults.
- **Fund assignments** are undo-then-set too. They are amounts, not definitions, so a chain adds
  nothing.

Statements on transactions (fund consumption, loan breakdowns and tags) follow D-063's stated model
whole: they bind records, agree or conflict, report `basis_changed`, and `review confirm` and
`review separate` refuse to leave one unsettled.

### G5. Tokens: a two-letter kind from M12

After M11, the free single letters are `e`, `i`, `j`, `l`, `n`, `w`, `x`, `y` and `z`, nine of them.
M12 to M20 need about fifteen new kinds. **Recommendation:** every new kind from M12 on takes a
two-letter prefix, and the existing single letters keep theirs. The format is otherwise unchanged.

- The parser accepts one or two lowercase letters, then the version digits, then `-` and the digest.
- A single letter followed by a digit can never read as a two-letter kind, so `t10-…` and `tg1-…`
  never collide.
- A test pins the full registry below, and fails on a reused or unregistered kind.

| Kind | Covers | First version | Milestone |
|---|---|---|---|
| `in` | Income source: add (over the proposal or definition shown), supersede, undo | `in1` | M12.1 |
| `ob` | Recurring obligation: add, supersede, undo, dismiss a proposal | `ob1` | M12.2 |
| `st` | A ledger setting (household timezone, checking buffer) | `st1` | M13.1 |
| `bp` | Budget plan: set, supersede, undo | `bp1` | M13.1 |
| `fu` | Fund (goal, emergency, reserve, tax): add, supersede, undo, priority order | `fu1` | M14.1 |
| `fa` | Fund assignment: assign or release, over the account's assignable amount | `fa1` | M14.1 |
| `fc` | Fund consumption statement: undo | `fc1` | M14.2 |
| `al` | Account link (subaccount to aggregate): set, undo | `al1` | M15.1 |
| `lt` | Loan terms (rates, payment schedule, due day): add, supersede, undo | `lt1` | M15.2 |
| `lb` | Loan payment breakdown statement: undo | `lb1` | M15.3 |
| `lq` | Liquidity designation of an account: set, undo | `lq1` | M16.1 |
| `tg` | Tag statement: undo | `tg1` | M17.3 |
| `sc` | Scenario and its inputs: add, undo | `sc1` | M18.1 |
| `sp` | Scenario promotion, over the scenario and every baseline entry it replaces | `sp1` | M18.3 |
| `dv` | Paired device: revoke | `dv1` | M20.1 |

- **The operation is part of each token's hashed input** (`add`, `supersede`, `undo` and so on), so
  a token shown for one operation never authorizes another. D-064 used two letters, `p` and `q`, for
  this. The tag makes a second letter unnecessary.
- **Shared tokens move only where a statement on a transaction is added:**
  - M14.2's fund consumption bumps `r`, `t`, `d` and `c` once. After M11 these are `r13`, `t11`,
    `d10` and `c6`.
  - M15.3's breakdown bumps them once more.
  - M17.3's tags bump them once more.
  - Each new input is left out of a token while nothing reaches its transaction, so every digest is
    kept on a ledger with no such statement, as M9.2 and M10.1 did.
- **Every other planning entry joins no `r`, `t`, `d` or `c` token.** Such an entry binds no records
  and no decision changes which one applies, as M11's default.

### G6. Byte-for-byte parity, every milestone

This is the CB5 and CC4 method, made a standing rule.

1. **Before each slice,** keep the suite's ledgers with `--basetemp` under `build/`. Then run the
   previous slice's commit over them and capture every existing command's output, capped at 50
   per-ID shows per kind, as M9.3 did.
2. **After the slice,** migrate copies and run the new code. Every command the slice does not name
   must be byte for byte the same. A token's version may move only where G5 says it does, and its
   digest must not move.
3. **Generated ledgers with the new tables populated:** `totals`, `report monthly` and
   `report household` must be byte for byte the same as on the same ledger with the planning tables
   emptied. The only exception is a milestone that names an intended change: M15.3's breakdown lines
   are the one planned in M12 to M21.
4. **Undo restores parity:** after every new statement is undone, every `r`, `t`, `d` and `c`
   digest is as if the statement had never been made.

Each decision lists the commands its slices may change. Every other command is held by this rule.

### G7. Time: an explicit "as of", and the household's timezone

M13 to M20 need "today": pace, allowances, the next paycheck, due dates and snapshot cutoffs.

- **A setting, `household_timezone`,** an IANA name read with `zoneinfo`, set with `pf setting set`
  (D-069). With no setting, every command that needs today refuses and names the command to run. No
  zone is assumed.
- **Every planning computation takes `as_of` as an argument.** Only the CLI reads the clock, by
  converting the current UTC time into the household's zone. Every planning command takes
  `--as-of YYYY-MM-DD`. Tests always pass it, so no test depends on the clock. A test fails if a
  planning module calls `date.today`, `datetime.now` or `time.time`.
- **Months are calendar months in the household's zone.** A "closed month" is any month before
  `as_of`'s month.
- **A closed month's plan is never rewritten.** Every dated value is chosen by
  `effective_from <= month`, so later terms never change an earlier month's figures.

### G8. Money, rates and rounding

D-003 and D-065 point 4 hold everywhere: integer cents, and percentages in basis points. Floating
point is refused, and a test parses every planning module for `float` and fails on it.

Rates in loan math (D-071) use `decimal.Decimal`, which PRD §7 allows, in a local context with 28
digits:

- A rate is stored as an integer in millionths of a percent, so 6.875% is `6875000`.
- Each result is quantized to cents once per period with `ROUND_HALF_EVEN`, stated in the report.

Every division of cents into allowances or reservations rounds toward protection:

| Figure | Rounds |
|---|---|
| A spendable amount (allowance, surplus) | Down |
| A required amount (reservation, monthly need) | Up |

`allocate_cents` (D-065) is reused wherever an amount divides among members.

### G9. Performance: thresholds and the stopping rule

All figures are on the 100,000-transaction shape (D-057), on the same machine, with nothing else
running (D-064's lesson). Targets are provisional and are not test assertions (D-034).

| Operation | Target |
|---|---|
| Any report or page, including every new one | Below 2.0s |
| `pf dashboard` and `pf safe-to-spend` (M16) | Below 1.0s each. The dashboard page renders both below 2.0s |
| Any planning write (add, supersede, undo, set) | Below 2.0s, and at most 2× an import of one row |
| An import of one row, with every derived planning outcome | At most 0.5s above M11's figure for the same row |
| Proposals (income, obligations) over 60 months | Below 2.0s |
| Scenario recalculation, 24-month horizon | Below 2.0s. 120 months below 5.0s |
| Snapshot generation, 90-day window | Below 5.0s, holding a read transaction. File below 5 MB |
| Sync, server-side time for pairing and for one delivery on loopback | Below 1.0s and 2.0s |

- **Each milestone adds its own benchmark row,** in the style of `--household`. The row's shape
  asserts the counts that prove it reaches the cost it claims to measure.
- **Stopping rule (D-064 point 9).** If a target is missed, the work stops and the cost behind it
  is reported, before any optimization.
- **`totals` is at 1.9s.** No milestone adds to `totals`, apart from M15.3's breakdown lines, which
  read a derived table. The dashboard (M16, M17) does not call `totals`, so it never pays for the
  transfer candidate search (D-072 point 7).

### G10. Backups, migrations and the real ledger

- **New tables are covered without any change.** The backup manifest's logical digest hashes every
  table. Each milestone adds its entries to the backup tests' rich ledger and compares after restore,
  as CB6, RB3 and HB5 do.
- **Every new migration needs the following** (from the handoff's "A new migration"):
  - It works on a populated ledger, synthetic and real.
  - Its tables are empty, no account goes stale, and no digest, total or report changes.
  - It is atomic on failure, and a ledger at the previous version is refused until `pf migrate`.
  - Older migration tests' set-back helpers drop its tables.
  - `tests/unit/test_migrations.py`, `LEDGER_TABLES` in `test_review_show.py` and in
    `test_backups.py`, and `test_pending_posted_migration.py` list its tables.
- **Real ledger.** After each milestone is accepted, the owner takes a verified `pf backup create`,
  then runs `pf migrate` across that milestone's versions only, so a problem is traced to one
  milestone. Migrations go one milestone at a time, never two at once.

**The migration map** (numbers are given at build time, in order. A cut slice frees its number for
the next):

| Migration | Slice | Tables |
|---|---|---|
| 0022, 0023 | M11.1, M11.2 | D-065 |
| 0024 | M12.1 | `income_source`, `income_source_terms`, `income_source_event`, derived `transaction_income_source` |
| 0025 | M12.2 | `recurring_obligation`, `recurring_obligation_terms`, `recurring_obligation_event`, `obligation_proposal_dismissal`, derived `transaction_obligation` |
| 0026 | M13.1 | `ledger_setting_key` (seeded), `ledger_setting`, `ledger_setting_event`, `budget_plan`, `budget_plan_member_part`, `budget_plan_category`, `budget_plan_event` |
| 0027 | M14.1 | `fund`, `fund_terms`, `fund_event`, `fund_assignment`, `fund_assignment_event`, `fund_priority`, `fund_priority_event` |
| 0028 | M14.2 | `fund_consumption`, `fund_consumption_record`, `fund_consumption_event`, derived `transaction_fund_consumption`, `tax_reserve_release` with events |
| 0029 | M15.1 | `account_link`, `account_link_event` |
| 0030 | M15.2 | `loan_terms`, `loan_rate_period`, `loan_payment_period`, `loan_terms_event`, `payoff_plan`, `payoff_plan_event` |
| 0031 | M15.3 | `loan_payment_breakdown`, `loan_payment_breakdown_record`, `loan_payment_breakdown_event`, derived `transaction_loan_breakdown` |
| 0032 | M16.1 | `account_liquidity`, `account_liquidity_event`, `obligation_coverage`, `obligation_coverage_event`, `fund_restoration` and its events. Seeds the `checking_buffer_cents` setting key |
| 0033 | M17.3 | `tag`, `tag_statement`, `tag_statement_record`, `tag_statement_event`, derived `transaction_tag` |
| 0034 | M18.1 | `scenario`, `scenario_event`, `scenario_input`, `scenario_input_event`, `scenario_promotion`, `scenario_promotion_entry` |
| 0035 | M19.2 | `snapshot_record` |
| 0036 | M20.1 | `paired_device`, `paired_device_event`, `pairing_window`, `sync_delivery` |

### G11. Security boundaries

| Milestone | Security change | Needs |
|---|---|---|
| M12 to M16, M18 | None | Each milestone's own approval |
| M17 | Browser `POST` writes: M8.4's UD1 to UD4 revived | Approval as a security change (D-066 point 5) |
| M19 | A new kind of file leaves the ledger folder | Gated as a backup destination is (D-072 point 5). No network. Not a control change, but stated |
| M20 | A listener beyond loopback, `ssl`, one new subprocess (`/usr/bin/openssl`) and one new dependency (`segno`, for the pairing QR code), each a change to W1 | Approval as a security change, with shared-contract §7's proposal written out, and the dependency approved under D-020 |
| M21 | D-025 decided | The owner's decision |

D-037 holds everywhere: no logging, and the safe CLI boundary. Every new name a person types (a
source, obligation, fund, scenario, tag or device) is escaped as D-040 wherever it is printed or
rendered. Every new page is read-only until M17, under D-062's protections.

### G12. Testing for review, per slice

The handoff's rules are unchanged: about 20 to 25 targeted breaks per slice, narrow files first,
`-x`, a fresh `PYTHONPYCACHEPREFIX` for each break, and an unbroken control run. Every planning
slice aims its breaks at:

- refusals;
- rounding direction (G8);
- `effective_from` selection (G7);
- token inputs, one break per input;
- the no-double-count invariants named in each decision;
- `evidence_digest` (G1).

### G13. Module layout (a recommendation, not a rule)

| Package | Holds |
|---|---|
| `personal_finance/planning/` | `entries.py` (G2, from M12.2), `calendar.py` (G7: zone, months, days remaining), `schedules.py` (occurrence generation shared by income, obligations, reserves and loans, extracted at M12.2), `income.py`, `obligations.py`, `budgets.py`, `funds.py`, `net_worth.py`, `loans.py`, `safe_to_spend.py`, `scenarios.py` |
| `reports/` | Each new report's builder and its evidence and tokens, as now. `report_text.py` builds the lines the CLI prints and the UI renders (D-062) |
| `snapshot/` | `builder.py`, `canonical_json.py`, `validate.py` |
| `sync/` | `identity.py`, `pairing.py`, `server.py`. W1 allows network imports in `sync/server.py` alone, from M20 |

---

## D-068 M12 plan: income and recurring obligations — Approved

M12 meets PRD §11 and §10's fixed and discretionary split, and closes PRD §21's "Third paychecks do
not increase normal spending targets" on the income side. M13 holds the rule on the budget side.

What it adds:

- **Income sources:** confirmed salary and side income, with a cadence and an expected take-home
  amount.
- **Expected against actual deposits,** with the changes it finds flagged.
- **Recurring obligations,** proposed from history and confirmed by a person, each marked fixed or
  discretionary.

It builds on D-053, D-056 and D-064, and on D-065's members, and changes none of them.
**No security control changes.** No `r`, `t`, `d` or `c` token moves (point 7).

```sh
pf income proposals      --db DB [--account A] [--as-of DATE]
pf income add            --db DB --account A --name NAME --kind (salary|side) \
   --cadence (weekly|biweekly|semimonthly:D1,D2|monthly:D) --anchor DATE --amount AMOUNT \
   --match TEXT [--tolerance-days N] [--amount-tolerance AMOUNT] [--member NAME] \
   [--tax-eligible] [--from-proposal PROPOSAL_KEY] --revision in1-…
pf income terms          --db DB SOURCE_ID --effective-from DATE --amount AMOUNT \
   [--cadence … --anchor DATE] --revision in1-…
pf income sources        --db DB [--account A]
pf income source show    --db DB SOURCE_ID [--as-of DATE]
pf income undo           --db DB SOURCE_ID --revision in1-…
pf obligation proposals  --db DB [--account A] [--as-of DATE]
pf obligation add        --db DB --account A --name NAME \
   --cadence (weekly|biweekly|monthly:D|quarterly:D|annual:MM-DD|every:N-months:D) \
   --anchor DATE (--amount AMOUNT | --range LOW..HIGH) --class (fixed|discretionary) \
   --match TEXT [--category NAME] [--from-proposal PROPOSAL_KEY] --revision ob1-…
pf obligation terms      --db DB OBLIGATION_ID --effective-from DATE (--amount … | --range …) \
   [--cadence … --anchor DATE] [--class …] --revision ob1-…
pf obligation dismiss    --db DB PROPOSAL_KEY --revision ob1-…
pf obligations           --db DB [--account A] [--as-of DATE]
pf obligation show       --db DB OBLIGATION_ID [--as-of DATE]
pf obligation undo       --db DB OBLIGATION_ID --revision ob1-…
pf report income         --db DB [--from YYYY-MM] [--to YYYY-MM] [--as-of DATE]
```

**Slices:**

| Slice | Scope |
|---|---|
| M12.1 | Income sources: migration 0024, schedules, proposals, add, terms, undo, expected against actual, `in1` (points 1 to 4) |
| M12.2 | Recurring obligations: migration 0025, `planning/entries.py` and `planning/schedules.py` extracted, proposals, dismissal, fixed and discretionary, `ob1` (points 5 and 6) |
| M12.3 | `pf report income`: baseline, extra and side income by month, obligations due and paid, its UI page, the benchmark row (points 3, 8 and 9) |

**Recommendations, each with its alternatives:**

1. **An income source is a confirmed schedule plus a matcher, and a deposit counts only once it is
   `income`.**
   - **What a source stores:**
     - the account it lands in;
     - a name, and a kind: `salary` or `side`;
     - a cadence and an anchor date, one real pay date;
     - the expected take-home amount;
     - a matcher: D-064's normalized "description contains" text;
     - a date tolerance, ±3 days by default, which can be set from 0 to 7 at add time;
     - an amount tolerance, 0 by default;
     - optionally a member, with M11, used by M13's personal view;
     - a `tax_eligible` flag, read by M14.
   - **A deposit is reached by a source** only when all of these hold:
     - it is in the source's account;
     - it is money in;
     - its applied type is `income` (D-056);
     - its normalized effective description contains the source's text.

     Unclassified deposits that would match are listed as "possible paychecks, unclassified" and are
     never counted. This keeps D-056's income the one definition of income.
   - **Two sources reaching one deposit** give `source_conflict` on both, disclosed, as D-064's
     `rule_conflict`. The deposit counts toward neither until a source's matcher is narrowed by a new
     terms row or a supersession.
   - **Derived on every write,** as category rules are: `transaction_income_source` holds deposit,
     source, occurrence and state. It is rewritten wherever categories are, binds no records, and so
     reaches later imports in any order.
   - Alternatively:
     - **Sources that also classify the deposit as `income`:** less to do by hand, but this is
       "rules that state a type", which D-064 deliberately left out.
     - **A person's per-deposit assignment statement:** exact, but it bumps `r`, `t`, `d` and `c`
       for a case that narrowing the matcher already covers. Revisit if the owner finds deposits
       that no text separates.

2. **Schedules: nominal dates, generated deterministically.**
   - `planning/schedules.py` generates a source's **nominal pay dates**, as follows:

     | Cadence | Nominal dates |
     |---|---|
     | Weekly and biweekly | `anchor + k × 7` or `14` days, for every whole k |
     | Semimonthly | Days D1 and D2 of each month |
     | Monthly | Day D of each month |
     | Quarterly, annual and every N months | Day D of the months the anchor fixes |

     A day beyond the month's end means the month's last day. Nothing models weekends or holidays:
     the tolerance absorbs them.
   - **Matching actual deposits to nominal dates, one to one.** A reached deposit pairs with an
     unpaired nominal date within the tolerance. Ties go to the nearest date, then the earlier
     nominal date, then the earlier transaction date, then the transaction ID. These are the only
     inputs, so the pairing never depends on import order (as F12's exhaustive tests).
   - **Each occurrence gets one state:**

     | State | Meaning |
     |---|---|
     | `received` | A deposit pairs with it, within the amount tolerance |
     | `amount_changed` | A deposit pairs with it, outside the amount tolerance. Flagged, with the difference |
     | `missed` | The tolerance has passed as of `as_of`, with no deposit |
     | `expected` | Still to come |

     A reached deposit with no nominal date in range is `unscheduled`, flagged.
   - **Changes are dated terms, never edits** (G2). A raise is
     `pf income terms --effective-from DATE --amount …`, so months before it keep their baseline
     (G7).
   - Alternatively **matching by the deposit's month:** simpler, but a paycheck paid a day early
     across a month boundary would read as a third paycheck. Point 3 exists to prevent exactly that.

3. **The three-paycheck rule: a month's baseline is a count fixed by cadence, and nominal dates
   decide the month.**
   - **Baseline count per month:**

     | Cadence | Baseline count |
     |---|---|
     | Weekly | 4 |
     | Biweekly | 2 |
     | Semimonthly | 2 |
     | Monthly | 1 |
     | Longer cadences | Not salary: refused for `salary` |

     That is, floor(occurrences per year ÷ 12).
   - **A month's occurrences are those whose nominal date falls in it.** The deposit date does not
     decide the month. The first baseline-count occurrences are baseline, and any later ones are
     **extra**.
   - **Baseline monthly income** is the baseline count × the expected amount in effect on each
     nominal date. It is a planned figure, labelled so (G1), and never the actual deposits.
   - **Extra income** is the actual amounts of extra occurrences that were received.
   - **Side income** (kind `side`) is never baseline: every received occurrence is extra once
     received, and nothing before it is (PRD §11's proposed default).
   - **What M12 guarantees:**
     - No figure M13 or M16 reads as baseline income can include an extra or side occurrence.
     - A month's baseline is the same whether it holds two or three biweekly paychecks.
     - M12.3's report shows each extra occurrence on its own line, "extra: to goals (M14)", and
       M14 allocates it.
   - **Proved by a test** comparing two generated ledgers that are identical except that one month
     holds a third biweekly paycheck. Every baseline figure is byte for byte the same, and only the
     extra lines differ. Further tests cover:
     - an early payment across a month boundary (paid on the 31st, nominal date the 1st), which is
       not a third paycheck;
     - a late payment the other way;
     - 2026's two three-paycheck months for a Friday anchor, computed by hand in the test.
   - Alternatively:
     - **The baseline as an average,** 26 ÷ 12 paychecks: smooths the year, but raises every
       month's targets by the third paychecks spread across it, which PRD §11 forbids.
     - **The deposit date's month:** see point 2's alternative.

4. **Proposals: deterministic, never stored, confirmed by a person.**
   - `income proposals` and `obligation proposals` group transactions by account, normalized
     description (D-064's normalization), direction, and income type or spending type. A group
     becomes a proposal only when **all** of these hold:
     - it has at least 3 transactions, or 2 for annual or quarterly;
     - its intervals fit one cadence within the default tolerance;
     - its amounts lie within a 10% band, or are exact.
   - **Each proposal gives:** the cadence, an anchor (its latest date), a suggested amount (the
     median of its last 6, or of all if fewer, rounded half-down to the cent), the range it saw,
     the next expected date, and a `PROPOSAL_KEY`. The key is a hash of the account, the normalized
     text and the cadence, and is stable across imports.
   - **Confirming a proposal** is `income add` or `obligation add` with `--from-proposal`. Its token
     covers the proposal's whole content, so a proposal changed by a later import refuses. The person
     may adjust any field. Adding without a proposal is the manual path (PRD §11: "manual input is
     secondary but … necessary").
   - **A proposal is withdrawn** once a source or obligation's matcher reaches its transactions, or
     once it is dismissed (point 5). A proposal is never stored and never relied on (D-066 point 4).
   - **A normalized merchant (D-066)** is not needed. D-064's normalization groups well enough on
     the fixtures. If the owner's real descriptions vary within one payee (store numbers, dates in
     the text), a merchant normalization is its own decision, raised with an example.
   - Alternatively **stored proposals with their own lifecycle:** they can be listed historically,
     but they are a cache that goes stale with every import.

5. **Recurring obligations: confirmed, dated, fixed or discretionary.**
   - **What an obligation stores:**
     - an account, a name, a cadence and an anchor;
     - an exact amount, or a range LOW..HIGH (utilities, for example);
     - a class, `fixed` or `discretionary`;
     - a matcher: text, and optionally a category, the effective category of D-064's precedence;
     - dated terms, as income (G2).
   - **Expected against actual** works as point 2, over money out in spending, with the states
     `paid`, `amount_out_of_range`, `missed`, `expected` and `unscheduled`.
     - The planned amount of a range is its HIGH, which rounds toward protection (G8).
     - A `missed` obligation stays a protected amount in M16 until its tolerance passes.
   - **Fixed and discretionary (PRD §10, §12).** A spending transaction reached by a `fixed`
     obligation is **fixed spending**. Every other spending transaction is **discretionary**. Both are
     derived from `transaction_obligation`. Categories are untouched: the class is a fact about the
     obligation, not about the category.
   - **Dismissal** stores the proposal key with an event, so the proposal stays withdrawn across
     imports. Undoing the dismissal brings it back.
   - **Two obligations reaching one transaction** give `obligation_conflict`, disclosed. The
     transaction is then discretionary, which is the conservative choice for budget capacity.
   - Alternatively:
     - **Fixed and discretionary as a class per category:** simpler, but a category such as
       Utilities holds both a fixed bill and a one-off purchase.
     - **Card minimum payments as obligations:** possible, since an obligation can be added on a
       card's payment, and M15 adds loan minimums from schedules. Recommended: card payments are
       obligations on the paying account, typed by the person, until M15.

6. **The extraction (principle 2).** M12.1 writes income sources directly. M12.2 is the second use,
   so `planning/entries.py` (G2) and `planning/schedules.py` are extracted then. M12.1's code moves
   onto them with every M12.1 output byte for byte unchanged, compared as CB5. This is the same
   pattern as `stated_fields.py` in M9.2.

7. **Tokens.**
   - `in1` covers:
     - the operation;
     - for add, the proposal's or definition's full content and every deposit the matcher would reach
       now, with its state;
     - for terms and undo, the source's definition, its active terms and its current outcome.
   - `ob1` covers the same for obligations, and the key and group content for a dismissal.
   - **No `r`, `t`, `d` or `c` token moves.** Sources and obligations bind no records, and no
     decision changes which one applies to a transaction. A decision or correction that changes a
     derived outcome is reflected in `in1` and `ob1`, which are recomputed on the next show.
   - **Commands that may change output:** `review show` and `review transaction show` gain a
     "Recurring" section, and only where a source or obligation reaches the transaction. Every other
     command is held by G6.

8. **`pf report income` (M12.3).** One block per month, a month chosen as D-057's:
   - per source: baseline, extra and side, with the expected and received amounts and the
     occurrences by state;
   - obligations due and paid by class;
   - "possible paychecks, unclassified";
   - and disclosures: conflicts, `unscheduled` deposits and `amount_changed` occurrences.

   **The UI page** renders the builder's lines, with M8's parity test. It is read-only, under D-062,
   unchanged.

9. **Performance.** Derived outcomes are rewritten on every write: linear in deposits on the
   accounts of sources and obligations, times the matchers there. Proposals scan once, grouped by a
   key, then sort within each group. **The benchmark row** is `--recurring`: 6 sources (biweekly,
   semimonthly, side), 60 obligations, 60 months, with the counts of `received`, `missed`, extra and
   `obligation_conflict` asserted. It times:

   | Operation | Target |
   |---|---|
   | `report income`, both proposals | Below 2s |
   | `income add`, `obligation add` | Below 2s, at most 2× a one-row import |
   | A one-row import | G9 |
   | `totals` | Unchanged |

**Not in M12:** per-deposit assignment statements, sources or obligations that set a type, a
normalized merchant, gross income and payroll deductions (PRD §13: "do not subtract payroll
deductions again", so M12 stores take-home only), income categories (point 1's matcher and kind
answer "which income is this" without one), tax reserves (M14), and budgets (M13).

**Inputs needed from the owner:** each salary's account, cadence, one real pay date and the normal
take-home amount; the side-income sources and which are tax-eligible; whether paychecks vary (for
the amount tolerance); the bills to confirm first.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** Income sources as a confirmed schedule plus matcher, counting only `income`-typed deposits.
  Conflicts are disclosed (point 1). Alternatively sources that classify, or per-deposit statements.
- **B.** Nominal dates decide the month, and baseline counts are fixed by cadence. Side income is
  never baseline (points 2 and 3). Alternatively an averaged baseline, or the deposit date's month.
- **C.** Deterministic proposals, never stored, confirmed through `--from-proposal` with a token
  over their content (point 4).
- **D.** Obligations with exact or range amounts, dated terms, and fixed or discretionary by
  obligation (point 5). Alternatively a class per category.
- **E.** `entries.py` and `schedules.py` extracted at M12.2 (point 6).
- **F.** Migrations 0024 and 0025, two-letter tokens `in1` and `ob1` (G5), and no shared token
  moving (point 7).
- **G.** `pf report income` and its page, and the `--recurring` benchmark row (points 8 and 9).
- **H.** The slices M12.1 to M12.3, in that order.

### M12.1 acceptance criteria

| ID | Test |
|---|---|
| IA1 | Migration 0024 meets G10: populated ledgers, empty tables, nothing stale, nothing changed, atomic, the previous version refused. Each append-only trigger refuses, with a control insert that succeeds |
| IA2 | Nominal dates for every cadence: month-end clamping, a leap-year February, and a biweekly anchor crossing a year, each computed by hand in the test |
| IA3 | A source reaches only income-typed money in, in its account, whose effective description contains its text, a corrected description included. An unclassified match is listed as a possible paycheck and never counted. Two sources on one deposit give `source_conflict` on both |
| IA4 | One-to-one pairing within the tolerance, ties as point 2. The states `received`, `amount_changed`, `missed` (only after the tolerance passes `as_of`), `expected` and `unscheduled` are each produced, and pairing is the same in every import order, exhaustively for four files |
| IA5 | `income proposals` is deterministic, stable across repeat imports, and omits groups below the thresholds and those a source reaches. `--from-proposal` with a token made before an import that changes the group refuses, changing nothing |
| IA6 | `income add`, `terms` and `undo` follow G3: stale token, stale account, unknown account, blank text, `salary` on a longer cadence, a tolerance out of range and an `effective_from` in a closed month are each refused, changing nothing. `evidence_digest` is unchanged by every income write |
| IA7 | A later terms row changes only nominal dates on or after its `effective_from`. Undo steps back by G4 |

### M12.2 acceptance criteria

| ID | Test |
|---|---|
| IB1 | Migration 0025 meets G10. Every M12.1 output is byte for byte the same after the extraction, compared as CB5 |
| IB2 | Obligations reach spending by text and optional effective category. A range's planned amount is its HIGH. The states are produced as IA4. `obligation_conflict` leaves the transaction discretionary, disclosed |
| IB3 | Fixed spending plus discretionary spending equals D-056's Spending exactly, for the ledger, each account and each month, on generated ledgers |
| IB4 | A dismissal keeps a proposal withdrawn across imports, and its undo brings it back. A dismissal or add with a stale `ob1` refuses |
| IB5 | `review show` and `review transaction show` gain "Recurring" only where something reaches the transaction. Every other command is byte for byte as before, compared as G6 |

### M12.3 acceptance criteria

| ID | Test |
|---|---|
| IC1 | Three-paycheck rule: two ledgers differing only by a third biweekly occurrence have byte-identical baseline lines in every month, and the extra shows once, labelled. An early and a late payment across a month boundary never make a third |
| IC2 | Side income is never baseline, and shows as extra in the month received |
| IC3 | `report income` opens read-only and changes no logical digest. Every figure is labelled actual, expected or planned (G1). Its UI page equals the command line for line, with source names holding HTML shown as text |
| IC4 | `--recurring` asserts its counts, its figures are recorded in [benchmarks.md](benchmarks.md) under G9's stopping rule, and `totals` and `report monthly` are byte for byte unchanged. Every earlier criterion still passes |

---

## D-069 M13 plan: budgets and spending allowances — Approved

M13 meets PRD §12's budget structure and required outputs, without safe-to-spend, which is M16
(D-066 point 2):

- calendar-month targets;
- a household allowance with personal allocations;
- optional category allowances;
- fixed commitments apart from discretionary spending;
- no rollover;
- revised daily and weekly allowances, and pace.

Every figure here is labelled **budget pace**, never "safe to spend". M13 holds the three-paycheck
rule on the budget side. It also adds the household timezone (G7), which every later milestone
reads. **No security control changes.** No `r`, `t`, `d` or `c` token moves.

```sh
pf setting show          --db DB
pf setting set           --db DB household_timezone ZONE --revision st1-…
pf setting undo          --db DB household_timezone --revision st1-…
pf budget set            --db DB --from YYYY-MM --allowance AMOUNT \
   [--member NAME=AMOUNT ...] [--category NAME=AMOUNT ...] \
   [--supersedes PLAN_ID --supersedes-revision bp1-…] [--correct-closed-month] --revision bp1-…
pf budgets               --db DB
pf budget show           --db DB PLAN_ID
pf budget undo           --db DB PLAN_ID --revision bp1-…
pf report budget         --db DB [--month YYYY-MM] [--member NAME] [--as-of DATE]
```

**Slices:**

| Slice | Scope |
|---|---|
| M13.1 | Settings and budget plans: migration 0026, `pf setting`, `pf budget set`, `show`, `undo`, chains, `st1`, `bp1` (points 1, 2 and 6) |
| M13.2 | `pf report budget`: actual against target, pace, revised allowances, the personal view, closed months and unused capacity, the UI page, the benchmark row (points 3 to 5, 7) |

**Recommendations, each with its alternatives:**

1. **Settings, keyed and append-only.**
   - `ledger_setting_key` is a reference table seeded by migrations. 0026 seeds
     `household_timezone`, and 0032 seeds `checking_buffer_cents`. A key not in the table is refused
     by a foreign key, so a new setting is always a migration and never free text.
   - `ledger_setting` holds a key, a value and events. One value is active per key, and changing it
     is undo then set, with `st1` over the key and its active value.
   - The timezone is validated with `zoneinfo.ZoneInfo`. An unknown zone is refused.
   - Alternatively **a settings file:** easier to edit, but outside the ledger, its backups and
     D-043's checks.

2. **A budget plan applies from a month until a later plan replaces it.**
   - **What a plan holds:**
     - `effective_from`, a month;
     - the household **discretionary allowance**, in cents per month, which is PRD §12's "original
       monthly target";
     - optionally, **personal allocations**: one amount per M11 member, summing exactly to the
       allowance;
     - optionally, **category allowances**: amounts per category, each a cap of its own.

     If the category allowances exceed the household allowance, the plan is accepted and the excess
     is shown as a warning, since categories overlap members.
   - **The plan in effect for month M** is the newest active plan with `effective_from` ≤ M. Chains
     follow G4.
   - **Closed months are never rewritten** (G7). An `effective_from` before `as_of`'s month is
     refused unless `--correct-closed-month` is given. A correction is disclosed on every later
     report of that month as "target corrected after the month closed".
   - **Fixed commitments are not part of the target.** The report shows them apart: planned from
     M12's fixed obligations due that month, and actual from fixed spending.
   - **Personal allocations by amount, not percentage.** Typing amounts that sum exactly avoids any
     rounding. A percentage view can be computed with `allocate_cents` if the owner wants one.
   - Alternatively:
     - **A plan typed for every month:** explicit, but it needs a plan each month, and forgetting
       one leaves the month with none.
     - **Targets derived from income:** PRD §12 asks for typed targets, and deriving them would put
       the three-paycheck rule at risk.

3. **Actual spending against the target, conservatively.**
   - **Actual discretionary** is M12's discretionary spending in the month, by D-057's date, with
     pending transactions included (PRD §8: "pending transactions must reduce spending capacity
     immediately").
   - **Possible spending** is unclassified money out, plus unconfirmed transfer-kind money out
     (D-011: "suspected transfers never increase safe-to-spend").
     - It is counted **against capacity**, on a line of its own: "counted until classified".
     - Remaining capacity is labelled provisional while it is non-zero.
   - **Personal view (`--member`).** A member's actual is their parts of discretionary spending,
     from M11's effective allocations.
     - Unattributed discretionary spending counts against the household only, disclosed.
     - It marks every member's figures provisional.
     - Members' actuals plus unattributed add exactly to the household's.
   - **Category allowances** compare a category's discretionary spending, effective category first
     (D-064), against its cap. A refund reduces its category (PRD §9).
   - Alternatively **classified spending only, with possible spending disclosed:** a smaller "actual",
     but it overstates capacity while anything is unclassified, against D-011.

4. **Required outputs: exact formulas in cents.** For the month in view, with `as_of` on day d of
   a month of N days:

   | Figure | Definition |
   |---|---|
   | R, days remaining including today | N − d + 1 |
   | T, the target | The plan's allowance |
   | A, actual | Actual discretionary plus possible spending |
   | C, remaining capacity | T − A, shown negative when negative |
   | Original daily allowance | floor(T ÷ N) |
   | Revised daily allowance | floor(C ÷ R) when C > 0, else 0 |
   | Revised weekly allowance | floor(C × min(7, R) ÷ R) when C > 0, else 0: the next seven days, capped at month end (PRD §12) |
   | P, pace to date | floor(T × d ÷ N): what the target allows through the end of today |
   | Above or below pace | A − P, signed, worded "above" or "below" |
   | Reduction needed to recover | Original daily − revised daily, when positive, per day for the R days left |
   | Equivalent days of original allowance | floor((A − P) ÷ original daily), shown only when A > P and original daily > 0 (PRD's "where meaningful") |
   | Negative remaining capacity | "Over target by \|C\|", revised allowances 0, and the lines that caused it: the largest five discretionary transactions and possible spending |

   - **Rounding is always down for allowances (G8).** A test proves Σ over the remaining days of
     the revised daily allowance ≤ C.
   - **A future month** shows the plan only. **A closed month** shows its final figures and
     "unused capacity: max(0, C), to savings (planned, not a bank transfer)" (PRD §12). M14's
     priority order takes that figure.
   - Alternatively **pace through the end of yesterday,** d − 1: stricter in the morning, but it
     disagrees with an actual that includes today's transactions.

5. **The three-paycheck rule, held.** No input of `report budget` is actual income or an extra
   occurrence. The report shows M12's baseline monthly income beside the target and fixed
   commitments as context, labelled planned. **Proved by test:** M12's two ledgers differing only by
   a third paycheck give byte-identical `report budget` output in every month, and M14's goals
   receive the extra.

6. **Tokens and parity.**
   - `bp1` covers the operation, the plan's full content, the plan it supersedes and its token, and
     which months each change affects.
   - `st1` covers a key and its active value.
   - Plans bind no records, so no shared token moves.
   - No existing command changes output (G6).

7. **Performance.** `report budget` reads one month: its transactions, M12's derived outcomes and
   M11's allocations. It never runs the transfer candidate search. **The benchmark row** is
   `--budget`, on M12's shape plus three members, a plan with 12 category allowances, and a month
   holding 3,000 discretionary transactions. It asserts its counts, and times `report budget` for
   the household and for each member (target below 2s, expected well below 1s) and `budget set`.

**Not in M13:** rollover (PRD §12 forbids it), weekly or custom periods, budgets by account, safe to
spend (M16), alerts or notifications (the system is on demand, PRD §2; a report states the over-pace
condition, and the M17 dashboard shows it), goals (M14), and budgets in scenarios (M18).

**Inputs needed from the owner:** the household timezone, the monthly discretionary allowance, the
personal allocations, and any category allowances.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** Keyed, append-only settings, with the household timezone required for any "today" (point 1
  and G7).
- **B.** Plans effective from a month until replaced, closed months protected, personal allocations
  by exact amount, and fixed commitments apart from the target (point 2). Alternatively a plan
  typed for every month.
- **C.** A conservative actual that counts possible spending until it is classified (point 3).
  Alternatively classified spending only.
- **D.** Point 4's formulas, rounding down, pace through the end of today.
- **E.** No input from actual or extra income (point 5).
- **F.** Migration 0026, `st1` and `bp1`, and no shared token moving (point 6).
- **G.** The `--budget` benchmark row (point 7).
- **H.** The slices M13.1 and M13.2, in that order.

### M13.1 acceptance criteria

| ID | Test |
|---|---|
| BA1 | Migration 0026 meets G10, seeds `household_timezone` only, and every trigger refuses with a control |
| BA2 | `setting set` refuses an unknown key, an unknown zone, a second active value and a stale `st1`. Every planning command needing today refuses with no zone set, naming the command to run |
| BA3 | `budget set` refuses: member amounts not summing exactly to the allowance, an unknown member or category, a negative amount, a closed-month `effective_from` without the flag, and a stale `bp1`. Each refusal changes nothing, and `evidence_digest` is unchanged by every budget write |
| BA4 | The plan in effect for each month is the newest active plan with `effective_from` ≤ the month. Chains follow G4, and every planning module is free of clock calls (G7's test) |

### M13.2 acceptance criteria

| ID | Test |
|---|---|
| BB1 | Each formula of point 4, computed by hand for a 28-, 30- and 31-day month, on day 1, a middle day and the last day, with A below, at and above the target and C negative |
| BB2 | Σ revised daily × R ≤ C, and the revised weekly allowance ≤ C, over generated months and amounts (Hypothesis) |
| BB3 | Pending, unclassified and unconfirmed transfer-kind money out reduce capacity, each on its own line. Classifying one moves it to actual discretionary or out of the budget, exactly |
| BB4 | Members' actuals plus unattributed equal the household's, and a member's view with any unattributed spending reads provisional |
| BB5 | Third-paycheck parity as point 5. A closed month shows unused capacity labelled planned, and a corrected closed month is disclosed |
| BB6 | `report budget` opens read-only. Its UI page equals it line for line. `--budget` asserts its counts and records its figures under G9. Every earlier criterion still passes |

---

## D-070 M14 plan: goals, reserves and the tax reserve — Approved

M14 meets PRD §13's goals, emergency fund and annual and irregular expenses, and §16's
lightweight tax reserve. It closes three PRD §21 boxes:

- "Annual reservations and purchases are not double-counted";
- "Goal allocations cannot silently exceed available funds";
- "Backups restore … goals".

M14 is the planning layer's second use of a fund-like model, so it extracts the shared model here
(D-066 point 3). It also adds the first statement on a transaction since M11, fund consumption, so
`r`, `t`, `d` and `c` move once (G5). **No security control changes.**

```sh
pf fund add        --db DB --name NAME --kind goal \
   (--monthly AMOUNT | --percent-of-income PCT | --target AMOUNT --by YYYY-MM) --revision fu1-…
pf fund add        --db DB --name NAME --kind emergency (--minimum AMOUNT | --months N) --revision fu1-…
pf fund add        --db DB --name NAME --kind reserve --target AMOUNT \
   (--due DATE | --cadence annual:MM-DD | --cadence every:N-months:D --anchor DATE) --revision fu1-…
pf fund add        --db DB --name NAME --kind tax --percent PCT --effective-from DATE --revision fu1-…
pf fund terms      --db DB FUND_ID --effective-from DATE … --revision fu1-…
pf fund undo       --db DB FUND_ID --revision fu1-…
pf funds           --db DB [--as-of DATE]
pf fund show       --db DB FUND_ID [--as-of DATE]
pf fund assign     --db DB --fund FUND_ID --account A --amount AMOUNT --revision fa1-…
pf fund unassign   --db DB --fund FUND_ID --account A --revision fa1-…
pf fund priority   --db DB FUND_ID FUND_ID ... --revision fu1-…
pf fund release    --db DB --fund TAX_FUND_ID --amount AMOUNT --on DATE --revision fu1-…
pf review consume  --db DB --account A TRANSACTION_ID --fund FUND_ID --revision t11-… \
   [--supersedes CONSUMPTION_ID --supersedes-revision fc1-…]
pf review consumptions      --db DB [--account A]
pf review consumption show  --db DB CONSUMPTION_ID
pf review consumption undo  --db DB --account A CONSUMPTION_ID --revision fc1-…
pf report funds    --db DB [--as-of DATE]
```

**Slices:**

| Slice | Scope |
|---|---|
| M14.1 | Funds, assignments and priority: migration 0027, the four kinds, the assignability guard, planned contributions, `fu1`, `fa1` (points 1 to 4) |
| M14.2 | Consumption and the tax reserve: migration 0028, `review consume` on the stated model, tax accrual, payments and releases, `fc1`, `r13`, `t11`, `d10`, `c6` (points 5 to 7) |
| M14.3 | `pf report funds`, extra income and unused capacity allocated by priority, M13's "paid from reserves" line, the UI page, the restore test, the benchmark row (points 4, 8 and 9) |

**Recommendations, each with its alternatives:**

1. **One fund model, four kinds.** A fund has a name and a kind, plus dated terms (G2, G4):

   | Kind | Terms | Required amount as of a date |
   |---|---|---|
   | `goal` | One of: monthly amount, percentage of baseline income (bps), or target amount by month | Monthly: the amount each month. Percentage: ceil(baseline × bps ÷ 10,000) each month. Target: ceil((target − assigned) ÷ months left, including the deadline month) |
   | `emergency` | A minimum amount, or N months of essential expenses | The minimum, or N × the monthly fixed commitments planned in `as_of`'s month (M12), a non-monthly obligation counting as ceil(amount × occurrences per year ÷ 12) |
   | `reserve` | A target, and a due date or a recurrence (M12's schedules) | ceil((target − assigned − consumed this cycle) ÷ months left until due, including the due month). With no month left and anything outstanding, it is underfunded |
   | `tax` | A percentage (bps), from a date | Accrued − paid − released (point 6) |

   - A goal's "percentage of income" reads **baseline** income only. Extra and side income reach
     goals through priority (point 4), never through a percentage, so a third paycheck changes
     nothing about a goal's required amount.
   - Alternatively **four separate models:** each one simpler, but it is the same definition,
     terms, assignments and states four times. The planning layer's extraction belongs here
     (D-066 point 3).

2. **Assignments: funds are held in accounts, and never assigned twice.**
   - **An assignment** says "X of account A's balance belongs to fund F". One is active per fund
     and account, and changing it is undo then assign, with `fa1`.
   - **What an account can hold:** its latest balance observation on or before `as_of` (D-057). An
     account with no observation can hold no assignment, so the command refuses and names
     `pf balance record`. A card or loan is refused.
   - **The guard:** `fund assign` refuses when the active assignments on the account, plus the new
     amount, would exceed that observation. That is "the same funds cannot be allocated twice" (PRD
     §13), enforced inside the write lock (G3).
   - **When an observation falls below the assignments,** for example after a later
     `balance record`, the account is **`over_assigned`** by the difference:
     - it is disclosed on every report and page that shows a fund;
     - every fund assigned on that account is marked "assignment not backed";
     - every new assignment there is refused until assignments are released or a higher balance is
       observed;
     - M16 treats the difference as unfunded.

     It is never absorbed and never silent: this is PRD §21's "cannot silently exceed".
   - **A stale observation,** older than 31 days at `as_of`, keeps assignments valid but marks
     them provisional. Activity since the observation is not added, since D-057 counts only what
     has been observed. M16 makes its own estimate of current liquidity.
   - Alternatively **assignments without accounts** (envelopes over total savings): simpler, but
     PRD §13 says goals "may share an account", and no check against an actual balance could hold.

3. **Planned contributions are planning figures, never transfers.** Each month, each goal and
   reserve has a **planned contribution**: its required amount for the month. The emergency fund
   has a **restoration recommendation**, max(0, minimum − assigned), when it is underfunded. These
   are "recommend restoration … do not change other allocations without approval" (PRD §13):
   - nothing is assigned automatically;
   - `report funds` lists what to assign.

   Retirement stays apart from fund priority (PRD §13): a retirement account can hold no
   assignment.

4. **Priority: where extra income and unused capacity go, as a plan.**
   - `fund priority` sets one ordered list of goals, reserves and the emergency fund, with `fu1`
     over the whole list.
   - **Planned allocation of a month's extra.** The extra is M12's extra paychecks received, plus
     side income received after its tax accrual (point 6), plus M13's unused capacity of a closed
     month. It is allocated down the list:
     1. each fund takes up to its outstanding need;
     2. what is left is "unallocated extra", shown.

     These are planned figures, labelled so, and never assignments (PRD §12: "an allocation to
     savings is not evidence of an actual bank transfer"). The person assigns once the money has
     moved.
   - **PRD §11's "after tax reservation, it goes toward goals unless overridden"** is this rule.
     The override is the priority list itself, or leaving a source's extra unallocated by putting
     no goal first. A per-source override is not built until it is needed.
   - **PRD §22's "house versus debt" preference** is the order of a house goal against an
     extra-debt-payment goal. M15's payoff plans read the debt goal's planned amount (D-071 point 6).
   - Alternatively **automatic assignments from the priority:** less typing, but assignments would
     no longer mean money that is really there.

5. **Consumption: a purchase consumes its reserve once, on D-063's stated model.**
   - `review consume` states that a spending transaction is paid from a fund: a reserve, a goal or
     the tax fund. It binds the transaction's records, and chains, agreement, conflicts,
     `basis_changed` and the refusals of `review confirm` and `review separate` are all D-063's,
     through `stated_fields.py`'s shared code. This is the fourth stated kind.
   - **Its effect, derived in `transaction_fund_consumption`:** the transaction consumes
     min(|amount|, the fund's assigned amount not yet consumed this cycle).
     - The consumed portion reduces the fund's assignment, as a derived amount: the stored
       assignment row is never rewritten.
     - In M13 the consumed portion **leaves discretionary actual**, on a line of its own: "paid from
       reserves".
     - Any excess stays discretionary.
     - The transaction is still counted once in spending, in `totals` and in its category,
       unchanged.

     That is PRD §21's "annual reservations and purchases are not double-counted": the reservation
     stops reducing capacity, and the purchase does not reduce the monthly target.
   - **A refund of a consumed purchase** restores the fund only if it is itself consumed against
     the fund (a stated choice), and is otherwise discretionary. Nothing is inferred.
   - **Cycles.** A recurring reserve's consumption counts against the cycle holding the
     transaction's date. A new cycle starts with its target outstanding and its leftover assignment
     carried over, since assigned money is still there.
   - Alternatively **a matcher that consumes automatically** (text and category near the due date):
     less to do by hand, but a wrong match would silently move money between budget and reserve. It
     can be added later, as D-064 rules were, once the owner names the need.

6. **The tax reserve.** It is a `tax` fund with a percentage from a date.
   - **Accrual** is derived and never stored. For each M12 occurrence of a `tax_eligible` source
     that is `received` on or after the fund's `effective_from`, the accrual is
     ceil(received amount × bps ÷ 10,000), rounded toward protection.
   - **Payments** are consumptions against the tax fund (point 5).
   - **Releases** are `fund release`: an amount and a date, for a reserve found too large. Undo is
     by G4.
   - **Required** = accrued − paid − released, never below zero. The excess of payments over the
     reserve is shown as "paid beyond the reserve".
   - **Every line is labelled** "planning reserve, not a calculated tax liability" (PRD §16).
   - **Excluded from spendable income:** side income's extra (point 4) is net of its accrual, and
     M16 protects the tax reserve's required amount first, item 1 of PRD §12's order.

7. **Tokens and parity.**

   | Token | Covers | Version |
   |---|---|---|
   | `fu1` | Fund definition, terms, chain, priority list, release | M14.1 |
   | `fa1` | The account's observation, its active assignments and the fund's | M14.1 |
   | `fc1` | Consumption undo: its fund, the transactions holding its bound records, and the outcome with and without it | M14.2 |
   | Item, transaction, decision undo, correction undo | Add each transaction's active consumption statements, left out while none reaches | `r13`, `t11`, `d10`, `c6` (after M11) |

   The correction undo token joins because the consumed amount turns on the effective amount.
   **Commands that may change output:**
   - `review show` and `review transaction show` gain a "Paid from" section, only where a
     consumption reaches;
   - `report budget` gains "paid from reserves", only where one applies.

   Every other command is held by G6, with digests kept on every ledger with no consumption.

8. **`pf report funds` (M14.3).** One block per fund: kind, terms in effect, assigned by account,
   consumed this cycle, required, planned contribution this month, state (`funded`, `underfunded`,
   `over_assigned`, `provisional`) and the date its target is reached at the planned rate. Then:
   - the month's extra and its planned allocation by priority;
   - each account's balance observed, assigned and unassigned;
   - the tax reserve block with its label;
   - disclosures.

   **The UI page** renders the builder's lines, with the parity test.

9. **Backups and performance.**
   - **Backups:** the rich-ledger restore test gains funds, assignments, priority, consumptions and
     releases, closing PRD §21's "goals". Compared as HB5.
   - **Performance:** `report funds` reads funds, assignments, the latest observations, M12's
     outcomes and the consumption outcomes, and is linear in each. **The benchmark row** is
     `--funds`: 20 funds of every kind, 6 accounts holding assignments (one `over_assigned`), 2,000
     consumptions and 60 months of tax-eligible side income. It times `report funds`,
     `report budget`, `fund assign`, `review consume` and a one-row import (G9).

**Not in M14:** automatic consumption matchers, automatic assignments, per-source extra overrides,
goals in net worth (M15 reads balances, not funds), safe to spend (M16), and goals in snapshots
(M19).

**Inputs needed from the owner:** initial goals with their terms, the emergency minimum (amount or
months), annual and irregular expenses with targets and dates, the tax reserve percentage, the
priority order (including house against extra debt payments), and each fund's accounts and
current assignments.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** One fund model of four kinds, with dated terms, extracted as the planning layer's shared
  model (point 1).
- **B.** Assignments against an account's latest observation, refused beyond it, with
  `over_assigned` disclosed and never absorbed (point 2). Alternatively assignments without
  accounts.
- **C.** Planned contributions and restoration as recommendations, never automatic assignments
  (points 3 and 4).
- **D.** One priority list for extra income and unused capacity, as a plan (point 4).
- **E.** Consumption as a person's statement on D-063's model, taking the consumed portion out of
  M13's discretionary actual (point 5). Alternatively a consumption matcher.
- **F.** The tax reserve as derived accrual less payments and releases, labelled as PRD §16 asks
  (point 6).
- **G.** Migrations 0027 and 0028, `fu1`, `fa1`, `fc1`, and `r13`, `t11`, `d10` and `c6` keeping
  every digest (point 7).
- **H.** `pf report funds`, its page, the restore test and `--funds` (points 8 and 9).
- **I.** The slices M14.1 to M14.3, in that order.

### M14.1 acceptance criteria

| ID | Test |
|---|---|
| GA1 | Migration 0027 meets G10, every trigger refusing with a control |
| GA2 | Each kind's required amount, by point 1's formula, computed by hand at a deadline month, mid-term and past due, rounded up (G8). A percentage goal is byte-identical across M12's third-paycheck pair |
| GA3 | `fund assign` refuses beyond the latest observation, on an account with no observation, on a card, loan or retirement account, a second active assignment and a stale `fa1`, changing nothing |
| GA4 | A later lower observation makes the account `over_assigned` by exactly the difference, disclosed wherever funds show, and new assignments there refuse until resolved. A race test (G3): two assignments shown against one observation, so the second refuses |
| GA5 | Planned contributions and restoration change no assignment. `evidence_digest` is unchanged by every fund write |

### M14.2 acceptance criteria

| ID | Test |
|---|---|
| GB1 | Migration 0028 meets G10. `review consume` follows D-043 and D-063: a stale `t11`, another account, a transaction not in spending and an unknown fund are refused. Chains, agreement, conflict and `basis_changed` follow CB2 and CB3 |
| GB2 | No double count: a purchase consuming a reserve counts once in `totals` and its category, leaves discretionary actual by exactly the consumed portion, and its excess stays discretionary. The fund's outstanding amount falls by exactly the consumed portion. Undo restores both exactly |
| GB3 | Tax accrual rounds up per occurrence from `effective_from`. Payments and releases reduce required, never below zero, and every tax line carries PRD §16's label |
| GB4 | `r13`, `t11`, `d10` and `c6` keep every digest without consumption, with a test pinning each definition and `fc1`. Every command but those point 7 names is byte for byte as before (G6) |

### M14.3 acceptance criteria

| ID | Test |
|---|---|
| GC1 | Extra income and unused capacity allocate down the priority list exactly, each fund to its need, leaving the remainder shown. All are labelled planned |
| GC2 | `report funds` and its page agree line for line, read-only, with names holding HTML shown as text |
| GC3 | Backup and restore keep funds, assignments, priority, consumptions and releases, compared as HB5 |
| GC4 | `--funds` asserts its counts and records its figures under G9. Every earlier criterion still passes |

---

## D-071 M15 plan: net worth and loans — Approved

M15 meets:

- PRD §17's balances and net worth;
- §13's retirement and investment history;
- §14's graduated loan planning;
- §9's "loan principal reduces debt, loan interest is an expense".

It closes PRD §21's "Graduated payments follow the configured schedule", and records shared-contract
§6's **loan projection assumptions** (point 5). It also places D-065's "net worth by member". **No
security control changes.** `r`, `t`, `d` and `c` move once, in M15.3.

```sh
pf account link          --db DB --subaccount A --aggregate B --revision al1-…
pf account unlink        --db DB --subaccount A --revision al1-…
pf loan terms add        --db DB --account A --rate PCT --payment AMOUNT --due-day D \
   --effective-from DATE [--remaining-months N] --revision lt1-…
pf loan rate             --db DB --account A --rate PCT --effective-from DATE --revision lt1-…
pf loan payment          --db DB --account A --amount AMOUNT --effective-from DATE --revision lt1-…
pf loan terms show       --db DB --account A
pf loan terms undo       --db DB --account A --revision lt1-…
pf loan plan set         --db DB --order (avalanche|snowball|custom:A,B,…) [--extra AMOUNT] --revision lt1-…
pf report net-worth      --db DB [--as-of DATE] [--member NAME]
pf report loans          --db DB [--as-of DATE]
pf loan project          --db DB --account A [--extra AMOUNT] [--months N] [--as-of DATE]
pf loan payoff           --db DB [--order …] [--extra AMOUNT] [--as-of DATE]
pf review breakdown      --db DB --account A TRANSACTION_ID --interest AMOUNT [--fees AMOUNT] \
   --revision t12-… [--supersedes ID --supersedes-revision lb1-…]
pf review breakdowns     --db DB [--account A]
pf review breakdown show --db DB BREAKDOWN_ID
pf review breakdown undo --db DB --account A BREAKDOWN_ID --revision lb1-…
```

**Slices:**

| Slice | Scope |
|---|---|
| M15.1 | Net worth: migration 0029, account links, valuation dates and warnings, retirement and investment history, `pf report net-worth`, its page (points 1 to 3) |
| M15.2 | Loan terms and planning: migration 0030, rate and payment periods, actual against schedule, projections, payoff orders, `pf report loans`, `loan project`, `loan payoff`, `lt1` (points 4 to 6) |
| M15.3 | Principal and interest: migration 0031, `review breakdown` on the stated model, interest in Spending by amount, `r14`, `t12`, `d11`, `c7`, `lb1`, the benchmark row (points 7 to 9) |

**Recommendations, each with its alternatives:**

1. **Net worth from observations only (PRD §17: "observed balances, not transaction totals
   alone").**
   - Each account's **valuation** is its latest balance observation on or before `as_of` (D-057), in
     the ledger's sign convention, so what is owed is negative. The valuation date is shown beside it.
   - **No observation means "not valued"**, listed by name and never counted as zero (PRD §7:
     "distinguish missing information from zero"). Net worth is then labelled incomplete.
   - **The mixed-date warning:** shown when the included valuations span more than 31 days, or when
     any is older than 31 days at `as_of`. Each such account is named.
   - **Statement balances (PRD §17: "extract … where available"):** D-060 stores a PDF statement's
     closing balance per document, but nothing reads it. Recommended: `pf balance record
     --from-statement DOCUMENT` turns one into an observation, as a person's act with D-057's
     checks. It is never automatic, since a statement balance is a dated fact the person confirms.
   - **Scenario assets** never reach net worth: scenarios write no observations (D-074).
   - Alternatively **observation plus activity since**: more current, but it needs complete
     coverage since the observation, and PRD §17 asks for observed balances. M16 does that estimate
     for liquidity only, labelled.

2. **Aggregate loans and subaccounts are counted once.**
   - `account link` makes a loan account a **subaccount** of an **aggregate** loan account. Both
     must be loans. Links are one level deep: an aggregate cannot itself be a subaccount, and a
     subaccount has one aggregate. Undo then set, with `al1`.
   - **The rule:**
     - When **every** subaccount has an observation dated on or after the aggregate's latest one,
       the subaccounts are counted and the aggregate is not.
     - Otherwise the aggregate's own observation is counted and the subaccounts are listed as "not
       counted: aggregate valued".
     - An aggregate with no observation counts its subaccounts if all are valued, and is otherwise
       not valued.
     - **Never both**, proved over generated link sets.
   - Alternatively **always the subaccounts:** simpler, but a missing subaccount would understate
     the debt.

3. **Retirement and investment, and net worth by member.**
   - `report net-worth` adds each retirement and investment account's observation history (dated
     values) and its contribution history: applied `investment_contribution` transfers into it, by
     month. It notes that payroll contributions never appear as take-home deposits, so nothing is
     subtracted twice (PRD §13). These accounts stay out of fund priority (D-070 point 3).
   - **By member (`--member`):** each account's valuation divided by M11's account attribution,
     with `shared` by the share through `allocate_cents`, and unattributed shown apart. Members plus
     unattributed add exactly to net worth. This reads attribution as ownership, labelled "by
     account attribution".
   - Alternatively **a separate ownership table** (PRD §6 distinguishes ownership from
     attribution): needed only if some account's spending is shared while its balance belongs to one
     person. An input below.

4. **Loan terms: dated rates and graduated payments.**
   - `loan_terms` is per loan account (or card, for interest projection only). It holds:
     - **rate periods:** an APR, stored as an integer in millionths of a percent (G8), and an
       `effective_from`;
     - **payment periods:** the scheduled payment, and an `effective_from`. A graduated schedule is
       a sequence of these, and changing a scheduled amount (PRD §14) is a new period;
     - a due day;
     - optionally, remaining months, as the lender states it.

     Chains and undo follow G4.
   - **The amount due on a due date** is the payment period in effect on that date. **The rate for a
     month** is the rate period in effect on its first day. Both are exact selections, tested at
     every step of a graduated schedule. That is PRD §21's box.
   - Alternatively **a schedule typed as a list of every payment:** exact for any lender, but long,
     and PRD §14 describes schedules with effective dates.

5. **Projection assumptions** (shared-contract §6), recorded here and printed with every
   projection:

   | Assumption | Rule |
   |---|---|
   | Start | The latest observation (a confirmed balance, dated). With none, there is no projection |
   | Interest per month | balance × APR ÷ 12, in `Decimal`, quantized to cents half-even once per month |
   | Payment | The scheduled payment in effect, plus any extra assumption, on the due day of each month |
   | Fees, late charges, daily accrual, payment allocation order, capitalization | Not modelled. Each is named in the output |
   | Negative amortization | Interest exceeding the payment is flagged, and the loan never pays off within the horizon |
   | Horizon | At most 600 months |
   | Label | Every figure is "projection, not lender-exact" (PRD §14), and never shown beside confirmed balances without that label |

   Alternatively **daily accrual on a 365-day year:** closer for many loans, but still not
   lender-exact without the lender's rules, and harder to check by hand.

6. **Actual against schedule, and payoff orders.**
   - **Actual payments** to a loan for a due period, which runs after the previous due date through
     this one, are the confirmed transfers into the loan account dated in the period: applied
     matches, and one-sided transfers naming it (D-054, D-055). Unconfirmed loan payments are listed
     apart, as "not counted until confirmed". The states are:

     | State | Meaning |
     |---|---|
     | `on_schedule` | Paid equals the amount due |
     | `short` | Paid less than due |
     | `extra` | Paid more than due, with the excess |
     | `missed` | Nothing paid, and the due date has passed |
     | `upcoming` | The due date has not come |

   - **Payoff orders.** They take the total monthly debt budget: the sum of scheduled payments, plus
     the plan's extra, or the planned amount of D-070's debt goal if the plan names none.
     - **Avalanche:** the highest rate first. Ties go to the larger balance, then the account name.
     - **Snowball:** the smallest balance first. Ties go to the higher rate, then the account name.
     - **Custom:** the stated order.

     Each loan receives its scheduled payment, and the extra goes to the first unpaid loan in the
     order. A paid-off loan's payment rolls into the next. The output gives each loan's payoff month,
     total interest, and the months until debt-free, for each order side by side. All of it is
     projection.
   - Alternatively **minimum-only comparisons:** less to configure, but PRD §14 asks for orders
     with user-configured allocation.

7. **Principal and interest, stated on a loan payment, by amount (M15.3).**
   - `review breakdown` states the interest, and optionally fees, of one loan payment, as the
     lender's statement gives them. The principal is the remainder. The statement:
     - binds the transaction's records;
     - follows D-063's model, the fifth stated kind;
     - requires interest + fees ≤ |amount|, and the transaction to be a confirmed loan payment.
   - **Effect on `totals` and `report monthly`: the one intended change of M12 to M21.**
     - The interest and fees move from Confirmed transfers to **Spending**, as "Loan interest and
       fees within loan payments", by amount.
     - Spending by category places them under "Interest and financial fees". No rule reaches them,
       since they are not transactions.
     - D-056's five groups still add exactly to net account movement. T1's "each transaction in
       exactly one group" becomes "each cent in exactly one group", disclosed by count.
     - D-055's warning that a loan payment's interest is not in spending is withdrawn for each
       payment holding an applied breakdown.
     - A breakdown that does not apply (conflict, or `basis_changed`) changes nothing, disclosed.
   - **Loan reports** read breakdowns for actual interest paid, and actual principal reduces the
     projected start only through a newer observation. Breakdowns never edit a balance.
   - Alternatively **breakdowns in `report loans` only, with `totals` unchanged:** keeps CC4 parity
     everywhere, but leaves PRD §9's "loan interest is an expense" unmet in the main report.
     Recommended only if the owner prefers `totals` frozen.

8. **Tokens and parity.**

   | Token | Covers | Version |
   |---|---|---|
   | `al1` | The aggregate's links and the latest observations of each linked account | M15.1 |
   | `lt1` | Loan terms, periods, the chain and the payoff plan | M15.2 |
   | `lb1` | Breakdown undo, as `fc1` | M15.3 |
   | Item, transaction, decision undo, correction undo | Add breakdowns, left out while none reaches | `r14`, `t12`, `d11`, `c7` (after M14) |

   **Commands that may change output:**
   - `balance record` gains `--from-statement`, and every other form of the command is unchanged;
   - `totals`, `report monthly` and `report household` change only where an applied breakdown
     reaches, and are byte for byte unchanged elsewhere, compared as G6 with breakdowns emptied;
   - `review show` and `review transaction show` gain "Principal and interest" where one reaches.

9. **Performance.** Net worth reads one observation per account. Projections are loans × months,
   at most 600. `totals` adds one read of `transaction_loan_breakdown`, measured against its 1.9s
   margin, and **if `totals` crosses 2.0s, the stopping rule applies** before any change.
   **The benchmark row** is `--loans`: 8 loans (2 graduated with 6 steps each, 1 aggregate with 3
   subaccounts), 120 months of payments, 5,000 breakdowns. It times `report net-worth`,
   `report loans`, `loan payoff` with all three orders, `totals` and `review breakdown`.

**Not in M15:** lender-exact accrual, fees inside projections, statement balances read
automatically, investment performance or prices (PRD §4: no investment recommendations), a separate
ownership table (unless input says so), and loans in scenarios (M18).

**Inputs needed from the owner:** representative graduated-loan documents, redacted, for the terms
and steps (PRD §22); which loans are aggregates with subaccounts; whether any account's ownership
differs from its spending attribution; the payoff plan's extra amount, or the debt goal's.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** Net worth from observations, with "not valued" never zero and the mixed-date warning, and
  statement balances recorded by a person (point 1).
- **B.** Subaccounts counted only when all are valued no older than the aggregate, never both
  (point 2).
- **C.** Net worth by member through M11's attribution (point 3). Alternatively an ownership table.
- **D.** Dated rate and payment periods (point 4), and point 5's projection assumptions, recorded as
  shared-contract §6's decision.
- **E.** Actual against schedule from confirmed transfers, and three payoff orders (point 6).
- **F.** Breakdowns moving interest and fees into Spending by amount (point 7). Alternatively loan
  reports only, with `totals` frozen.
- **G.** Migrations 0029 to 0031, `al1`, `lt1`, `lb1`, and `r14`, `t12`, `d11` and `c7` keeping
  every digest (point 8), and `--loans` (point 9).
- **H.** The slices M15.1 to M15.3, in that order.

### M15.1 acceptance criteria

| ID | Test |
|---|---|
| LA1 | Migration 0029 meets G10. `account link` refuses non-loans, two levels, a second aggregate and a stale `al1` |
| LA2 | Net worth adds valuations exactly, with liabilities negative. An unvalued account is listed and not counted, and the incompleteness and mixed-date warnings fire exactly at 31 days |
| LA3 | Subaccounts and aggregate never both counted, over generated link and observation sets, with each branch of point 2 produced |
| LA4 | `--member` parts plus unattributed equal net worth exactly. `--from-statement` makes an observation from a stored closing balance under D-057's checks, and changes no other `balance` command's output |
| LA5 | `report net-worth` and its page agree line for line, read-only |

### M15.2 acceptance criteria

| ID | Test |
|---|---|
| LB1 | Migration 0030 meets G10. Terms refuse a non-loan or non-card account, a rate or payment out of range, a due day outside 1 to 28 unless month-end clamping is stated, and a stale `lt1` |
| LB2 | Graduated schedule: the amount due on each due date is the period in effect, at every step, including a step on the due date itself |
| LB3 | Actual against schedule produces each state exactly, counts only confirmed transfers, and lists unconfirmed payments apart |
| LB4 | A projection matches a hand-computed amortization for 12 months to the cent, half-even, flags negative amortization, stops at 600 months and prints every assumption of point 5 |
| LB5 | Payoff orders follow point 6's ordering and ties, roll payments over, and are deterministic. Every figure is labelled projection |

### M15.3 acceptance criteria

| ID | Test |
|---|---|
| LC1 | Migration 0031 meets G10. `review breakdown` follows D-043 and D-063, and refuses interest + fees > \|amount\|, an unconfirmed or non-loan payment and a stale `t12` |
| LC2 | With breakdowns, D-056's groups add to net movement exactly by amount, Spending rises by exactly the applied interest and fees, Confirmed transfers fall by the same, and the category line moves with them. D-055's warning is withdrawn only where a breakdown applies |
| LC3 | Without breakdowns, `totals`, `report monthly` and `report household` are byte for byte as before. `r14`, `t12`, `d11` and `c7` keep every digest, with `lb1` pinned |
| LC4 | `--loans` asserts its counts and records its figures, `totals` among them, under G9. Every earlier criterion still passes |

---

## D-072 M16 plan: safe-to-spend and the cash-flow constraint — Approved

M16 meets PRD §12's protected funds and cash-flow constraint, and records shared-contract §6's
**safe-to-spend calculation details**. It combines M12 (income and obligations), M13 (budget
capacity), M14 (funds) and M15 (loan schedules) into one figure, and keeps its two constraints
apart:

- **budget capacity,** which is M13's revised allowance;
- **near-term liquidity,** which is what the liquid accounts hold until the next paycheck, less
  every protected fund.

The figure is the lower of the two, with the limiting constraint named. M16 also adds
`pf dashboard`, the summary M17's dashboard page renders. **No security control changes.** No `r`,
`t`, `d` or `c` token moves. Nothing here is stored except the designations and links point 2 adds.

```sh
pf account liquidity set   --db DB --account A --revision lq1-…
pf account liquidity undo  --db DB --account A --revision lq1-…
pf obligation covers       --db DB OBLIGATION_ID (--loan A | --fund FUND_ID) --revision ob1-…
pf obligation uncover      --db DB OBLIGATION_ID --revision ob1-…
pf fund restoration        --db DB --fund EMERGENCY_FUND_ID --monthly AMOUNT --effective-from DATE --revision fu1-…
pf setting set             --db DB checking_buffer_cents AMOUNT --revision st1-…
pf safe-to-spend           --db DB [--as-of DATE] [--explain]
pf dashboard               --db DB [--as-of DATE]
```

**Slices:**

| Slice | Scope |
|---|---|
| M16.1 | Inputs: migration 0032, liquidity designations, obligation coverage links, emergency restoration terms, the checking buffer, `lq1` (points 2 and 4) |
| M16.2 | The engine: the horizon, liquid balance, protected funds in order with no double reservation, the two constraints, the limiting constraint, provisional reasons, `pf safe-to-spend`, `pf dashboard`, its page, the benchmark row (points 1, 3 and 5 to 8) |

**Recommendations, each with its alternatives:**

1. **The horizon runs until the next paycheck.**
   - **N, the next paycheck,** is the earliest nominal date after `as_of` of any `salary` source
     (M12). Side income never counts (PRD §11).
   - **The horizon** runs from `as_of` through N − 1, which is H = N − `as_of` days, at least 1.
   - **A paycheck due but not yet received,** within its tolerance on or before `as_of`, is not
     counted as money: it shows as "expected, not received", and makes the figure provisional.
   - **With no salary source,** the horizon runs to month end, provisional with reason
     `no_salary_source`.
   - Alternatively **a fixed 14-day horizon:** simpler, but it would protect too little before a
     late-month paycheck, or too much after one.

2. **Inputs a person states (M16.1, migration 0032).**
   - **Liquidity designations.** These are the checking and savings accounts that safe-to-spend may
     draw on. Undo then set, with `lq1`. Other account types are refused. **None designated** means
     the liquidity constraint is not evaluated, and the figure is budget-only, labelled
     provisional (`no_liquidity_accounts`).
   - **Coverage links: the explicit no-double-reservation rule.**
     - `obligation covers` says one M12 obligation is the payment of an M15 loan's schedule, or is
       the purchase an M14 reserve saves for. Each obligation covers at most one thing, and each
       loan or reserve is covered by at most one obligation.
     - **Without a link,** the engine checks for two items that look like the same thing: a loan
       whose scheduled amount and due day equal an obligation's amount and day within 3 days, or a
       reserve whose target and due date equal an obligation's within 3 days. Each such pair gives a
       `possible_double_reservation` warning, which marks the figure provisional and names the
       command to link them. It never decides by itself.
   - **Emergency restoration:** a dated monthly amount on the emergency fund, applied only while it
     is underfunded. With none stated, restoration is recommended (D-070) but not protected,
     disclosed.
   - **The checking buffer:** one amount across all liquidity accounts, as setting
     `checking_buffer_cents`. With none, the buffer is 0, disclosed.

3. **The liquid balance, estimated and labelled.**
   - For each liquidity account: its latest observation, plus the effective amounts of its
     transactions after the observation day through `as_of`. Pending outflows are included, pending
     inflows are left out, and inflows of `unknown` status are left out.
   - **`activity_incomplete`** is set when complete coverage, on either basis, does not span every
     day from the observation's next day through the last day the account's documents cover.
     **`stale_observation`** is set when the observation is older than 7 days. Either one marks the
     figure provisional.
   - **No observation** means the account cannot be estimated. It is left out, and the figure is
     provisional, with the account named.
   - The estimate is labelled "estimated from <date>'s observation and activity since". It is never
     shown as a balance, and never enters net worth (D-071 point 1).

4. **Protected funds, in PRD §12's order, each taken once.**

   | Order | Fund | Protected amount |
   |---|---|---|
   | 1 | Side-income tax reserve | The tax fund's required amount (D-070 point 6), less what is assigned to it on non-liquidity accounts, never below zero |
   | 2 | Required bills and minimum debt payments | Every `fixed` obligation's planned amount for occurrences that are `expected` or `missed` with a nominal date in the horizon, and not paid. Plus every loan's scheduled payment due in the horizon and not yet paid (D-071), unless an obligation covers that loan, which then counts only as the obligation |
   | 3 | Annual and irregular expenses | Each reserve's assignment on liquidity accounts, plus its outstanding contribution this month (below). A reserve covered by an obligation counts here and never in row 2 |
   | 4 | Minimum checking buffer | The setting |
   | 5 | Emergency-fund restoration | The emergency fund's assignment on liquidity accounts, plus the stated restoration amount for this month while it is underfunded, less what was assigned to it this month |
   | 6 | Approved savings and extra debt-payment goals | Each goal's assignment on liquidity accounts, plus its outstanding contribution this month |

   - **Outstanding contribution this month:** max(0, the planned contribution for the month − the
     increase in the fund's assignments over the month so far). The increase is computed from
     assignment events dated in the month, in the household's zone. So money set aside this month
     is counted once, either as the assignment or as the plan, never both.
   - **The no-double-count invariant.** Every protected amount carries the planning entry it comes
     from: the tax fund, an obligation, a loan, a reserve, the buffer, the emergency fund or a goal.
     **No entry appears in two rows,** and a test asserts it over generated plans. Assignments on
     non-liquidity accounts are never protected again, since that money is not in the liquid
     balance.
   - **`over_assigned` accounts (D-070).** The difference is treated as unfunded: the affected
     funds protect their full amount, and the figure is provisional.
   - Alternatively **protecting assigned amounts only:** simpler, but bills due before the next
     paycheck would not be protected, against PRD §12's "must not … leave an upcoming obligation
     unfunded".

5. **Two constraints and the limiting one.** S, the surplus, is the liquid balance − Σ protected.

   | Figure | Definition |
   |---|---|
   | Liquidity daily | floor(S ÷ H) when S > 0, else 0 |
   | Liquidity weekly | floor(S × min(7, H) ÷ H) when S > 0, else 0 |
   | Budget daily and weekly | M13's revised household allowances (D-069 point 4) |
   | **Safe to spend today, and this week** | The lower of the two in each, never below 0 |
   | Limiting constraint | `budget`, or `liquidity`, naming the largest protected row and its largest item. On equal figures, `liquidity` |
   | Shortfall | When S < 0: "short by \|S\| before the next paycheck on N", the rows that cause it, and safe to spend 0. Never a negative allowance (PRD §12) |

   - **Card spending.** Purchases on a card reduce budget capacity when made (M13). They reduce
     liquidity only through the card's payment obligation (row 2). **A card with activity in the
     last 60 days and no payment obligation** gives `card_without_payment_obligation`, making the
     figure provisional, since its payment would otherwise go unprotected.
   - Alternatively **one combined figure with no limiting constraint:** simpler, but PRD §12
     requires "show the constraint limiting the allowance".

6. **Provisional reasons, an enumerated list.** The figure is labelled "provisional" while any reason
   holds, and every reason is printed with what would clear it:

   | Reason | Clears when |
   |---|---|
   | `no_salary_source` | A salary source is confirmed (M12) |
   | `paycheck_expected_not_received` | The deposit arrives, or the tolerance passes and it is `missed` |
   | `no_liquidity_accounts` | An account is designated (point 2) |
   | `stale_observation` | A balance is recorded within 7 days |
   | `activity_incomplete` | Coverage spans the gap after the observation |
   | `unvalued_liquidity_account` | A balance is recorded for the account |
   | `possible_spending` | M13's unclassified and unconfirmed transfer-kind money out is classified |
   | `open_review_items` | No open review item touches a liquidity account in the horizon |
   | `card_without_payment_obligation` | An obligation is added for the card's payment |
   | `over_assigned` | Assignments are released, or a higher balance is observed (D-070) |
   | `possible_double_reservation` | The pair is linked, or shown to be distinct |
   | `no_budget_plan` | A plan is in effect for the month. Until then the budget constraint is absent and the figure is liquidity-only |

   **Missing the household timezone refuses** (G7), and is never provisional.

7. **`pf dashboard`, and keeping it fast.**
   - The dashboard's lines come from one builder in `report_text.py`, so M17's page renders them:
     - safe to spend, with its constraint and reasons;
     - M13's pace;
     - fund states (D-070);
     - net worth, with valuation dates (D-071);
     - this month's income against baseline (M12);
     - review counts;
     - each account's freshness: the last covered day, and the last import's date.
   - **It never calls `totals`, and never runs the transfer candidate search.** That answers
     D-066 point 8: the search stays in `totals`, and the dashboard counts unconfirmed transfer kinds
     from D-056's groups, which need no candidates. **Targets** (G9): `safe-to-spend` and `dashboard`
     below 1.0s each.
   - **Sync freshness (shared-contract §5):** freshness is per account and states institution-data
     dates, never "now", so M19 and M20 carry it as is.

8. **Tokens, parity and performance.**
   - `lq1` covers an account's designation.
   - Coverage links use `ob1` with the operation `covers`.
   - Restoration terms use `fu1`, and the buffer uses `st1`.
   - Every existing command is byte for byte unchanged (G6). The engine is read-only.
   - **The benchmark row** is `--safe-to-spend`: the union of the `--recurring`, `--budget`,
     `--funds` and `--loans` shapes, with 3 liquidity accounts, a buffer and links. It asserts that
     every protected row is non-empty and that each limiting branch is reached in some `as_of`. It
     times `safe-to-spend` and `dashboard` at 12 `as_of` dates, reporting the slowest.

**Shared-contract §6 record: the safe-to-spend calculation details are points 1 to 6 of this
decision,** once approved.

**Not in M16:** safe to spend per member, intra-day timing, forecasts beyond the next paycheck
(M18's scenarios do that), automatic linking of duplicate reservations, and notifications.

**Inputs needed from the owner:** the checking buffer (PRD §22), which accounts are liquid, the
links between obligations and loans or reserves, and the emergency restoration amount.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** A horizon to the next salary paycheck, with side income never counted (point 1).
  Alternatively a fixed 14 days.
- **B.** Liquidity designations, explicit coverage links, warnings for possible double reservations,
  a restoration amount and one buffer (point 2).
- **C.** The liquid balance as observation plus activity since, labelled as an estimate (point 3).
- **D.** Protected funds in PRD §12's order, each entry taken once, with outstanding contributions
  computed from assignment events (point 4).
- **E.** Safe to spend as the lower of budget and liquidity, with the limiting constraint and
  shortfalls shown, never negative (point 5).
- **F.** The enumerated provisional reasons (point 6).
- **G.** `pf dashboard` without `totals` or the candidate search, below 1.0s (point 7).
- **H.** Migration 0032, `lq1`, and `--safe-to-spend` (point 8).
- **I.** The slices M16.1 and M16.2, in that order.

### M16.1 acceptance criteria

| ID | Test |
|---|---|
| SA1 | Migration 0032 meets G10 and seeds `checking_buffer_cents`. Designation refuses non-checking and non-savings accounts and a stale `lq1`. Coverage links refuse a second link on either side and a stale `ob1` |
| SA2 | Possible double reservations are found exactly at the 3-day edges, for loans and for reserves, and a link clears each |
| SA3 | `evidence_digest` is unchanged by every M16 write. Every existing command is byte for byte as before |

### M16.2 acceptance criteria

| ID | Test |
|---|---|
| SB1 | The horizon: N for weekly, biweekly and semimonthly sources at month ends, a payday equal to `as_of`, an unreceived paycheck within its tolerance, and no source |
| SB2 | The liquid balance is the observation plus activity, with pending outflows in and pending inflows out, and `activity_incomplete` and `stale_observation` fire exactly at their edges |
| SB3 | Each protected row computed by hand. No entry appears in two rows, over generated plans with links, unlinked look-alikes, reserves covered by obligations and loans covered by obligations |
| SB4 | Money assigned this month is counted once, as an assignment or as an outstanding contribution, never both: assigning the planned amount mid-month leaves the protected total unchanged |
| SB5 | Safe to spend is the lower of the two constraints, with the constraint named, ties to liquidity, a shortfall shown with safe to spend 0, and every provisional reason produced and cleared by its stated action |
| SB6 | Third paycheck: the extra changes neither the budget constraint nor the horizon's protected amounts. It reaches liquidity only as money actually received |
| SB7 | `safe-to-spend` and `dashboard` open read-only, call no candidate search (a test replaces it with a failure), and the dashboard page equals the command line for line. `--safe-to-spend` records its figures under G9. Every earlier criterion still passes |

---

## D-073 M17 plan: the local UI completed, with browser writes — Approved, a security change

M17 meets PRD §18:

- the seven sections, the eight required visuals and CSV export;
- PRD §10's tags and search;
- writes from the browser, by D-066 point 5, so M18's scenarios can be entered in the UI as PRD §15
  requires.

**Browser writes change a security control** (D-062's "`GET` only"). Point 1 is written to be
approved as one security change. Nothing else in D-062 relaxes:

- loopback only;
- the system-chosen port;
- the exact Host;
- the one-use launch key;
- the `HttpOnly`, `SameSite=Strict` cookie;
- no script;
- no logging;
- the gate on every request.

```sh
pf ui                      --db DB            # unchanged launch; pages gain forms (M17.1)
pf transactions            --db DB [--search TEXT] [--account A] [--from DATE] [--to DATE] \
   [--category NAME] [--tag NAME] [--min AMOUNT] [--max AMOUNT]    # M17.3
pf tag add                 --db DB NAME
pf tags                    --db DB
pf review tag              --db DB --account A TRANSACTION_ID --tags NAME,NAME|--none --revision t13-… \
   [--supersedes ID --supersedes-revision tg1-…]
pf review tagging show     --db DB TAG_STATEMENT_ID
pf review tagging undo     --db DB --account A TAG_STATEMENT_ID --revision tg1-…
pf export transactions     --db DB --out PATH [--account A] [--from DATE] [--to DATE]   # M17.4
pf export report           --db DB --out PATH (totals|monthly|budget|funds|net-worth|household) [scope options]
```

**Slices:**

| Slice | Scope |
|---|---|
| M17.1 | The write pipeline (the security change), and review decisions from the browser: M8.4's UD1 to UD4, revived and extended (points 1 and 2) |
| M17.2 | The remaining sections: accounts and members, budgets, goals and planned expenses, settings and backups, and planning writes from the browser on point 2's allowlist (point 3) |
| M17.3 | Search and tags (migration 0033, `tg1`, `r15`, `t13`, `d12`, `c8`), and the eight visuals as script-free SVG (points 4 to 6) |
| M17.4 | CSV export from the terminal to a gated destination (point 7) |

**Recommendations, each with its alternatives:**

1. **The write pipeline: every `POST` passes all of these, in this order, before any ledger is
   opened for writing.** Each step's refusal is a fixed page that repeats nothing from the request,
   and changes nothing.
   1. The exact Host, as now (`421`).
   2. A valid session cookie, as now (`403`).
   3. **The method is `POST`, and the route is on the allowlist** (point 2). Any other method is
      `405`, and any other route `404`.
   4. **`Origin` is present and exactly `http://127.0.0.1:<port>`.** A missing or foreign one is
      `403`.
   5. **`Sec-Fetch-Site`, if present, is `same-origin`,** and **`Sec-Fetch-Mode`, if present, is
      `navigate`.** Otherwise `403`.
   6. **`Content-Type` is exactly `application/x-www-form-urlencoded`,** `Content-Length` is
      present and at most 8,192, and there is no `Transfer-Encoding`. Otherwise `415` or `413`, with
      the body unread.
   7. **The body is parsed strictly:** at most 50 fields, no repeated field, no unknown field for
      the route, UTF-8. Otherwise `400`.
   8. **The form token.**
      - Each session holds a 32-byte secret from `secrets`, in memory only.
      - Each rendered form carries HMAC-SHA256(secret, route, form ID, every revision token the
        form shows), compared with `hmac.compare_digest`.
      - A token is **single-use**: kept in a per-session set of used tokens, refused when seen
        twice.
      - A wrong, missing, reused or other-session token is `403`.
   9. **The write itself is G3's function, the same one the CLI calls.** It opens through the gate
      with a write connection (UD4), checks that the accounts are current, and checks the revision
      tokens from the form under the write lock. It never reconciles, and a stale account gives the
      CLI's message (UD1).
   10. **Post/Redirect/Get.** Success gives `303` to a result page naming what was made (IDs and
       the undo command). A refusal gives a page with the CLI's refusal text, which repeats no input
       (UD3).
   - **CSP** adds `form-action 'self'` and keeps `default-src 'none'`, no script and no inline
     style. Forms work without script.
   - **W1 is unchanged:** `urllib.parse` parses bodies, and the server's imports stay as UB1.
   - **The server stays one request at a time.** A write holding the lock blocks other pages for at
     most its own duration, measured.
   - **Threats covered, each by a test with a control that succeeds:**
     - a cross-site form from another origin or port;
     - DNS rebinding (the Host check);
     - a replayed form;
     - a double submit;
     - a request with a stale revision token;
     - a body over the limit;
     - an `Origin` of `null`;
     - a page in a frame (`DENY`, as now);
     - a `GET` with write parameters, which never writes.
   - Alternatively:
     - **A JSON API with fetch:** needs script, and with it a weaker CSP.
     - **`SameSite` alone, without form tokens:** defends against cross-site requests, but not
       against a same-site page on another loopback port, which shares the cookie (status.md's
       known limitation).

2. **The allowlist of browser writes (the owner's input).**
   - **Recommended in the browser:**
     - review decisions: reject, confirm, separate and undo;
     - corrections, completions, dismissals and coverage declarations;
     - classification, categorization, allocation, consumption, breakdown and tagging;
     - category rules: preview, then add, with `p1`;
     - transfer matches and one-sided transfers;
     - balance observations;
     - income sources and obligations, from proposals or typed;
     - budget plans;
     - funds, assignments and priority;
     - liquidity designations and coverage links;
     - the checking buffer;
     - scenarios (M18).
   - **Terminal only:**
     - `init`, `migrate`, `import`, `reconcile`;
     - `account add` and `account link`;
     - `backup`, `archive`, `storage`;
     - `export` (point 7);
     - the `household_timezone` setting;
     - everything in `sync` (M20).

     That is, anything that reads or writes a path, changes the gate's subject, changes what "today"
     means, or touches devices.
   - Each allowed route maps to exactly one core function. A test asserts that the route table and
     the allowlist are equal.

3. **The sections, each a builder's lines (D-062).**

   | Section (PRD §18) | Pages |
   |---|---|
   | Dashboard | M16's `dashboard` |
   | Transactions and search | Point 4 |
   | Import results and review queue | As M8, now with decision forms |
   | Accounts and members | Accounts with types, freshness, liquidity and links. M11's members, share and defaults |
   | Budgets, goals and planned expenses | `report budget`, `report funds`, `report income`, obligations |
   | Scenarios | M18 |
   | Settings and backups | Settings in effect, `pf storage`, and the backup records (0018), read-only. A backup is made in the terminal |

   Every page gets M8's parity test against its command. F2 holds: no page shows a creation
   timestamp.

4. **Search, read-only.** The transactions page and `pf transactions` take the same filters:
   - text, as D-064's normalized "contains" on the effective description;
   - account, date range, effective category, tag, and an amount range in cents.

   Each filter is parsed strictly, refused when malformed, and shown back escaped. The results are
   capped at 500 rows, with a count of the rest. A plain scan over 100,000 rows is expected well
   under the target, so there is no index unless a measurement asks for one (principle 4).

5. **Tags (M17.3, migration 0033).**
   - A tag list, append-only as categories (D-063). A **tag statement** gives a transaction's set
     of tags, possibly empty.
   - It is the sixth stated kind, on D-065's canonical multi-part value: tag IDs, sorted.
   - Tags are free labels: they enter no total. They filter search and the exports.
   - Tokens: `tg1`, and `r15`, `t13`, `d12` and `c8`, each keeping its digests while no statement
     reaches.
   - Alternatively **tags without statements,** stored on the transaction: against D-049 (values
     are kept apart), and with no undo.

6. **The eight visuals, as script-free SVG.**
   - Each chart is drawn by a builder from the same rows as a table printed beneath it: category
     spending, spending over time, target against actual pace, goal progress, household comparison,
     income and cash flow, debt history, and net worth with valuation dates.
   - The SVG is inline, uses presentation attributes only (no `style` attribute and no `<style>`),
     and gives each mark a `<title>` carrying its value. Its colours come from a fixed, tested
     palette that keeps contrast in light and dark modes.
   - **A test parses each SVG** and asserts that each mark's value equals its table cell, and that
     no script, event attribute, external reference or `style` is present.
   - **Before building, check in a real browser** that the CSP allows presentation attributes, as
     the handoff's lesson on outside tools asks.
   - Alternatively **a charting library:** needs script and a dependency, against D-062 and D-020.

7. **CSV export from the terminal, to a gated destination (M17.4).**
   - `pf export` writes a new file only. The destination must pass the real-ledger folder checks
     (D-058): not in a git work tree, not in a synced folder, not through a link, private, and for a
     real ledger inside an encrypted image. The file is `0600`, and an existing file is refused.
   - **Money** is a decimal string (`-12.34`), dates are ISO, missing values are empty and never
     `0` (shared-contract §4), and the columns are fixed and documented.
   - **Cells are protected against formula injection:** a cell starting with `=`, `+`, `-`, `@`,
     tab or CR is prefixed with `'`. Amounts are an exception and keep their sign, since they are
     never text.
   - **The browser shows the command, and offers no download:** a download lands in `~/Downloads`,
     which is unencrypted and may be synced. Alternatively **a browser download with a warning:**
     easier, but it places real data outside the gate.

8. **Tokens, parity and performance.**
   - The form token is a session secret, not a revision token. Revision tokens are unchanged, apart
     from point 5's.
   - **Commands that may change output:** `pf transactions`, which gains filters (with none given,
     it is byte for byte as before); `review show` and `review transaction show`, which gain "Tags"
     where a statement reaches. Every other command is held by G6.
   - **Targets:** every page below 2.0s, the dashboard page below 2.0s, search below 2.0s, and a
     browser write within 0.1s of the same CLI write. **The benchmark row** is `--ui`: every page at
     the `--safe-to-spend` shape, and 50 sequential `POST` decisions, timed per request.

**Not in M17:** script of any kind, PDF or image export (PRD §18: later), the UI on any address but
loopback, separate logins, decision history pages (they need F2), and browser downloads.

**Inputs needed from the owner:** which writes the browser may make (point 2), and whether the
terminal-only list is right.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Approve browser writes as one security change, by point 1's pipeline.** Alternatively stay
  read-only and enter scenarios in the terminal (D-066 point 5's alternative).
- **B.** Point 2's allowlist and terminal-only list.
- **C.** The sections as builders with parity tests (point 3).
- **D.** Read-only search with strict filters (point 4).
- **E.** Tags as a stated kind, with migration 0033 and the token bumps (point 5).
- **F.** Script-free SVG visuals, tested against their tables (point 6).
- **G.** CSV export from the terminal only, gated, protected against formula injection (point 7).
- **H.** The `--ui` benchmark row (point 8).
- **I.** The slices M17.1 to M17.4, in that order.

### M17.1 acceptance criteria

| ID | Test |
|---|---|
| WA1 | Each pipeline step refuses alone, on a request correct in every other respect, with the same request passing as the control (UD2) |
| WA2 | A form token is single-use, bound to its session, route and shown revision tokens. Reuse, another session's token, a changed hidden revision and a missing token are each refused, changing nothing |
| WA3 | A decision from the browser equals the same CLI decision: the same rows, the same logical digest afterwards. A stale revision token or stale account refuses with the CLI's message, and the UI never reconciles (UD1) |
| WA4 | Post/Redirect/Get: a reload of the result page writes nothing, and a resubmitted form refuses (UD3). No refusal page repeats a request value, tested with sentinels |
| WA5 | Each `POST` opens through the gate, and a real ledger whose probe fails refuses with no write (UD4). No request writes to stdout or stderr. Every earlier criterion still passes |

### M17.2 acceptance criteria

| ID | Test |
|---|---|
| WB1 | Each section's pages equal their commands line for line, with names holding HTML shown as text |
| WB2 | The route table equals point 2's allowlist, and each terminal-only command has no route. A `POST` to any other path is `404` |
| WB3 | Each planning write from the browser equals its CLI write, including refusals |

### M17.3 acceptance criteria

| ID | Test |
|---|---|
| WC1 | Migration 0033 meets G10. Tag statements follow D-063 and D-065's multi-part model. `r15`, `t13`, `d12` and `c8` keep every digest without tags, with `tg1` pinned |
| WC2 | Search filters each select exactly, compose with AND, refuse malformed values, and cap at 500 with the rest counted. `pf transactions` with no filter is byte for byte as before |
| WC3 | Each SVG's mark values equal its table. No script, event attribute, external reference or `style` is present, and a real-browser check of the CSP is recorded |

### M17.4 acceptance criteria

| ID | Test |
|---|---|
| WD1 | Export refuses an unsafe or existing destination, writing nothing, and writes `0600`. A cell starting with each formula character is prefixed. Money round-trips exactly, and missing is empty |
| WD2 | `--ui` records its figures under G9. Every earlier criterion still passes |

---

## D-074 M18 plan: financial scenarios — Approved

M18 meets PRD §15:

- an active baseline plus named alternatives;
- dated inputs of every listed kind, each carrying PRD §15's six distinctions;
- comparison on request, with absolute values and differences;
- conservative defaults, with uncertain income left out unless enabled;
- promotion only on explicit confirmation;
- actual history never altered.

It closes the Phase 1B backlog's "Financial scenarios". Scenario inputs are entered in the UI
through M17's pipeline, and in the terminal. **No security control changes** beyond M17's.

```sh
pf scenario add            --db DB --name NAME [--include-uncertain]
pf scenario input add      --db DB SCENARIO_ID --kind KIND --amount AMOUNT --from DATE [--to DATE] \
   [--cadence (once|monthly:D|biweekly --anchor DATE|annual:MM-DD)] [--replaces ENTRY_ID] \
   [--uncertain] [--gross --take-home-percent PCT] [kind options] --revision sc1-…
pf scenario input undo     --db DB SCENARIO_ID INPUT_ID --revision sc1-…
pf scenarios               --db DB
pf scenario show           --db DB SCENARIO_ID
pf scenario compare        --db DB SCENARIO_ID [--months N] [--as-of DATE]
pf scenario promote        --db DB SCENARIO_ID --revision sp1-…
pf scenario promotion undo --db DB SCENARIO_ID --revision sp1-…
pf scenario undo           --db DB SCENARIO_ID --revision sc1-…
```

The kinds are `income`, `bonus`, `expense`, `annual_expense`, `purchase`, `home_purchase`,
`loan_payoff` and `borrowing`. Their options are in point 2.

**Slices:**

| Slice | Scope |
|---|---|
| M18.1 | Scenarios and inputs: migration 0034, every kind with PRD §15's six distinctions, replacement references, `sc1` (points 1 and 2) |
| M18.2 | The projection engine and comparison: baseline and scenario from one pure function, every output, conservative defaults, double-count prevention, `scenario compare`, its UI pages and forms (points 3 to 5) |
| M18.3 | Promotion and its undo, `sp1`, the actual-history guarantee, the benchmark row (points 6 to 8) |

**Recommendations, each with its alternatives:**

1. **The baseline is the active plan, read live, and is never copied.**
   - **The baseline** is M12 to M16's entries in effect as of `as_of`: sources, obligations, the
     budget plan, funds, assignments, priority, loan terms, the payoff plan, liquidity and the
     buffer. Nothing is stored as a "baseline scenario": copying it would create a second plan that
     drifts from the first.
   - **A scenario** is a name, a flag for including uncertain inputs, and its inputs. All are
     append-only, with events (G2). Changing an input is undo then add.
   - **When a replaced entry is undone or superseded** after the input was made, the input becomes
     **`target_changed`**. It is disclosed and left out until the person undoes it and adds it
     again. It never silently applies to a different entry.
   - Alternatively **a stored baseline per scenario:** comparisons stay stable as the plan changes,
     but each scenario then answers against a plan the owner no longer has.

2. **Inputs, each with PRD §15's distinctions.**

   | Distinction | Stored as |
   |---|---|
   | Amount | Cents. Money out positive in the input, signed by kind |
   | Effective date or date range | `from`, and an optional `to`, inclusive |
   | One-time or recurring | `once`, or an M12 cadence with an anchor |
   | Replacement or additional | `replaces` naming one entry ID of a matching kind (a source for `income`; an obligation for `expense`; a reserve for `annual_expense`; loan terms for `loan_payoff`), or none |
   | Confirmed or uncertain | A flag. Uncertain inputs count only in a scenario with `--include-uncertain` |
   | Take-home or gross | Take-home by default. `--gross` requires `--take-home-percent`, applied once and rounded down (G8). Gross without it is refused |

   **Kind options:**
   - `home_purchase` takes `--price`, `--down-payment`, `--closing-costs`, `--loan-rate`,
     `--loan-months` and `--ownership-costs AMOUNT/month`. It expands into its parts: a one-time
     outflow, a projected loan, a recurring expense, and a **scenario asset** valued at the price.
     That asset is never in actual net worth (PRD §17).
   - `borrowing` takes the rate, term and proceeds.
   - `loan_payoff` takes a loan account and an amount.
   - `bonus` is one-time income, uncertain by default.

3. **One pure projection, run twice.**
   - `project(plan, inputs, as_of, months)` is a pure function. The baseline is
     `project(plan, [], …)` and the scenario `project(plan, inputs, …)`. Both run on request, and
     nothing is stored (PRD §15: "after the user requests recalculation").
   - **The horizon** defaults to 24 months, at most 120, starting from `as_of`'s month.
   - **Each month projects:**

     | Projected item | Rule |
     |---|---|
     | Income | Salary by nominal dates, extra paychecks included as cash. Side income only from confirmed inputs |
     | Fixed obligations | At their planned amounts |
     | Discretionary spending | At the budget target in full (conservative: plans are assumed met, never underspent) |
     | Funds | Planned contributions to goals and reserves, tax accrual on eligible income |
     | Loans | Payments by schedule, with M15's projection assumptions for balances |
     | Starting liquid balance | M16's estimate, carried month by month |

   - **The outputs** are PRD §15's list. Each is absolute for both runs, plus the difference:
     - monthly cash flow;
     - each month's daily and weekly allowances (D-069's formulas on the target, capped by projected
       liquidity, M16's rule taken monthly);
     - required saving to meet each goal by its deadline;
     - goal completion months;
     - debt balances and net worth, both labelled projection, with scenario assets apart;
     - cash shortfalls, the months when liquidity falls below the protected amount;
     - unmet goals;
     - assumptions and missing inputs, listed.
   - **Conservative defaults:** uncertain inputs are left out, bonuses are uncertain, discretionary
     spending is at target, and projected interest follows M15's half-even rounding with every
     assumption printed.
   - Alternatively **a daily simulation:** more precise around paydays, but harder to check by
     hand. Monthly matches PRD §15's "monthly cash flow" and the budget's period.

4. **No double counting when a scenario changes the plan (PRD §15).**
   - **A replacement** removes the replaced entry's effect over the input's range only, and adds
     the input's. Outside the range the entry applies as before.
   - **An additional input that looks like a baseline entry** (same kind, account, cadence, an
     amount within 1%, dates overlapping) gives `possibly_already_planned`. It is disclosed, and
     counts as typed: it is never merged silently.
   - **Proved:**
     - replacing a salary gives exactly the new amount in its range;
     - an additional duplicate of an obligation counts twice and is flagged;
     - a scenario with no inputs gives outputs identical to the baseline, byte for byte.

5. **Its pages and forms.** Scenario list, scenario detail with an input form for each kind, and
   the comparison. Each page is a builder's lines with parity against `scenario show` and
   `scenario compare`, and each form goes through M17's pipeline. Recalculation is a `GET` of the
   comparison page, which writes nothing.

6. **Promotion: explicit, atomic, reversible.**
   - `scenario promote` turns every **confirmed** input into planning entries, through the same
     functions the CLI's planning commands call, in one transaction:

     | Input | Becomes |
     |---|---|
     | A replacement | A new terms row on the replaced entry, from the input's date (G2) |
     | Additional recurring income or expense | A new source or obligation |
     | A one-time purchase or `annual_expense` | A reserve (D-070) with the target and due date |
     | `loan_payoff` | An extra-payment assumption in the payoff plan |

   - **Not promotable, and listed:** uncertain inputs, `borrowing` and `home_purchase` (they need an
     account that does not exist yet), and scenario assets.
   - **`sp1` covers** the scenario, every input, and every entry it replaces with that entry's own
     token, so a plan changed since the comparison refuses.
   - `scenario_promotion_entry` links each created entry to its input. **Promotion undo** undoes
     every created entry in one transaction. It refuses, naming the newer change, if any created
     entry has been superseded since.
   - Alternatively **promotion one input at a time:** finer control, but PRD §15 promotes "a
     scenario".

7. **Actual history is never altered.** Every scenario command, including promote and its undo,
   leaves `evidence_digest` unchanged (G1). Actual net worth (D-071) is byte for byte the same with
   any scenario present. Promotion writes planning entries only.

8. **Tokens, parity and performance.**
   - `sc1` covers a scenario's inputs and their states. `sp1` is point 6's.
   - Every existing command is byte for byte unchanged (G6).
   - **Targets:** `scenario compare` below 2.0s at 24 months and 5.0s at 120 (G9). The cost is
     plan size × months, and the starting state is M16's estimate.
   - **The benchmark row** is `--scenarios`: 10 scenarios with 40 inputs of every kind, including
     replacements and a home purchase, on the `--safe-to-spend` shape. It times compare at 24 and
     120 months, and promote.

**Not in M18:** Monte Carlo or probability, inflation or market returns (an input could add a growth
rate later), tax calculation (PRD §4), stored results, scenarios in actual reports, and scenarios
from the phone.

**Inputs needed from the owner:** none beyond earlier milestones (D-066). Optionally, the first
scenario to model, such as a home purchase, to shape the fixtures.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** A live baseline, never copied. Inputs referencing replaced entries become `target_changed`
  when those entries change (point 1).
- **B.** Point 2's inputs and distinctions, with gross requiring a take-home percentage.
- **C.** One pure monthly projection, run for both sides, with conservative defaults and nothing
  stored (point 3). Alternatively a daily simulation.
- **D.** Replacement by range, and look-alike additions flagged, never merged (point 4).
- **E.** Atomic promotion of confirmed inputs, with `sp1` over the replaced entries, and an undo
  (point 6).
- **F.** Migration 0034, `sc1`, `sp1`, and `--scenarios` (point 8).
- **G.** The slices M18.1 to M18.3, in that order.

### M18 acceptance criteria

| ID | Test |
|---|---|
| XA1 | Migration 0034 meets G10. Each kind and distinction is stored and refused as point 2: gross without a percentage, a replacement of the wrong kind, a `to` before `from`, a stale `sc1` |
| XA2 | A replaced entry undone or superseded makes its input `target_changed`, left out and disclosed |
| XB1 | A scenario with no inputs equals the baseline byte for byte. Replacing a salary counts only the new amount in range. A look-alike addition counts and is flagged |
| XB2 | Uncertain inputs count only with `--include-uncertain`. Discretionary spending projects at target. Every output of point 3 is present, absolute and as a difference, with assumptions and missing inputs listed |
| XB3 | A 12-month projection is computed by hand to the cent, including a home purchase's parts. Scenario assets never reach actual net worth |
| XB4 | `scenario compare` and its page agree line for line. Each form follows M17's pipeline, and a `GET` writes nothing |
| XC1 | Promotion creates exactly the mapped entries in one transaction, is refused with a stale `sp1` or a changed replaced entry, and lists what is not promotable. Undo restores the plan's every token, and refuses after a later supersession |
| XC2 | `evidence_digest` is unchanged by every scenario command. `--scenarios` records its figures under G9. Every earlier criterion still passes |

---

## D-075 M19 plan: snapshots — Approved

M19 meets shared-contract §3 and §4, and records §6's **snapshot compatibility policy**. A snapshot
is:

- versioned;
- generated from one consistent database state;
- holding §3's contents and none of its exclusions;
- deterministic given its inputs;
- written to a gated file, with no network.

That file is also M20's local-only fallback (D-066 point 6). **No security control changes:** it is
a new kind of file leaving the ledger folder, gated as M17's export is (G11).

```sh
pf snapshot create  --db DB --out PATH [--as-of DATE] [--window-days 90]
pf snapshot verify  PATH [--db DB]
pf snapshots        --db DB
```

**Slices:**

| Slice | Scope |
|---|---|
| M19.1 | The builder and the format: canonical JSON, the envelope, every §3 section, value kinds, exclusions, the schema document and its validator, golden fixtures (points 1 to 3, 5) |
| M19.2 | Creating, verifying and listing: one read transaction, the gated atomic write, migration 0035's `snapshot_record`, `snapshot verify`, the benchmark row (points 4, 6 and 7) |

**Recommendations, each with its alternatives:**

1. **One canonical JSON file.**
   - **Encoding:** UTF-8, keys sorted, no insignificant whitespace, no NaN, and **no floats
     anywhere.** The builder refuses one, as a test proves.
   - **The envelope:**

     | Field | Holds |
     |---|---|
     | `format` | `"commoncents-snapshot"` |
     | `schema_version` | `"1.0"` |
     | `snapshot_id` | A UUID4 |
     | `generated_at` | RFC 3339 UTC with milliseconds and `Z` |
     | `content_sha256` | The SHA-256 of `content`'s canonical bytes |
     | `content` | The snapshot itself |

   - **Deterministic:** the same ledger state, `as_of`, window, `snapshot_id` and `generated_at`
     give identical bytes. The CLI supplies the ID and the time, and tests inject them.
   - Alternatively **SQLite as the snapshot format:** the phone could query it, but a database file
     carries free pages and whatever the schema holds, which is harder to prove free of excluded
     data.

2. **Contents, by shared-contract §3.** Each item maps to its source:

   | §3 item | `content` section | Source |
   |---|---|---|
   | Financial-data cutoff and per-account freshness | `cutoff`, `accounts[].freshness` | `as_of`. Per account: the last covered day on each basis, the last import date and the latest observation date (D-072 point 7) |
   | Household timezone | `household.timezone` | G7 |
   | Reporting period | `period` | `as_of`'s month and the window |
   | Household members and allocations | `household` | M11's members, share and defaults, and per month the members' and unattributed totals |
   | Spending summaries | `months[]` | Per month over the full history: D-056's five groups and spending by category, as `report monthly` |
   | Original and revised allowances | `budget`, `safe_to_spend` | M13 and M16, with constraint and reasons |
   | Goals and assigned funds | `funds` | M14 |
   | Debt summaries | `loans` | M15: observed balances, schedule states, projections labelled |
   | Net worth and valuation dates | `net_worth` | M15 |
   | Selected transaction history | `transactions[]` | The last `window_days` days (1 to 366, default 90): each transaction's ID, effective date, effective amount, effective description, account reference, type, category with its source, tags, member parts, status and unsettled flags |
   | Material warnings | `warnings[]` | Coverage gaps, provisional reasons, `over_assigned`, unsettled statements, possible duplicates affecting totals |
   | Review counts | `review` | Open items by kind |
   | Calculation assumptions | `assumptions` | M15 point 5, M16 points 1 to 6, the rounding of G8, `MatchingRules` version |

3. **Exclusions, enforced by a test.**
   - **Left out:**
     - raw rows and original cells;
     - file names, document hashes and paths;
     - external IDs and record IDs;
     - `last4` and institution;
     - source descriptions where a correction applies (the effective one is sent);
     - creation timestamps of any row (so F2 is not needed);
     - device and pairing data.
   - Accounts are referenced by a snapshot-local index, with display name and type only.
   - **The test** seeds a ledger with sentinels in every excluded field, builds a snapshot, and
     asserts that no sentinel appears anywhere in its bytes.
   - Alternatively **all fields, filtered on the phone:** simpler for the backend, against §3's
     "exclude".

4. **One consistent state.**
   - Every section is built from **one read-only connection inside one read transaction**. Each
     builder takes the connection and never opens its own.
   - In the rollback-journal mode a real ledger uses, that shared lock holds writers off until the
     snapshot is built. So a writer waits, and reports `database_busy` beyond 5 seconds. Generation
     must stay below G9's 5s.
   - **Proved:** a writer committing during generation gives a snapshot equal to the one built on
     the state before the write, or on the state after it, never a mix. Shown by building both and
     comparing.

5. **The compatibility policy (shared-contract §6).**
   - `schema_version` is MAJOR.MINOR.
     - **A minor version** may only add optional fields or enum values that a consumer may ignore.
     - **A major version** is any removal, rename, type change, meaning change, or newly required
       field.
   - A consumer accepts any minor of a major it supports, and ignores unknown fields. It refuses an
     unknown major with an actionable error naming both versions (shared-contract §5).
   - **The backend emits exactly one version per release.**
   - **A field to be removed** is marked deprecated in the schema document for at least one minor
     version first.
   - **Machine-checked:** `snapshot/schema_v1.json` describes every field, its type, its value kind
     and whether it may be null. `snapshot/validate.py` checks a snapshot against it. It is a
     standard-library subset validator (types, required, enums, patterns), so there is no new
     dependency.
   - **Golden fixtures** under `tests/fixtures/synthetic/snapshots/v1.0/` are pinned byte for byte
     from fixed synthetic ledgers. Any change to the builder fails until the fixture is updated with
     a conscious minor or major bump, which a test checks against the schema's diff.

6. **Representation (shared-contract §4).**
   - Money is integer cents, in fields named `*_cents`.
   - Dates are `YYYY-MM-DD`, and timestamps RFC 3339 UTC.
   - Missing values are `null`, never `0`.
   - **Every `*_cents` field has one value kind** (`actual`, `projected`, `reserved` or
     `allocated`), declared in the schema. A test fails on an undeclared field.
   - Allocations reconcile exactly: `snapshot verify` checks that members plus unattributed equal
     each total, that the five groups add to net movement per month, and that categories add to
     spending.

7. **Creating and verifying.**
   - `snapshot create` writes a new file only, to a destination passing M17's export checks,
     `0600`. The write is atomic:
     1. write a temporary file in the same folder;
     2. `fsync` it;
     3. `os.link` it to the final name, which fails if the name exists;
     4. remove the temporary file;
     5. `fsync` the folder.
   - It then records the ID, schema version, `as_of`, window, `generated_at` and digest in
     `snapshot_record` (migration 0035), append-only. The path is not recorded. **If recording
     fails,** the file stays and the failure is reported. Nothing is retried silently.
   - `snapshot verify PATH` checks the envelope, the digest, the schema, point 6's invariants and
     point 3's exclusions (by key, as names). It writes nothing. With `--db`, it also confirms the
     record.
   - **The file is sensitive and unencrypted by M19,** so it is kept on the encrypted image.
     Carrying it to the phone by hand (AirDrop, or a cable) is the owner's act, documented as M20's
     fallback. Encrypting the file needs M20's key material, and is not in M19.

**Performance.** The work is one pass of each report's builder plus the window's transactions.
**The benchmark row** is `--snapshot`, on the `--safe-to-spend` shape with 60 months and a 90-day
window holding about 5,000 transactions. It records generation time (below 5.0s), file size (below
5 MB) and verify time.

**Not in M19:** encryption of the file, a network, incremental or delta snapshots, phone writes
(shared-contract §5: read-only first), and scenario results. They are not in §3's list, and adding
them later is a minor version.

**Inputs needed from the owner:** the transaction window (90 days proposed), and whether
institution names may appear on the phone.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** Canonical JSON with an envelope and a content digest, with no floats, and deterministic
  (point 1). Alternatively SQLite.
- **B.** Point 2's sections and point 3's exclusions, proved with sentinels.
- **C.** One read transaction for the whole snapshot (point 4).
- **D.** The MAJOR.MINOR compatibility policy, a standard-library validator and golden fixtures
  (point 5), recorded as shared-contract §6's decision.
- **E.** Point 6's representation, with a declared value kind for every money field.
- **F.** A gated atomic write, `snapshot_record` without the path, and `verify` (point 7, migration
  0035).
- **G.** The slices M19.1 and M19.2, in that order.

### M19 acceptance criteria

| ID | Test |
|---|---|
| VA1 | Fixed inputs give byte-identical snapshots. Canonical encoding is checked, and a float anywhere in the builder's output fails |
| VA2 | Every §3 item is present, and every number agrees with its source command on the same ledger and `as_of` (`report monthly`, `report budget`, `safe-to-spend`, `report funds`, `report net-worth`, `report household`) |
| VA3 | No sentinel from any excluded field appears in the snapshot's bytes |
| VA4 | Every `*_cents` field has a declared kind, missing is `null`, and the validator accepts the golden fixtures and refuses each mutated copy: a wrong type, a missing required field, an unknown enum value, an unknown major |
| VA5 | A builder change without a fixture and version change fails |
| VB1 | A concurrent writer gives a snapshot equal to the before or the after state, never a mix |
| VB2 | `create` refuses an unsafe or existing destination, writing nothing. It writes `0600` atomically, and records without the path. Migration 0035 meets G10 |
| VB3 | `verify` accepts a fresh snapshot, and refuses a one-byte change, a changed digest, broken reconciliation and an excluded key, writing nothing |
| VB4 | `--snapshot` records its figures under G9. Every earlier criterion still passes |

---

## D-076 M20 plan: pairing and local-network sync — Approved, a security change

M20 meets PRD §19's "explicit sync mode for mobile access" and shared-contract §5, and records §6's
**pairing protocol**:

- pairing before any data access;
- encrypted, authenticated connections;
- snapshots validated before installation;
- atomic updates;
- acknowledgement;
- revocation;
- read-only from the phone.

**This milestone changes three security controls:**

1. a listening socket beyond loopback;
2. the `ssl` module;
3. one new subprocess.

Each is a change to W1, approved as one security change. Shared-contract §7's proposal is written
out in point 9.

```sh
pf sync identity create  --db DB                       # once: the Mac's TLS key and certificate
pf sync identity show    --db DB                       # its fingerprint
pf sync identity rotate  --db DB --revision dv1-…      # new identity; every device must pair again
pf sync pair             --db DB --name DEVICE_NAME --address IPV4 [--port P]
pf sync serve            --db DB --address IPV4 [--port P] [--minutes 10] [--window-days 90]
pf sync devices          --db DB
pf sync revoke           --db DB DEVICE_ID --revision dv1-…
pf sync deliveries       --db DB [--device DEVICE_ID]
```

**Slices:**

| Slice | Scope |
|---|---|
| M20.1 | Identity and pairing: migration 0036, the TLS identity through `/usr/bin/openssl`, the pairing window, the pairing code, device secrets, W1's changes (points 1 to 4) |
| M20.2 | Serving: `pf sync serve`, the three endpoints, device authentication, delivery and acknowledgement records, revocation, `dv1` (points 5 to 7) |
| M20.3 | The adversarial suite, the reference test client, `docs/sync-protocol.md` for the iOS side, the owner's runbook, and one check on a real phone (points 8 to 10) |

**Recommendations, each with its alternatives:**

1. **Transport: TLS 1.3, with the Mac's certificate pinned by the phone.**
   - `sync/server.py` serves HTTPS with `http.server`'s `HTTPServer`, its socket wrapped by an
     `ssl.SSLContext(PROTOCOL_TLS_SERVER)`, with these settings:
     - `minimum_version = TLSv1_3`;
     - no client certificates;
     - compression off;
     - session tickets off.

     It answers one request at a time, as `pf ui`.
   - **There is no certificate authority.** The phone pins the SHA-256 of the Mac's certificate,
     learnt at pairing (point 3), and refuses any other certificate. That pinning is the phone's
     side, specified in `docs/sync-protocol.md` and exercised by the reference client.
   - Alternatively:
     - **TLS-PSK:** needs no certificate and no subprocess, but Python's PSK callbacks arrive in
       3.13, and the project is on 3.12.6. It needs a runtime upgrade and an iOS check first.
     - **A hand-built encrypt-then-MAC over HMAC:** rejected. It would be custom cryptography.

2. **The identity: a P-256 key and a self-signed certificate, made once by `/usr/bin/openssl`.**
   - `sync identity create` runs `/usr/bin/openssl req -x509 -newkey ec -pkeyopt
     ec_paramgen_curve:prime256v1 -nodes -days 3650 -subj /CN=commoncents-sync -keyout KEY -out
     CERT`. The arguments are a fixed list with no shell, the timeout is 30 seconds, and the output
     is discarded.
   - It writes into a `sync/` folder beside the ledger, created `0700` with files `0600`, on the
     encrypted image (D-058).
   - The key never leaves that folder, and is never printed, backed up or put in a snapshot.
     Backups leave it out deliberately: a restored ledger means pairing again.
   - **W1 gains one allowance:** `sync/identity.py` may run exactly that executable. The test pins
     the path and arguments, as it does for `diskutil`.
   - **Before designing on it, run it once for real** (the handoff's lesson): macOS ships LibreSSL,
     and its options and output must be confirmed.
   - **Rotation** makes a new identity, revokes every device in the same transaction, and requires
     pairing again.
   - Alternatively **the `cryptography` package:** generates keys in-process, but it is a compiled
     dependency with its own native code, a larger audit than one system binary run once.

3. **Pairing: a one-use code shown as a QR code, inside a 120-second window.**
   - `sync pair` creates a **pairing secret** (32 bytes from `secrets`) and stores only its
     SHA-256. It then opens a **pairing window**: the listener on the given address for at most 120
     seconds, answering only `POST /v1/pair`.
   - It shows a **QR code** in the terminal holding `commoncents-pair:v1`, the address, the port,
     the certificate fingerprint and the secret.
   - **The phone scans it,** connects pinning the fingerprint, and posts the secret and its device
     name. The server compares the secret's hash with `hmac.compare_digest`, and on success returns:
     - a new **device ID**;
     - a **device secret** (32 bytes, base64url), stored only as its SHA-256.

     The window then closes.
   - **Failure limits:** 5 failed attempts close the window. A window is single-use, and only one is
     open at a time.
   - **The QR code is drawn by `segno`,** pure Python and BSD-3, pinned by version and hash, and
     imported only by `sync/pairing.py`. W1 parses it, as it does pypdf. **This is a new dependency
     needing approval** (D-020). Its modules must pass W1 before it is approved.
   - **A manual fallback:** the same payload as a base32 code to type, and the phone shows the
     fingerprint's first 16 hex digits to compare against the terminal's.
   - Alternatively:
     - **A QR encoder written in-repo:** no dependency, but a few hundred lines of error-correction
       code with no stdlib reference to test against.
     - **A numeric comparison (SAS) with commitments:** no QR, but more protocol, and more ways for
       a person to get it wrong.

4. **Where it listens.**
   - `--address` must be a private IPv4 address (RFC 1918, by `ipaddress`). Loopback, link-local,
     public and `0.0.0.0` are refused, apart from a test-only loopback hook that cannot be reached
     from the CLI.
   - **The port** is a stored setting (default 8443), so the phone can reconnect. A changed address
     is shown by `serve` as a QR code holding no secret.
   - There is no discovery (Bonjour): it would add a dependency and advertise the Mac.
   - **macOS's firewall** will ask to allow incoming connections for Python. The runbook documents
     answering it.

5. **`pf sync serve`: foreground, time-limited, read-only.**
   - **At start:** it builds a fresh snapshot in memory with M19's builder in one read transaction,
     and verifies it with M19's validator. It is never written to disk.
   - **It runs** until `--minutes` (default 10, at most 60), Ctrl-C, or 10 authentication failures
     in the session. On exit it prints counts only.
   - It never imports, writes ledger data, or runs while another serve or pair is running (a lock
     file in `sync/`).

   **The endpoints, all after TLS, and nothing else:**

   | Request | Needs | Answer |
   |---|---|---|
   | `GET /v1/snapshot/latest` | `Authorization: Bearer <device_id>.<device_secret>`, and `Accept-Snapshot-Major: 1` | `200` with the snapshot's bytes and its digest header. `409` with a JSON error naming the supported major when none matches (shared-contract §5's actionable error) |
   | `POST /v1/ack` | The same authorization, and a JSON body (at most 4 KB) of `snapshot_id` and `content_sha256` | `204` when both match what was served to that device. It records the acknowledgement, idempotent per device and snapshot |
   | `POST /v1/pair` | Only during a pairing window (point 3) | As point 3 |

   Every other method or path gets `404`, and an unauthenticated request `401`, with fixed bodies
   that repeat nothing from the request.

6. **Device authentication and revocation.**
   - Each request looks up the device by ID **in the ledger, per request**, and compares the
     secret's hash with `hmac.compare_digest`. A revoked device gets `401` from its next request on,
     with no restart needed.
   - `sync revoke` needs `dv1`, which covers the device and its state. Undoing a revocation is not
     offered: the device pairs again.
   - The phone stores its secret in the iOS Keychain. That is the iOS PRD's side, stated in the
     protocol document.

7. **Deliveries, and storage (migration 0036).** The tables:
   - `paired_device`: ID, name, secret hash, pairing time;
   - `paired_device_event`: `paired`, `revoked`;
   - `pairing_window`, with events `opened`, `failed`, `used`, `closed`, and only its secret's hash;
   - `sync_delivery`: device, snapshot ID, digest, with events `served`, `acknowledged`.

   All are append-only (G2). Device names are escaped as D-040. `snapshot_record` (M19) also gains
   a row for each served snapshot. The tables hold no snapshot content.

8. **Atomic installation on the phone, and the reference client.**
   - `docs/sync-protocol.md` specifies the phone's side:
     - pin the fingerprint;
     - send the supported majors;
     - verify the digest and the schema with M19's rules;
     - install atomically, keeping the last valid snapshot on any failure;
     - acknowledge only after installing;
     - show freshness from the snapshot, never from the sync time (shared-contract §5).
   - **The reference test client** in `tests/` does exactly that, in Python. It is the
     specification the iOS application is tested against, and it drives every end-to-end test on
     loopback.

9. **Shared-contract §7's proposal.**

   | Item | Answer |
   |---|---|
   | One-time and recurring costs | None. No service, no account, no paid dependency |
   | Data leaving the devices | Only the snapshot (D-075: its contents and exclusions), to a paired phone on the local network, while `serve` runs. Nothing leaves the local network |
   | Credentials and tokens | The Mac's TLS key, `0600` on the encrypted image, never backed up or printed. Device secrets stored as hashes. Pairing secrets single-use, at most 120 seconds, stored as hashes. The phone's secret in its Keychain |
   | Permissions and access scope | A listener on one private address and port, only while `pair` or `serve` runs in the foreground. Read-only: the phone can fetch the latest snapshot and acknowledge it, nothing else |
   | Operational dependencies | `/usr/bin/openssl` (once per identity), `segno` (if approved), the macOS firewall prompt, the same local network |
   | Failure behaviour | A failed or interrupted delivery leaves the phone's last valid snapshot. The server exits cleanly on timeout. A busy ledger refuses `serve` with `database_busy` |
   | Revocation | `sync revoke` takes effect from the device's next request. `identity rotate` revokes every device |
   | Local-only fallback | M19's snapshot file, carried by the owner (AirDrop or cable), verified on the phone by the same rules |

10. **Threat model, each threat with a test.**

    | Threat | Defence | Test |
    |---|---|---|
    | Another device on the network | No data without a device secret. `401`, fixed body | Every endpoint without, with a wrong, and with a revoked secret |
    | Man in the middle | The pinned fingerprint | The reference client refuses another certificate |
    | Someone seeing the QR code | A single use, 120 seconds, 5 failures | A second use, an expired window, a sixth attempt |
    | A stolen phone | Revocation | A request after revocation |
    | A downgrade | TLS 1.3 only | A TLS 1.2 client and a plaintext client are refused |
    | Malformed requests | Size limits, strict JSON, fixed bodies | Oversized headers and bodies, bad JSON, unknown fields, sentinels never echoed |
    | Leaving it on | Foreground only, time-limited, stops after failures | Timeout and the failure limit |
    | Logging data | D-037: no logs, counts only | No request writes to stdout or stderr except the final counts |

    **W1** allows `ssl` and `http.server` in `sync/server.py` alone, `segno` in `sync/pairing.py`,
    and `/usr/bin/openssl` in `sync/identity.py`, each pinned and each with a failing control.

**Performance.** Server-side time is below 1.0s for pairing and 2.0s for one delivery of a 5 MB
snapshot on loopback, plus the snapshot's own build at the start of `serve` (G9). **The benchmark
row** is `--sync`: 20 deliveries on loopback with the reference client.

**Not in M20:** writes from the phone (shared-contract §5 lists their prerequisites), sync over the
internet or through any relay, background or scheduled sync, discovery, several Macs, and push
notifications.

**Inputs needed from the owner:** the phone and its iOS version, the network (and whether it
isolates clients, as guest networks do), the port, approval of `segno` or the choice of the
alternative, and approval of the security change.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Approve local-network sync as one security change:** points 1 to 7 and W1's three
  allowances. Alternatively the file alone (D-066 point 6's alternative).
- **B.** TLS 1.3 with a pinned self-signed certificate made by `/usr/bin/openssl` (points 1 and 2).
  Alternatively TLS-PSK after a Python upgrade, or `cryptography`.
- **C.** A pairing window with a QR code drawn by `segno`, and a manual fallback (point 3).
  Alternatively an in-repo encoder or SAS.
- **D.** A private IPv4 address only, a stored port, no discovery (point 4).
- **E.** A foreground, time-limited, read-only `serve` with three endpoints (point 5).
- **F.** Per-request device checks, revocation with `dv1`, and rotation (point 6).
- **G.** Migration 0036, the reference client and the protocol document (points 7 and 8).
- **H.** Point 9's proposal and point 10's threat model.
- **I.** The slices M20.1 to M20.3, in that order.

### M20 acceptance criteria

| ID | Test |
|---|---|
| YA1 | Migration 0036 meets G10. `identity create` runs exactly the pinned command, writes `0600` files in a `0700` folder, and refuses an existing identity. W1 fails without each allowance, and on any other subprocess or network import |
| YA2 | Pairing succeeds once within the window, and refuses a second use, an expired window, a wrong secret and a sixth attempt. Only hashes are stored. The QR payload decodes to point 3's fields |
| YA3 | `--address` refuses loopback, link-local, public and wildcard addresses from the CLI |
| YB1 | The reference client receives exactly the snapshot `serve` built, verifies it, and acknowledges it. The delivery and acknowledgement are recorded idempotently, and a mismatched acknowledgement is refused |
| YB2 | No secret, a wrong one and a revoked device each give `401`, and revocation applies on the next request with no restart. An unsupported major gives `409` naming the supported one |
| YB3 | `serve` stops at its time limit and its failure limit, refuses a second concurrent `serve` or `pair`, writes no ledger data but deliveries, and prints counts only |
| YC1 | Every row of point 10 has a test with a control that succeeds. TLS 1.2 and plaintext clients are refused |
| YC2 | `docs/sync-protocol.md` and the runbook exist, are checked through on synthetic data in `build/`, and one real-phone delivery is recorded by the owner. `--sync` records its figures under G9. Every earlier criterion still passes |

---

## D-077 M21 plan: backend acceptance, stress testing and the security audit — Approved

M21 builds no feature. It proves that the backend is finished by D-066's definition:

- every PRD §21 box checked by a named test;
- every shared-contract §6 item recorded as a decision;
- each phase meeting shared-contract §10's definition of done;
- point F passed on a real file of each layout;
- D-025 decided.

It adds stress, crash and fuzz suites that run apart from the gating suite, and a written security
audit. **No migration is planned.** One is added only if the audit finds a schema gap, as its own
decision.

```sh
pytest tests/acceptance                     # the PRD §21 matrix, in the gating suite
python tests/stress/run_stress.py --minutes N --seed S       # outside the gating suite
python tests/stress/run_crashes.py --points all --seed S
python tests/stress/run_fuzz.py --target (csv|pdf|forms|sync) --examples N --seed S
python tests/benchmarks/measure_reconciliation.py --scale --everything
```

**Slices:**

| Slice | Scope |
|---|---|
| M21.1 | The acceptance matrices: PRD §21, shared-contract §6 and §10, by named tests and documents (points 1 and 2) |
| M21.2 | Stress: the full-scale shape, concurrent writers and readers, crashes at every commit point, fuzzing of every parser and every input boundary (points 3 to 6) |
| M21.3 | The security audit and D-025's decision (points 7 and 8) |
| M21.4 | With the owner: point F on every layout, a rehearsal of the real ledger's migration and restore, the readiness and recovery documents current (point 9) |

**Recommendations, each with its alternatives:**

1. **PRD §21 closed by named tests,** in `docs/backend-acceptance.md`, in the style of
   [m1-acceptance.md](m1-acceptance.md), and checked by a test as `test_acceptance_matrix.py` checks
   it:

   | §21 box | Closed by |
   |---|---|
   | Reimporting identical files changes no totals | A1 to A46's tests, rerun at full scale (point 3) |
   | Overlapping CSV and PDF records count once when confidently matched | I1 to I6 |
   | Legitimate repeated purchases remain distinct | M1's, J4, D12 |
   | Pending-to-posted reconciliation avoids double counting | M2.9's |
   | Confirmed internal transfers affect neither income nor spending | T1 to T5 |
   | Credit-card payments do not duplicate purchases | T5 |
   | Ambiguous matches remain visible and reversible | M2's, X3, X9 |
   | All transaction splits reconcile exactly | HA5, HB2, HC1 |
   | Annual reservations and purchases are not double-counted | GB2, SB3 |
   | Third paychecks do not increase normal spending targets | IC1, BB5, SB6 |
   | Goal allocations cannot silently exceed available funds | GA3, GA4 |
   | Graduated payments follow the configured schedule | LB2, LB3 |
   | Reports disclose incomplete data and material review issues | G5, CC3, the provisional reasons of SB5, VA2's warnings |
   | Backups restore records, rules, corrections, and goals | R4, CB6, RB3, HB5, GC3, and point 3's full-scale restore |
   | Core operation succeeds without internet access | W1, and the suite's socket guard, rerun with the network interface down by the owner once |

   Each box also gets **one end-to-end test** of its own, on one synthetic household's full year,
   from import to snapshot, so that no box is closed only by pieces.

2. **Shared-contract §6 and §10.**
   - **§6:** every item is named in [decisions.md](decisions.md)'s "Not yet decided" section,
     emptied:

     | §6 item | Decided by |
     |---|---|
     | Safe-to-spend calculation details | D-072 |
     | Loan projection assumptions | D-071 point 5 |
     | Snapshot compatibility policy | D-075 point 5 |
     | Pairing protocol | D-076 |

   - **§10,** for Phase 1B and Phase 1C, each as a checklist with evidence:
     - reproducible setup (a clean clone on this Mac);
     - automated tests;
     - a synthetic-data demonstration (`build/`, a script driving the full year);
     - documented assumptions;
     - migrations;
     - backup and recovery instructions;
     - security and privacy notes;
     - known limitations (status.md);
     - user acceptance checks, by the owner.

3. **The full-scale shape: `--everything`.**
   - **Its size:**
     - 100,000 transactions, 60 months, 30 accounts (PRD §2's upper bound, not four);
     - 3 members;
     - every planning entry kind at the counts of its milestone's row;
     - 10 scenarios;
     - one snapshot.
   - **It times** every report, page, write and command against G9, in one table in
     [benchmarks.md](benchmarks.md).
   - **It also backs up, verifies and restores this ledger,** comparing every command's output byte
     for byte (R4 at scale), and migrates a copy of a version-21 ledger of the same shape to the
     latest version, timing each step.
   - Missed targets follow the stopping rule. M21 reports them and does not redesign.

4. **Concurrency stress (G3).** `run_stress.py` runs N processes for the given minutes, with a
   seed:
   - writers making random valid commands from every write kind, each with the token it was just
     shown;
   - readers running every report, and the UI under a test client;
   - a `snapshot create` loop.

   After each run, and every 60 seconds:
   - `PRAGMA integrity_check` and `foreign_key_check`;
   - every invariant: the five groups, categories, members and fund sums, no double reservation,
     `evidence_digest` changes only by imports and statements;
   - every refusal is one of the documented codes, and no partial write exists.

   **A stale token must never succeed.** The harness records each token's age and asserts that any
   command whose evidence changed was refused. Seeds that fail are kept as regression tests.

5. **Crashes at every commit point.**
   - `run_crashes.py` enumerates each write command's statements, and for each one runs the command
     in a child process killed (`SIGKILL`) just before and just after that statement.
   - After each kill, the ledger must open through the gate. It must equal either the before or
     the after state (logical digest), never anything in between, and every invariant must hold.
   - It covers import, every statement kind, every planning write, migration steps, backup,
     snapshot create, and a delivery acknowledgement.
   - **The hook** is a test-only environment variable read by a test-only module that the CLI never
     imports. W1 checks this.

6. **Fuzzing, with Hypothesis and no new dependency.**

   | Target | What is generated | What must hold |
   |---|---|---|
   | CSV layouts | Malformed rows, encodings, sizes | Every file imports or fails with a documented code. No unexpected error, no partial import, no fabricated value |
   | PDF | Mutated synthetic PDFs | Documented failures only (D-060) |
   | Amount and date parsing | Arbitrary strings | Exact parsing or refusal |
   | UI requests | Arbitrary headers, methods, bodies (M17's pipeline) | A fixed response, no write unless the full pipeline passes, nothing echoed |
   | Sync requests | Arbitrary bodies and headers | As above, after TLS |
   | Snapshot validator | Mutated snapshots | Refused with a reason |

   Every run records its seed, and any failure becomes a fixed example.

7. **The security audit, written as `docs/security-audit.md`,** by the lead engineer, from the code
   as built. It covers:
   - **an inventory:** every listening socket, subprocess, file written outside the ledger folder,
     dependency (with versions and hashes), secret, and file mode;
   - **controls against their tests:** each D-058, D-062, D-073 and D-076 control, with the test
     proving it and its failing control;
   - **data flows:** what leaves the ledger (backups, exports, snapshots, sync) with each gate;
   - **a review of PRD §19's list,** line by line;
   - **dependencies:** pypdf, `segno` if approved, and the system `openssl`, with their current
     advisories checked by the owner. Checking needs the network, which needs the owner's approval
     to use;
   - **what is not covered:** the interpreter, macOS, the browser's own storage, the phone. No
     absolute-security claim is made (PRD §19).

   Each finding is a numbered item, fixed in M21 when small, or recorded as its own decision.

8. **D-025, decided.** D-025's proposal was never applied. The audit compares it with the controls
   actually built, and the owner decides, item by item, to apply, to drop as superseded, or to keep
   for later. Recommended: drop the items D-058, D-062, D-073 and D-076 cover, and present the rest
   as their own decision.

9. **With the owner (M21.4).**
   - **Point F** on one real file of each layout, by
     [layout-verification.md](layout-verification.md), in a throwaway ledger with the files already
     imported (as the handoff says).
   - **A migration rehearsal:** restore the latest real backup to a new path (D-058), migrate the
     restored copy across every pending version, and compare its reports with the original's at the
     common version. Only then does the owner migrate the real ledger.
   - **[real-data-readiness.md](real-data-readiness.md) and the recovery instructions** brought
     current, including the known `CommonCentsBackups` naming fix, then run once more by the owner.
   - **F2 closed:** shown not needed, since no page, export or snapshot presents a legacy creation
     timestamp. Otherwise a marker is added as its own decision.
   - Alternatively **acceptance by the gating suite alone:** quicker, but none of the stress, crash
     or audit work would exist, and PRD §19's "security controls must be verified" needs more.

**Not in M21:** new features, the iOS application, institution connections and every other "Later"
item of PRD §3.

**Inputs needed from the owner:** time for point F and the rehearsal, the advisory checks (with
network approval), D-025's decisions, and §10's user acceptance checks.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** PRD §21 by named tests and one end-to-end test per box, in `docs/backend-acceptance.md`
  (point 1).
- **B.** Shared-contract §6 and §10 as checklists with evidence (point 2).
- **C.** `--everything` at 30 accounts, with full-scale backup, restore and migration (point 3).
- **D.** Seeded concurrency stress, crash injection at every commit point, and Hypothesis fuzzing,
  outside the gating suite (points 4 to 6).
- **E.** A written security audit and D-025's item-by-item decision (points 7 and 8).
- **F.** Point F, the migration rehearsal and current readiness documents, with the owner (point
  9).
- **G.** The slices M21.1 to M21.4, in that order.

### M21 acceptance criteria

| ID | Test |
|---|---|
| ZA1 | `docs/backend-acceptance.md` maps every PRD §21 box to named tests that exist and pass, checked by a test. Each box has its own end-to-end test |
| ZA2 | "Not yet decided" in [decisions.md](decisions.md) is empty, and §10's checklists hold evidence for Phase 1B and 1C |
| ZB1 | `--everything` reaches its stated counts and records every figure, and a full-scale restore and migration compare byte for byte |
| ZB2 | A 60-minute stress run at three seeds ends with every check passing, no stale token succeeding, and no undocumented refusal |
| ZB3 | A crash at every enumerated point leaves the before or the after state and every invariant |
| ZB4 | Every fuzz target runs its examples with no failure, and every recorded seed reproduces |
| ZC1 | `docs/security-audit.md` covers point 7's sections, and each finding is closed or decided. D-025 is decided |
| ZD1 | Point F has passed for every layout, the rehearsal has compared clean, and the owner has run the readiness checklist again. Every earlier criterion still passes |

---

## Summary for implementation

### Dependency order

```
M11 ─► M12 ─► M13 ─► M14 ─► M15 ─► M16 ─► M17 ─► M18 ─► M19 ─► M20 ─► M21
        │      ▲      ▲  ▲     ▲      ▲
        └──────┴──────┘  │     │      │
   (M12 feeds M13's fixed/discretionary, M14's tax and extra, M16's horizon)
              M13 ──────►┘     │      │   (unused capacity to goals)
                     M14 ──────┘      │   (debt goal to payoff plans)
                     M12–M15 ─────────┘   (every protected fund)
```

### Where each token version moves

| Slice | `r` | `t` | `d` | `c` | New kinds |
|---|---|---|---|---|---|
| M11.2 (D-065) | 12 | 10 | 9 | 5 | `h1`, `a1`, `s1` |
| M12 to M13 | — | — | — | — | `in1`, `ob1`, `st1`, `bp1` |
| M14.2 | 13 | 11 | 10 | 6 | `fu1`, `fa1`, `fc1` |
| M15.3 | 14 | 12 | 11 | 7 | `al1`, `lt1`, `lb1` |
| M16 | — | — | — | — | `lq1` |
| M17.3 | 15 | 13 | 12 | 8 | `tg1` |
| M18 | — | — | — | — | `sc1`, `sp1` |
| M20 | — | — | — | — | `dv1` |

Every move keeps every digest on a ledger the new statement does not reach (G5, G6).

### Commands whose existing output may change

Every other existing command stays byte for byte the same, by G6.

| Milestone | Commands | Only where |
|---|---|---|
| M12 | `review show`, `review transaction show` | A source or obligation reaches the transaction |
| M14 | The same two, and `report budget` | A consumption reaches |
| M15 | `totals`, `report monthly`, `report household`, the two shows. `balance record` gains a flag | A breakdown applies |
| M17 | `pf transactions` (filters), the two shows | Filters are given, or a tag statement reaches |

### Inputs the owner gives, by milestone

| Milestone | Inputs |
|---|---|
| M12 | Salary accounts, cadence, a real pay date, take-home. Side-income sources and tax eligibility. Bills to confirm |
| M13 | The household timezone, the discretionary allowance, personal allocations, category allowances |
| M14 | Goals, emergency minimum, annual expenses, the tax percentage, the priority (house against debt), current assignments |
| M15 | Graduated-loan documents, redacted. Aggregates and subaccounts. Ownership differences. The payoff extra |
| M16 | The checking buffer, liquid accounts, coverage links, emergency restoration |
| M17 | The browser allowlist. **Approval of the security change** |
| M19 | The transaction window, and whether institution names may appear |
| M20 | The phone, the network, the port, `segno`. **Approval of the security change** |
| M21 | Point F time, advisory checks, D-025, acceptance checks |

### The routine for every slice

These are the handoff's rules, collected:

1. Approval for the slice, and renewed commit permission.
2. Check the branch and a clean tree, then run the full suite with a real exit code.
3. Before changing anything, keep the suite's ledgers under `build/` for G6.
4. Build the slice. Write the migration first, when there is one, with its G10 checklist.
5. Gate each commit on pytest's own exit code, never through a pipe.
6. Run 20 to 25 targeted breaks (G12), and record the counts.
7. Make the G6 comparison and the benchmark row (G9), then record the figures in
   [benchmarks.md](benchmarks.md).
8. Tick the slice in [plan.md](plan.md), update [status.md](status.md) and replace the handoff's
   state, then commit without `.DS_Store`.
9. Stop for review.
