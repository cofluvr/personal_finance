# Implementation Status

Last updated: 2026-11-20. Branch: `feature/m10-rules`, from `main` at `19ee858`, which holds everything through M9. The owner intentionally pushed `feature/m1-foundation` up to `643e1b1`, and pushed `feature/m2-review` themselves. This clone records only a push of `673c025`. Live remote state and repository visibility are unverified (see [archive/handoff-history.md](archive/handoff-history.md)). Handoff: [handoff.md](handoff.md).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Accepted |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Accepted |
| M1 slice 3: cross-document duplicate handling | Accepted |
| M1 slice 4: import summaries, log checks, entry point, setup documentation | Accepted |
| **M1 overall** | **Complete and accepted** |
| M2.1: review evidence and revision tokens | Accepted |
| M2.2: decision core, pair rejection and undo | Accepted |
| M2.3: confirmation, partitions and superseding | Accepted (D-046) |
| M2.4: separating machine-made merges | Accepted (D-047) |
| M2.5: new evidence on decided records, and superseding chains | Accepted (D-048) |
| M2.6: value corrections | Accepted (D-049) |
| M2.7: resolving incomplete records | Accepted (D-050) |
| M2.8: coverage correction with history | Accepted (D-051) |
| M2.9: pending to posted | Accepted (D-052) |
| **M2 overall** | **Complete and accepted** |
| M3.1: financial types | Accepted (D-053) |
| M3.2: transfers across accounts | Accepted (D-054) |
| M3.3: card payments, one-sided transfers and coverage warnings | Accepted (D-055) |
| M3.4: income and spending | Accepted (D-056) |
| **M3 overall** | **Complete and accepted** |
| M4.1: the 32,766-variable limit | Accepted (D-057) |
| M4.2: balance observations and statement reconciliation | Accepted (D-057) |
| M4.3: monthly reports with disclosures | Accepted (D-013, D-057) |
| M4.4: the 100,000-transaction benchmark | Accepted (D-057) |
| **M4 overall** | **Complete and accepted** |
| M5.1: real ledgers, their location and file permissions | Accepted (D-058) |
| M5.2: encryption, an encrypted volume checked on every open | Accepted (D-002, D-058) |
| D-081: the private-folder protection for a real ledger, iCloud Drive included | Built on 2026-11-26 for the owner's review |
| M5.3: archiving originals, and storage by kind | Accepted (D-017, D-058) |
| M5.4: backup, verification and restore | Accepted (D-058) |
| M5.5: network and dependency behaviour, and the readiness checklist | Accepted (D-058) |
| **M5 overall** | **Complete and accepted.** Readiness checklist run by the owner on 2026-11-09 |
| M6.1: Capital One card and bank layouts | Complete (D-059). Both formats confirmed, the bank's with its account number checked (D-061) |
| M6.2: U.S. Bank CSV activity list | Complete (D-059). Format not confirmed |
| M6.3: American Express card | Complete (D-059). Format confirmed |
| M6.4: BFSFCU | Complete (D-059). Format confirmed |
| **M6 overall** | **Complete.** Point F runs per layout before its first real import |
| M7.1: reading PDF text | Complete (D-060) |
| M7.2: U.S. Bank card activity printout, `us_bank_card_activity_pdf_v1` | Complete (D-060, as amended). Unverified until point F |
| M7.3: CSV and PDF counting once | Complete, on D-006 unchanged, against a test-only CSV layout (D-060) |
| M7.4 and M7.5 | Not built: one card per printout, and the owner holds no Capital One card PDF |
| **M7 overall** | **Complete,** recorded by the owner on 2026-11-09 |
| M8.1: one builder per report | Complete (D-062) |
| M8.2: `pf ui`, the loopback server, totals and monthly pages | Complete (D-062) |
| M8.3: import results, transactions, review queue and item pages | Complete (D-062) |
| M8.4: decisions from the browser | Not built: the owner chose a read-only M8 |
| **M8 overall** | **Complete,** verified by the owner in a browser on 2026-11-09 |
| M9.1: the category list | Accepted (D-063) |
| M9.2: categorizing one spending transaction, types and categories on one model | Accepted (D-063) |
| M9.3: spending by category in totals, monthly and the UI | Accepted (D-063) |
| **M9 overall** | **Complete and accepted** on 2026-11-09, verified by the owner on the real ledger: migrated to version 20 after a verified backup, and categorizing confirmed in the CLI and the UI |
| M10.1: category rules, their preview, outcome and precedence | Accepted (D-064) |
| M10.2: undoing a category rule | Accepted (D-064) |
| M10.3: rules in the reports, the source of a category, the benchmark row | Accepted (D-064) |
| **M10 overall** | **Complete and accepted** on 2026-11-10. Not yet verified on the real ledger, still at version 20 until a verified backup and `pf migrate` to 21 |
| M11.1: members, the household share and account attribution | Accepted (D-065) |
| M11.2: allocating one transaction | Accepted (D-065), two refusal messages changed at review |
| M11.3: the household report, its UI page, the benchmark row | Accepted (D-065) |
| **M11 overall** | **Complete and accepted** on 2026-11-10 (D-065). Not on the real ledger, which stays at version 20 until 21, then 22 and 23, each after a verified backup |
| M12.1: income sources | Accepted on 2026-11-15 as built, both departures included (D-068) |
| M12.2: recurring obligations | Accepted on 2026-11-16 as built, its departures included (D-068) |
| M12.3: the income report, its page, the benchmark row | Accepted on 2026-11-16 as built, its departures included (D-068) |
| **M12 overall** | **Complete and accepted** on 2026-11-16. Not on the real ledger, which takes 24 and 25 after M10's and M11's migrations, each after a verified backup |
| M13.1: settings, budget plans, today from the household timezone | Accepted on 2026-11-16 as built, its departures included (D-069) |
| M13.2: the budget report, its page, the benchmark row | Accepted on 2026-11-16 as built, its departures included (D-069) |
| **M13 overall** | **Complete and accepted** on 2026-11-16. Not on the real ledger, which takes 26 after M12's migrations, each after a verified backup |
| M14.1: funds, assignments and the priority list | Accepted on 2026-11-16 as built, its departures included (D-070) |
| M14.2: consumption, tax payments and releases | Accepted on 2026-11-19 as built, its departures included (D-070) |
| M14.3: `report funds`, the extra by priority, its page, the restore test, `--funds` | Accepted on 2026-11-19 as built, its departures included (D-070) |
| M15.1: net worth, account links, its page | Accepted on 2026-11-19 as built, its departures included (D-071) |
| M15.2: loan terms, actual against schedule, projections, payoff orders | Accepted on 2026-11-19 as built, its departures included (D-071) |
| M15.3: principal and interest, interest in Spending, `--loans` | Accepted on 2026-11-19 as built, its departures included (D-071) |
| **M14 and M15 overall** | **Complete and accepted** on 2026-11-19. Not on the real ledger, which takes 27 and 28, then 29 to 31, after the earlier milestones' migrations, each after a verified backup |
| M16.1: liquidity designations, coverage links, restoration, the buffer | Accepted on 2026-11-20 as built (D-072) |
| M16.2: safe to spend, the dashboard, its page, `--safe-to-spend` | Accepted on 2026-11-20 as built, with the two findings settled (D-072) |
| M17.1: the browser write pipeline, review decisions from the browser | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M17.2: the transaction page and its writes, the sections and planning writes | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M17.3: migration 0033, tags, search, the eight visuals | Accepted on 2026-11-21 by the owner's notes, its departures included. The real-browser CSP check is still the owner's to do |
| M17.4: CSV export, `--ui` | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M18.1: migration 0034, scenarios and their inputs, `sc1` | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M18.2: the projection, `scenario compare`, the scenario pages and forms | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M18.3: promotion and its undo, `sp1`, `--scenarios` | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M19.1: the snapshot builder, canonical JSON, the schema and its validator | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M19.2: snapshot create, verify and the list, migration 0035, `--snapshot` | Accepted on 2026-11-21 by the owner's notes, its departures included |
| M20.1: migration 0036, the sync identity, pairing windows, devices, `dv1` | Built on 2026-11-21 (D-076, "How M20 was implemented"), a security change, awaiting the owner's review |
| M20.2: `sync serve`, deliveries, acknowledgements, revocation | Built on 2026-11-21, awaiting the owner's review |
| M20.3: the threat model's tests, the protocol, the runbook, `--sync` | Built on 2026-11-21, awaiting the owner's review. The real-phone delivery (YC2) waits for the iOS app |
| M21.1: the acceptance matrix, B1 to B15 end to end, §6 decided, §10's checklists | Built on 2026-11-21 (D-077, "How M21 was implemented"), awaiting the owner's review |
| M21.2: crash, fuzz and stress suites, `--everything` | Built on 2026-11-21: 484 crash points hold; every fuzz target passes 500 examples at two seeds; stress at three 60-minute seeds |
| M21.3: [security-audit.md](security-audit.md) | Built on 2026-11-21. D-025's item-by-item decision is the owner's |
| M21.4: point F, the migration rehearsal, the readiness checklist | The owner's |
| iOS I1 to I3 (D-079): CommonCentsKit and the app | Built on 2026-11-21, awaiting the owner's review: 28 package tests on the Mac and the simulator, 8 UI tests, and interop against the real server. I4 and the real phone are the owner's ([ios/README.md](../ios/README.md)) |
| D-080: snapshot 1.1, each member's budget pace | Built on 2026-11-21, awaiting the owner's review |
| **M12 to M21** | **Approved** on 2026-11-10: the sequence (D-066) and each milestone's plan (D-067 to D-077, [decisions-m12-m21.md](decisions-m12-m21.md)). M12 to M19 accepted, M20 and M21.1 to M21.3 built for review |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- `personal_finance.db.id_lists`: any number of IDs as one SQL parameter (D-057).
- `personal_finance.db.real_ledger`: the real-ledger mark and its protection, and the location,
  encrypted-volume and import checks every open of a real ledger runs, with its temporary files
  kept in memory (D-058). A private-folder ledger's open makes its files private and refuses while
  a sync conflict's copy sits beside it (D-081).
- `personal_finance.db.originals`: archiving a real ledger's originals on import, and verifying
  them (D-017, D-058).
- `personal_finance.reports.report_text`: the text of `totals`, `report monthly`, `documents`,
  `transactions`, `review list` and `review show`, built as lines that the CLI prints (D-062).
- `personal_finance.ui.server`: `pf ui`'s read-only pages on 127.0.0.1, and their protections
  (D-062).
- `personal_finance.reports.storage`: software, database, originals and backups storage apart
  (D-058).
- `personal_finance.db.backups`: backing up a ledger with a manifest and logical digest, checking a
  backup, and restoring one to a new path (D-058).
- `personal_finance.db.volume_probes`: the only subprocess calls, `diskutil info -plist` on a mount
  point and `hdiutil info -plist` (D-058).
- Migrations `0001_initial`, `0002_block_replace`, `0003_reconciliation`,
  `0004_identity_and_primary`, `0005_decisions`, `0006_confirmation`, `0007_separation`,
  `0008_supersession_chains`, `0009_value_corrections`, `0010_record_resolutions`,
  `0011_coverage_declarations`, `0012_pending_posted_links`, `0013_type_classifications`,
  `0014_transfer_matches`, `0015_one_sided_transfers`, `0016_balance_observations`,
  `0017_real_ledger`, `0018_backup_records`, `0019_categories`, `0020_categorizations`,
  `0021_category_rules`, `0022_household`, `0023_allocations`, `0024_income_sources` and
  `0025_recurring_obligations`, `0026_settings_and_budgets` and `0027_funds`,
  applied by `init` and `migrate` only (D-035).
- `personal_finance.ingest`: two invented layouts and five unverified institution layouts (D-059), explicit coverage, atomic
  per-file import.
- `personal_finance.reconcile.same_document`: flags possible duplicates within one
  document. Merges nothing.
- `personal_finance.reconcile.cross_document`: derives an account's transactions and
  review items as a pure function of its stored evidence.
- `personal_finance.reconcile.apply`: applies that result atomically with the import,
  recording every source movement.
- `personal_finance.reconcile.decisions`: rejecting pairs, confirming partitions, separating
  automatic merges, superseding and undoing decisions, each under one write lock (D-043, D-045,
  D-046, D-047, D-048).
- `personal_finance.reconcile.correction_effects` and `corrections`: which corrected values apply
  to which transactions, and correcting and undoing values under one write lock (D-049).
  `reconcile.supersession` holds the chain rule that decisions and corrections share (D-048).
- `personal_finance.reconcile.record_resolutions`: completing and dismissing unresolved records, and
  undoing that, under one write lock (D-050).
- `personal_finance.reconcile.coverage_declarations`: declaring a document's coverage after import,
  and undoing that, under one write lock (D-051).
- `personal_finance.reconcile.stated_fields`, `statements` and `reports.stated_evidence`: a value a
  person states on one transaction, its chains, outcomes, commands and undo token, shared by types
  and categories (D-053, D-063).
- `personal_finance.reconcile.classification_effects` and `classifications`: which financial type
  applies to which transaction, sharing the corrections' effective-value rule, and classifying and
  undoing under one write lock (D-053).
- `personal_finance.reconcile.categories`, `category_effects` and `categorizations`: the category
  list, which category applies to which spending transaction, and categorizing and undoing under
  one write lock (D-063). `reports.categorization_evidence` holds the `g2` undo token.
- `personal_finance.reconcile.category_rule_effects` and `category_rules`: which category rules
  reach which spending transaction and the category they give, derived on every write, and adding and
  undoing a rule under one write lock (D-064). `reports.category_rule_evidence` holds the
  preview and undo outlooks, and the `p1` and `q1` tokens.
- `personal_finance.reconcile.household_effects` and `household`: household members, the share and
  each account's default, `allocate_cents`, each transaction's attribution resolved when read, and
  the `household` commands under one write lock (D-065). `reports.household_evidence` holds the
  `h1` and `a1` tokens.
- `personal_finance.reports.household`: `pf report household`'s side-by-side, one-member and
  shared views, counted by the same tally as `totals` (D-065).
- `personal_finance.reconcile.allocation_effects` and `allocations`: which allocation applies to
  which transaction, on the stated model shared with types and categories, and allocating and
  undoing under one write lock (D-065). `reports.allocation_evidence` holds the `s1` undo token.
- `personal_finance.planning.income_effects`, `income_sources` and `income_proposals`: income
  sources' nominal pay dates, the deposits each reaches and their states, derived on every write;
  adding, superseding, re-terming and undoing a source under one write lock; and proposals from
  history, never stored (D-068). `reports.income_evidence` holds the preview and the `in1` token.
- `personal_finance.planning.schedules` and `entries`: what income sources and obligations share,
  the schedules as pure functions and G2 to G4's write path (D-068 point 6).
- `personal_finance.planning.obligation_effects`, `obligations` and `obligation_proposals`:
  recurring obligations' due dates, the spending each reaches and its state and class, derived on
  every write; adding, superseding, re-terming, undoing and dismissing; and proposals from history
  (D-068 point 5). `reports.obligation_evidence` holds `ob1`, and `reports.obligation_spending`
  fixed and discretionary spending. `reports.income_report` builds `pf report income` (D-068 point 8).
- `personal_finance.planning.settings`: keyed, append-only ledger settings, the household timezone
  the first, with `st1` (D-069 point 1). Only the CLI reads the clock, turning UTC into the
  household's day (G7).
- `personal_finance.planning.budgets` and `budget_pace`: budget plans, the plan in effect for a
  month, chains and closed months, with `bp1` (D-069 points 2 and 6); and point 4's formulas in
  integer cents. `reports.budget_report` builds `pf report budget` (D-069 points 3 to 5).
- `personal_finance.planning.funds`: funds of four kinds with dated terms, each kind's required
  amount rounded up, assignments of an account's observed balance with the guard, and the
  priority list, with `fu1` and `fa1` (D-070 points 1 to 4). `reports.fund_standing` gathers
  baseline income, fixed commitments and the tax accrual from M12 for `pf funds` and `fund show`.
- `personal_finance.reconcile.transfer_effects` and `transfers`: which transfer matches and one-sided
  transfers apply and which pairs are candidates, read after each account derives alone, and
  matching, stating and undoing under one write lock (D-054, D-055).
  `reconcile.coverage_in_effect` holds the coverage in effect for an account (D-027, D-051).
- `personal_finance.reconcile.rules` and `similarity`: the versioned matching
  configuration and the description heuristic.
- `personal_finance.reports.totals`: account inflows, outflows and net movement, types, transfers
  between accounts, and income and spending (D-056).
- `personal_finance.reports.monthly`: the monthly report, with each month's coverage and
  disclosures (D-013, D-057).
- `personal_finance.reports.import_summary`: run-level import counts in explicit units (D-036).
- `personal_finance.reconcile.balance_observations` and `reports.balances`: recording and undoing
  balance observations under one write lock, their undo token, and statement reconciliation
  (D-057).
- `personal_finance.reports.review_evidence`: the evidence behind one review item or one
  transaction, and their revision tokens (D-040, D-047).
- `personal_finance.reports.decision_evidence`: what a decision binds, and the undo token (D-045).
- `personal_finance.reports.correction_evidence`: what a correction binds, and its undo token (D-049).
- `personal_finance.reports.classification_evidence`: what a classification binds, and its undo
  token (D-053).
- `personal_finance.reports.transfer_evidence`: what a transfer match or one-sided transfer binds,
  and their undo tokens (D-054, D-055).
- `personal_finance.reports.resolution_evidence`: what a resolution resolved, and its undo token
  (D-050).
- `personal_finance.reports.coverage_evidence`: a document's claimed and declared coverage, and their
  tokens (D-051). `reports.undo_items` computes the undo token both share.
- CLI: `init` (with `--real`), `migrate`, `account add`, `import`, `reconcile`, `documents`, `transactions`,
  `trace`, `review list`, `review show`, `review reject`, `review confirm`, `review merges`,
  `review merge show`, `review separate`, `review decisions`, `review decision show`,
  `review undo`, `review transaction show`, `review correct`, `review corrections`,
  `review correction show`, `review correction undo`, `review complete`, `review dismiss`,
  `review resolutions`, `review resolution show`, `review resolution undo`, `review coverage show`,
  `review coverage declare`, `review coverage history`, `review coverage undo`, `review classify`,
  `review classifications`, `review classification show`, `review classification undo`,
  `review transfers`, `review transfer match`, `review transfer one-sided`, `review transfer show`,
  `review transfer undo`, `category add`, `category list`, `category rules`,
  `category rule preview`, `category rule add`, `category rule show`, `category rule undo`,
  `review categorize`,
  `review categorizations`, `review categorization show`, `review categorization undo`,
  `household member add`, `household members`, `household share show`, `household share set`,
  `household share undo`, `household account show`, `household account set`,
  `household account undo`, `review allocate`, `review allocations`, `review allocation show`,
  `review allocation undo`, `income proposals`, `income preview`, `income add`, `income terms`,
  `income sources`, `income source show`, `income undo`, `obligation proposals`,
  `obligation preview`, `obligation add`, `obligation terms`, `obligation show`,
  `obligation undo`, `obligation dismiss`, `obligation dismissals`, `obligation dismissal undo`,
  `obligations`, `report income`, `setting show`, `setting set`, `setting undo`,
  `budget preview`, `budget set`, `budget show`, `budget undo`, `budgets`, `report budget`,
  `fund preview`, `fund add`, `fund terms`, `fund undo`, `fund show`, `fund assign`,
  `fund unassign`, `fund priority`, `fund release`, `fund release-undo`, `funds`,
  `report funds`, `review consume`, `review consumptions`, `review consumption show`,
  `review consumption undo`, `account links`, `account link`, `account unlink`,
  `report net-worth`, `loan terms add`, `loan terms show`, `loan terms undo`, `loan rate`,
  `loan payment`, `loan plan set`, `report loans`, `loan project`, `loan payoff`,
  `review breakdown`, `review breakdowns`, `review breakdown-show`, `review breakdown-undo`,
  `account liquidity show`, `account liquidity set`, `account liquidity undo`,
  `obligation coverage`, `obligation covers`, `obligation uncover`, `fund restorations`,
  `fund restoration`, `fund restoration-undo`, `safe-to-spend`, `dashboard`,
  `tag add`, `tags`, `review tag`, `review tagging show`, `review tagging undo`,
  `transactions` with `--search`, `--account`, `--from`, `--to`, `--category`, `--tag`, `--min`
  and `--max`, `report visuals`, `export transactions`, `export report`, `scenario add`,
  `scenarios`, `scenario show`, `scenario input add`, `scenario input undo`, `scenario undo`,
  `scenario compare`, `scenario promote`, `scenario promotion undo`, `snapshot create`,
  `snapshot verify`, `snapshots`,
  `sync identity create`, `sync identity show`, `sync identity rotate`, `sync pair`,
  `sync serve`, `sync devices`, `sync revoke`, `sync deliveries`,
  `totals`,
  `report monthly`, `report household`, `balance record`, `balance list`,
  `balance check`, `balance undo`, `archive verify`, `storage`, `backup create`,
  `backup verify`, `backup restore`, `pdf text`, run
  through the `bin/pf` launcher (D-038).

- `personal_finance.planning.scenarios`, `projection` and `promotions`: scenarios and their
  inputs, the pure monthly projection, and promotion with its undo (D-074).
  `personal_finance.reports.scenario_report`: the plan read once, and the lines of `scenarios`,
  `scenario show` and `scenario compare`, which the scenario pages render.
- `personal_finance.snapshot`: canonical JSON, the snapshot builder, the schema document and its
  validator, and creating, verifying and listing snapshot files (D-075).
- `personal_finance.sync`: the Mac's TLS identity, pairing windows, devices, deliveries and the
  TLS 1.3 server that hands a paired phone its snapshot (D-076). Its protocol is
  [sync-protocol.md](sync-protocol.md), executable as `tests/sync_reference_client.py`.

## What does not exist yet

Five institution layouts exist, `capital_one_card_v1`, `capital_one_bank_v1`, `us_bank_v1`,
`amex_card_v1` and `bfsfcu_v1`, on invented fixtures. The Capital One card, Capital One bank, Amex and
BFSFCU formats are confirmed from real exports, and the U.S. Bank format is not.
`capital_one_bank_v1` imports only into an account registered with the last four digits its rows
name (D-061). None is to
import into the real ledger until D-059 point F passes on a real file of it. One PDF layout exists,
`us_bank_card_activity_pdf_v1`, for U.S. Bank's printed card activity list, unverified until point F
passes. The owner holds no U.S. Bank card CSV, and `us_bank_v1`
is not that card's format. Fees linked to a parent and transfer groups are not built (D-059 point C).
The M5 gate is open: the owner ran [real-data-readiness.md](real-data-readiness.md) on 2026-11-09, and
real data belongs only in a real ledger on the encrypted image, never in a synthetic one. Only candidate items, decision conflicts and automatically merged transactions
can be acted on.

## Network and dependencies

Stated here once (D-058 point 9, W2).

- **No network but `pf ui`'s loopback and `pf sync`'s, and no other program but three.** No
  module under `src/` imports a network module, runs a program or imports dynamically, except:
  `db/volume_probes.py`, which runs `/usr/sbin/diskutil info -plist` and
  `/usr/bin/hdiutil info -plist`, for a real ledger only, with a 30-second timeout;
  `sync/identity.py`, which runs `/usr/bin/openssl req …` once per identity (D-076 point 2); and
  the two servers below. `tests/unit/test_no_network_imports.py` parses every module and fails on
  any added use, with a failing control for each allowance. Every command but `pf sync pair` and
  `pf sync serve` works with no network connection (PRD §21).
- **One listening socket on loopback** (D-062 point 1). `pf ui` serves pages from
  `ui/server.py`, which W1 allows to import from `http` only `http.server`'s
  `BaseHTTPRequestHandler` and `HTTPServer`. It binds `127.0.0.1` at a port the system picks, with
  no option to change it, looks up no name, and connects to nothing. A request needs the exact
  Host, and the cookie from that launch's one-use key. From M17.1, a security change approved
  with D-073, a `POST` to a route on the allowlist also needs this server's exact `Origin`,
  same-origin fetch metadata when sent, a plain form of at most 8,192 bytes parsed strictly, and
  a single-use HMAC form token bound to the route and every hidden field; it then runs the CLI's
  own command, whose gate and refusals apply. Every other method is refused. Forms work without
  script, and the CSP is unchanged.
- **One listening socket on the local network, only while you run it** (D-076, M20, a security
  change). `pf sync pair` and `pf sync serve` serve HTTPS from `sync/server.py`, the one module W1
  allows `ssl`, with the same two `http.server` classes. They bind one private IPv4 address
  (RFC 1918 only: loopback, link-local, public and wildcard are refused before any socket opens)
  in the foreground, for at most 120 seconds to pair or 60 minutes to serve. They use TLS 1.3 only,
  with the Mac's self-signed P-256 certificate, which the phone pins. A paired device may only
  fetch the snapshot built at the start and acknowledge it, authenticated against the ledger on
  every request. Every answer's body is fixed, and nothing is logged. The key is `0600` in a
  `0700` `sync/` folder beside the ledger, never printed or backed up. Secrets are stored only as
  SHA-256 hashes.
- **Two runtime dependencies.** **pypdf 6.21.2** (D-060 point 1, as amended), pure Python and
  BSD-3-Clause, imported by `ingest/pdf_reader.py` alone. Its one W1 allowance is `subprocess` in
  its `filters.py`, where its JBIG2 image decoder runs `jbig2dec` if that program is on the path.
  The reader runs pypdf with that program unset, so it never runs, and silences pypdf's log,
  which can quote a file's bytes. **segno 1.6.6** (D-076 point 3, fetched once on 2026-11-21),
  pure Python and BSD-3-Clause, imported by `sync/pairing.py` alone for `make_qr(...).matrix`.
  W1 pins each of its seven uses (opening a viewer, a plugin loader, Windows terminal colours,
  URL quoting) to the function that holds it, none on a path pairing takes. Both are pinned by
  version and hash in `requirements.txt`, installed with `--require-hashes`. Otherwise only
  Python 3.12's standard library and its SQLite. Nothing is downloaded or sent at run time: no
  telemetry, no update check and no log (D-037).
- **Development dependencies:** pytest 9.2.0 and Hypothesis 6.170.14, pinned in
  `requirements-dev.txt` without hashes, and setuptools `>=68` to build. Installing them and pypdf
  is the only step that needs a network, once. A later build can use another setuptools, and an editable
  install is untested.
- **The test socket guard** blocks Python sockets in the test process, not subprocesses or native
  code. The suite never runs the two probes. It runs openssl for real, and reaches the sync
  server only over `socket.socketpair()`; the benchmark `--sync` uses loopback TCP.
- **Not covered:** what the interpreter, macOS, or tools run outside `pf` do on the network.

## Acceptance criteria progress

All 47 criteria pass, each mapped to named tests in [m1-acceptance.md](m1-acceptance.md).
A17 is met against the corrected wording in [archive/plan-m1-m2.md](archive/plan-m1-m2.md). A18 is met because M1 has
no logs and its output stays clean (D-037).

**M1 is complete and accepted.** The owner gave final sign-off on 2026-11-06, based on the
acceptance tests and the clean-install verification in [m1-acceptance.md](m1-acceptance.md).
The limitations and deferred benchmarks below still stand.

A39 has provisional benchmarks, met by the figures below (D-034).

The security controls proposal is **not applied** and provides no protection
(D-025).

## Reconciliation measurements

In [benchmarks.md](benchmarks.md). Reconciliation is quadratic in fully overlapping files, in
distinct spellings per block, and in the units of a group a decision touches. On the
100,000-transaction shape every report runs below two seconds, and each write spends about 0.9s
rewriting 20,000 match outcomes (D-057). With 300 category rules each write spends about 0.5s more
rewriting their outcomes, and `totals` runs at 1.9s with or without rules, close to its target
(D-064). With 5,000 allocations each write spends about 0.6s more, `report household` runs in about
1.3s, and setting the share again about 3s, since `h1` covers every shared transaction (D-065).

## Known limitations

- **The browser makes only the writes D-073's allowlist as built names** (review decisions,
  completion and dismissal, the transaction page's classify, categorize, correct, separate,
  one-sided transfer and tags, the buffer, liquidity and coverage links). Everything else,
  including every planning preview-then-add, is made in the terminal. The UI is still one session,
  one request at a time, on loopback only. **The CSP was not checked in a real browser** for the
  visuals' presentation attributes or the forms (D-073 point 6), and no browser has submitted a
  form: the tests post as a browser would, over the real handler.
- **Scenarios project monthly,** with the assumptions `scenario compare` prints: no daily
  timing, inflation, returns or tax. Promotion is terminal only, one active promotion per
  scenario, and maps only point 6's inputs: a loan payoff, a bonus, a borrowing, a home purchase,
  an addition with an end date or without `--account` and `--match` stay scenarios. A withdrawn
  promotion's terms row keeps its date, so a terms row on that same date is refused (D-074).
- **Sync is not checked with a real phone** (YC2): the app (D-079's I3) passes against the real
  server on loopback, but the macOS firewall prompt, a real private address and a real phone are
  the owner's to check by [sync-runbook.md](sync-runbook.md) and [ios/README.md](../ios/README.md).
- **A restored ledger pairs again:** backups leave out the sync key on purpose (D-076 point 2),
  and `sync identity rotate` replaces it.
- **The port is not stored** (the M20.1 slice plan point 7): `--port` defaults to 8443, and
  `serve` shows a reconnect code holding the address, port and fingerprint.
- **A snapshot file is unencrypted** (D-075 point 7): it is to be kept on the encrypted image and
  carried to the phone by hand. Members' parts are monthly totals moved out and in, not D-056's
  five groups. Institution names are left out until the owner decides.
- Tags are free labels on a transaction's whole set, entering no total; no renaming, merging or
  deleting a tag. Search is a plain scan, capped at 500 rows shown.
- Exports are CSV only: transactions with fixed columns, or a report's lines one a row. No PDF,
  image or browser download.
- Categories cover spending only, by a person one transaction at a time, or by category rules on
  spending a person has typed (D-064): no income categories, and no renaming, merging or deleting a
  category (D-063). A ledger shows spending by category only while some categorization reaches a
  transaction or a rule's outcome does. A rule matches only "description contains": no amount
  ranges, priorities or editing, and changing a rule is undo then add (D-064).
- Household attribution is by a person's allocation on a transaction, else the account's default,
  one member or `shared`, with one active share applying to every month of the ledger (D-065
  points 2 and 3). No dated defaults or shares, renaming or removing a member, parts with their own
  categories or types, or account ownership. With 50/50, every odd-cent shared transaction gives its
  cent to the member added first.
- Allocations are made one transaction at a time in the terminal. Disagreeing allocations, one
  whose records end up in several transactions, or one by amount a correction stops summing, leave
  the transaction unattributed, never the account's default, until one is undone.
- An undo, a classification or a transfer that leaves a categorization unsettled does not say so in
  its own output, unlike `review confirm` and `review separate`, which refuse. `totals` and `review
  categorizations` disclose it.

- Income sources count only deposits typed `income`, in one account, whose description contains
  a text: an unclassified match is listed as a possible paycheck and never counted. Two sources
  reaching one deposit leave it to neither. A source has no end date, so pay that stops reads
  `missed` until the source is undone. Pay dates come from the cadence alone, with no weekends or
  holidays, which the date tolerance absorbs (D-068).
- Every command that needs today takes `--as-of`, else reads today in the household timezone, and
  refuses with none set, naming `setting set`. Only the CLI reads the clock (G7).
- Proposals group deposits by exactly equal normalized descriptions, so a payee whose text varies
  (a date or number in it) is never proposed, and a group with a missed paycheck in it fits no
  cadence. Proposals print no token: `income preview --from-proposal` does, over the options
  chosen.
- Obligations reach only money out in spending, so a bill a person has not typed is never counted
  and is not listed. Two obligations reaching one payment leave it to neither, and it is
  discretionary. Like income, an obligation has no end date.
- Fixed and discretionary spending appear in `pf obligations`, `report income` and `report budget`.
  `totals` and `report monthly` are unchanged (G6).
- The `/income` and `/budget` pages read today in the household timezone when given no date, and
  ask for one with no zone set.
- Budgets are calendar months with no rollover, one discretionary allowance a month for the
  household, divided among members by exact amounts and capped by category (D-069). A budget plan
  is changed by superseding it, and an undo that would change a closed month is refused: the plan
  is superseded with `--correct-closed-month` instead. Budget figures are budget pace, never safe
  to spend (M16).
- `report budget` counts possible spending, unclassified money out and unconfirmed transfer kinds,
  against the target until classified, so capacity is provisional while any is left. A category
  cap counts its subcategories. A closed month's correction is disclosed from the plan's
  `--correct-closed-month` flag and the month the plan was made, so a correction made with an
  `--as-of` far from the real date discloses by the real date.
- Funds (M14.1) are planning figures: nothing is assigned automatically, and an assignment says
  what an account's observed balance already holds, never that money moved. An account holds
  assignments up to its latest balance observation on or before the date; below it, the account
  is over-assigned, disclosed and never absorbed. One emergency fund and one tax reserve at a
  time. A fund has no supersession: its terms change from a date, anything else is undo then
  add, and a fund holding an assignment cannot be undone. A fund's start and terms cannot fall
  in a closed month. The tax reserve accrues from received occurrences only.
- A consumption (M14.2) pays from what the assignments active when it was stated still hold, so
  a later assignment never rewrites it; its portion is computed where read, never stored. The
  emergency fund is never consumed. `report budget` takes the portion out of discretionary
  actual; `totals` and categories count the purchase once, unchanged. A fund paying for a
  transaction cannot be undone until each consumption is.
- `report funds` (M14.3) offers as extra only as_of's month's extra paychecks and side income (net
  of its tax accrual) and the latest closed month's unused capacity; a goal with no target takes
  none. Every allocation is planned, never an assignment or a transfer.
- Net worth (M15.1) reads balance observations only. `balance record --from-statement` is not
  built: no statement balance is stored. Net worth by member divides by account attribution.
- Loan projections and payoff orders (M15.2) are projections, not lender-exact: monthly
  interest, no fees, no daily accrual, at most 600 months. A card takes a rate only. Periods may
  start in a closed month, since a schedule is the lender's contract.
- A breakdown (M15.3) is the only change of M12 to M21 to `totals`, `report monthly` and
  `report household`: only where one applies, interest and fees move from confirmed transfers to
  spending, and each divided payment is counted in both groups, disclosed by count.
- Safe to spend (M16) is an estimate until the next salary paycheck, never a balance: the
  latest observation of each liquidity account plus its activity since, with pending and
  unknown-status inflows left out. It is provisional while any of D-072 point 6's reasons holds,
  each printed with what clears it, and it refuses without the household timezone. A card's
  payment obligation is recognised by the card's name in the obligation's name or matcher. A
  loan payment due before `as_of` is not reserved. Nothing is linked automatically: a possible
  double reservation is a warning until `obligation covers` links the pair.
- The local UI is read-only, and shows twelve commands' output only, `report funds`,
  `report net-worth` and `dashboard` the last three. It searches nothing, imports
  nothing, exports nothing and shows no `trace` or decision history, which carry creation
  timestamps (F2). Decisions are made with `pf review` in the terminal (D-062).
- `pf ui` cannot stop what the browser keeps: history (addresses with IDs and months, a fixed
  title) and session-restore snapshots. It asks for a private window. Cookies are not kept apart by
  port, so a page served by another local user on another loopback port, opened while `pf ui`
  runs, receives its cookie. Anything running as the owner can read the ledger anyway.
- A control or format character in a file name shows escaped on a page and as typed in the CLI.
- `pf ui` answers one request at a time, and reruns a real ledger's two volume probes for each.
- Only a person classifies, one transaction at a time. A type must fit the transaction's
  direction. A card, loan or investment payment may be money in on the account it pays, and interest
  is money out only, so interest earned is `income` (D-053, D-054).
- Disagreeing classifications, one whose records end up in several transactions, or one whose
  transaction's amount a correction's undo turns against it, leave the transaction unclassified
  until one is undone. There is no command to settle them other than undo.
- Income and spending count only what a person classified. Unconfirmed transfer kinds and
  unclassified transactions are in neither, and `totals` gives how far that may understate each.
  The only reporting period is the calendar month, in `report monthly` (D-056, D-057).
- A loan payment is never split into principal and interest, so a one-sided one to a loan leaves
  that loan's interest out of spending, with a warning (D-056).
- Inserting a transfer match side scans every match side of its account, because SQLite plans the
  `transfer_match_side_two_accounts` trigger's lookup by `account_id`. Each match a person makes
  pays one scan, and building many matches directly is quadratic. Changing it needs a migration.
- Only a person matches a transfer, one pair at a time, and only a candidate: a transfer-kind type
  on one side, the exactly opposite amount in another account, and dates within 5 days. Fees apart
  from the amount transferred and a transfer split over several transactions are not matched, and
  are not planned yet (D-054, D-055).
- Only a person states a one-sided transfer, naming a registered counterpart account, and only
  while no candidate pairs it with that account and the counterpart's complete coverage does not
  span every day within 5 days. One whose records split, that reaches another match or one-sided
  transfer, whose type stops fitting or is undone, or whose counterpart's other side or covering
  coverage arrives no longer applies until undone. It is never superseded (D-055).
- Balance observations are manual and posted only: no layout carries a balance, and there is no
  available balance or net worth (D-057, points A, B and E). An observation is never superseded:
  undo it and record again. One active per account and day.
- `balance check` counts only transactions. An unresolved record is disclosed for the account but
  placed in no interval, so a difference it causes is not attributed to one.
- `report monthly` judges a month's coverage on the transaction basis only (D-057, point D), so a
  month covered on the posting basis alone reads as not covered. It lists every registered
  account for the ledger, including those with no documents.
- A matched transfer whose sides fall in different months moves each month by its side, disclosed
  by count. Nothing nets them.
- A match binds the records of both transactions when made, so a re-export that does not merge is
  unmatched. A match is never superseded: undo it and match again.
- A match whose side splits, that reaches a transaction another match or a one-sided transfer
  reaches, whose amounts stop offsetting or whose type stops fitting no longer applies until
  undone. `totals` discloses it, and so do undos, but an import summary does not, for either kind.
- Candidates are computed whenever `review transfers` or `totals` runs, quadratic in transactions of
  one amount on nearby dates. Every write rewrites every match's outcome, linear in matches, and
  every one-sided transfer's, which costs one-sided transfers times equal opposite amounts in their
  counterparts. All are measured in [benchmarks.md](benchmarks.md).

- Only `cross_document_candidates` items can be rejected, and only they and decision conflicts can
  be confirmed. External-ID and same-document items stay open.
- A group may hold one record per document, so two alike rows of one file are always separate
  transactions (D-008).
- Superseding by confirmation needs an open item holding the transactions. A rejection that closed
  its item must be undone first. Only one decision can be superseded at a time, by a confirmation
  or, for a confirmation, by a separation. A rejection supersedes nothing.
- A decision binds the records it names, and no decision transfers to a new record. A re-export
  raises the question again, so overlapping exports can bring repeat reviews. `review show` lists
  records alike a decided record to help, and binds nothing.
- Withholding can raise totals through new evidence, though it is disclosed. A decision conflict
  is settled by confirming a partition of all its transactions in one decision. A rejection never
  settles one.
- `review show` escapes file names in its decided section, but its older sections print them as
  typed, so a file name holding a newline can imitate a line there (noted below for all names).
- Setup and both entry points have only been verified on this Mac with Python 3.12.6.
  `bin/pf` needs `.venv` at the root of its checkout.
- A file's counts in an import summary describe the moment it was imported. Later files in
  the same run can change them, so only the run summary and the account lines are final.
- `internal_error` and the unexpected-error message carry no detail by design, so such a
  problem must be reproduced with synthetic data to be diagnosed.
- File and account names are shown as typed, so a name holding sensitive text is displayed
  and stored. The argument parser also echoes invalid option values.
- An interrupted import leaves earlier files in the run committed, with no summary.
- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule, not something the database enforces. Corrections live in their
  own tables, and `ledger_transaction` keeps the primary source's values (D-049).
- Only amount, transaction date, posting date and description can be corrected, and no value can
  be cleared. An unresolved record can be corrected once completed.
- A completion supplies only values the parser could not read, and never a status or an ID. A row
  whose status was unreadable keeps `unknown`. There is no superseding a resolution: undo it, then
  resolve again. Undoing a completion waits for any decision, correction or classification
  binding it.
- A completed record never merges automatically, so a re-export of it is reviewed as a possible
  duplicate. Same-document checks run only at import, so it is never flagged against rows of its
  own file.
- A correction binds the records of its transaction when made. One made after a merge binds more
  records, so a later split gives it `basis_changed` where an earlier correction would not. Item
  and transaction tokens then differ too, because they cover the bound records.
- Disagreeing corrections, or one whose records end up in several transactions, use the source
  value until one is undone. There is no command to settle them other than undo.
- Every correction and reconcile rewrites the account's derived correction rows.
- The database cannot enforce that every transaction has at least one source.
  Tests check this after success, failure and crash.
- A separation names every record of one transaction, at most 50. It splits records a
  confirmation joined only by superseding that confirmation, and does not act on a transaction in
  an open conflict. Automatic moves are recorded in
  `transaction_link_history`, and automatic splits happen only for machine-made merges.
- A separation binds the records it names. A re-export of them is withheld and raised as a
  conflict, so overlapping exports can bring repeat reviews.
- `review decision show` lists every record pair of a separation, up to 1,225 for 50 records.
- Import holds the write lock through reconciliation. At about 100,000 rows in one
  account that can exceed the 5-second wait, so a concurrent writer reports
  `database_busy`. It explains what to do, leaves nothing partial, and a retry succeeds.
- `reconcile` across all accounts commits each account separately. If it stops at a busy
  ledger, accounts already reported stay reconciled and the rest are untouched.
- An ID-bearing row against an ID-less row can only be a possible duplicate, so such
  overlaps stay flagged and counted twice. Revisit for CSV-to-PDF matching (M7).
- Similarity has known misses and false positives (D-032). A miss on rows without
  reliable IDs is counted twice with no flag, unless coverage proves an exact match.
  Rows with a blank description are never matched or flagged.
- An unresolved row with no parsed fields, such as `wrong_column_count`, blocks all
  confident ID-less pairing for its document until it is dismissed or completed (D-050).
- Long runs of repeated purchases become several overlapping review items. Reviewing
  them as a group arrives in M2.
- A transaction merged before migration 0004 shows no primary source until its account is
  reconciled. The account reads as not current until then, and `totals` says so.
- An ID retired before migration 0004 has no stored `created_at`. If revived, it uses its
  first record's link time. `trace` labels that as approximate, but the column itself
  carries no marker. Adding one is a prerequisite before any UI or export presents legacy
  creation timestamps (follow-up F2).
- A multi-step upgrade is atomic per step, not as a whole. After a failure the ledger stays
  at the last good version, and commands refuse it until `migrate` succeeds.
- `review show` does not say whether a transaction also sits in another review item (D-031).
  Its output for a long group is long, and there is no grouped review of long runs yet.
- Nothing consumes the revision token yet. It is shown for M2.2 to use, and today only tests
  compare it. It covers only inputs that exist, and is not a security measure.
- `review show` needs the full item ID. A later import can replace an item, and the ID then
  reads as not found.
- `review show` escapes descriptions and IDs, but prints file names as typed (D-037).
- Coverage can be declared after import with `review coverage declare`, complete or unknown only.
  Coverage a document's metadata states can only be withdrawn. One document at a time (D-051). A
  repeat import with a different declaration still fails with `coverage_conflict`, which names the
  command.
- Only a real ledger keeps originals. A synthetic one stores row contents and the file's hash only.
- A backup is taken only when the owner runs `backup create`: nothing is scheduled or rotated, and
  nothing deletes an old backup. Its manifest is not signed, so it shows accidental change, not a
  deliberate rewrite of both files and manifest. Two disk images whose files share one disk are not
  told apart, so such a backup does not survive losing that disk (D-058 point 7, as amended).
- Two real ledgers in one folder share `originals/`, and each lists the other's originals as not
  referenced. `archive verify` checks content, not modes, and nothing repairs or deletes an
  original. The syncs that make a copy durable are not tested.
- A pending and a posted row with one reliable ID merge whatever their amount. Without one, a changed
  amount raises a candidate for review, never a merge, and many alike descriptions in one block make
  that quadratic. Within one document, only rows D-021 flags, with equal amounts, can be confirmed
  together (D-052).
- After upgrading to rules version 2, every account reads as not current until `reconcile`.
- Identical rows in one document are always separate. This is true of the invented
  layouts and must be proven for each real layout.
- Failed attempts may go unrecorded if the database stays busy. The CLI still
  reports them.
- A file with a large number of rows holds the write lock for the whole import.
  Other writers wait up to 5 seconds and then report `database_busy`.
- `create_database` leaves its file behind if a migration fails, and a later
  attempt then refuses to overwrite it.
- Edited migration files are not detected. Only the version number is tracked.
- A synthetic ledger is not encrypted, and gets `0600` at creation only. An encrypted-disk-image
  ledger is checked for privacy and for an encrypted disk image on every open, and refused rather
  than repaired. The image's password, and the location of the image file itself, are not checked
  (D-058).
- A private-folder ledger (D-081) is encrypted at rest only as its disk is: FileVault on the Mac,
  and in iCloud Drive Apple's encryption, end to end only with Advanced Data Protection on. Neither
  is checked. Its modes are made private on each open rather than refused.
- Nothing stops two computers using one private-folder ledger at once: SQLite's locks do not cross
  a synced folder. A conflict is caught only when the sync client keeps a copy named like
  `ledger 2.db`, and only on the next open. A sync that uploads the database mid-write, between it
  and its `-journal` file, is not detected. Using one computer at a time, and letting the folder
  finish syncing first, is the owner's.
- A ledger's protection cannot be changed. Moving to the other means a new ledger and importing
  the statements again.
- iCloud's Desktop and Documents sync cannot be detected from a path. A real ledger now lives
  under `/Volumes`, which it does not reach, but an image file kept in `~/Desktop` or
  `~/Documents` would sync. The owner confirmed it off on 2026-11-08.
- A ledger is real or synthetic from `init`. A synthetic ledger is never checked, never promoted,
  and nothing stops real data being put in one: that rests on the owner.
- Uppercase extensions such as `.CSV` are ignored only because git sets
  `core.ignorecase` on macOS. On a case-sensitive setup they would not be.
- Amount parsing accepts a small generic syntax. Trailing minus signs and CR/DR
  suffixes are rejected until a layout proves they are needed.
