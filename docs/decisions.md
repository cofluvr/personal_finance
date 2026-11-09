# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-061 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-062 | M8 plan: the local review UI — Approved with A to E, read-only |

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
| PDF text | pypdf alone reads it, pinned by hash, imported by `ingest/pdf_reader.py` only, with `jbig2dec` unset and its log silenced. W1 parses pypdf too, allowing only its JBIG2 decoder's `subprocess` | D-020, D-060 |
| Backups | A new folder, on a mounted volume other than a real ledger's and gated as its folder is, holding the ledger, its referenced originals and a manifest of hashes, sizes, versions and a logical digest. Restore never overwrites, and checks every file, integrity, foreign keys, schema and digest first | D-058 |

## Not yet decided

From `shared-contract.md` §6: safe-to-spend details and loan projection assumptions
(Phase 1B), and pairing protocol and snapshot compatibility (Phase 1C). Transfer matching
was decided in D-054, resource benchmarks in D-057, and backup and recovery in D-058.


## D-062 M8 plan: the local review UI — Approved with A to E, read-only

Proposed on 2026-11-09. Delivers plan.md's M8 row (loopback-only import results, review queue and
transactions; tested by Host and CSRF checks, and UI totals matching the CLI) against PRD-backend §18
and §19 ("local UI bound to loopback", "sensitive descriptions excluded from routine logs", "security
controls must be verified"). Changes none of D-042 to D-061. **Point 1 changes a security control**
(W1, D-058 point 9), and point 3's alternative would add a write path from a browser: both are marked
below, and neither is approved. No dependency is added. Plan only: nothing is built until it is
approved, and then each slice separately. Acceptance tests, UA1 to UD4, are in [plan.md](plan.md).

```sh
pf ui --db DB      # prints http://127.0.0.1:PORT/start?key=..., serves until Ctrl-C
```

**Slices:**

| Slice | Scope |
|---|---|
| M8.1 | One builder per report: the text of `totals`, `report monthly`, `documents`, `transactions`, `review list` and `review show` built as lines in one module, the CLI printing them byte for byte as now (point 6). No server |
| M8.2 | `pf ui`: the loopback server, its protections (points 1, 4 and 5), and the totals and monthly pages |
| M8.3 | Import results (`documents`), transactions, the review queue and one review item, read-only |
| M8.4 | Only if the owner chooses point 3's alternative: review decisions from the browser |

**Recommendations, each with its alternatives:**

1. **Serving pages: `http.server`, fenced as pypdf was. Changes a security control.**
   - `ui/server.py` alone may write `from http.server import BaseHTTPRequestHandler, HTTPServer`,
     and nothing else from `http`, `socket` or `socketserver`. W1 gains the allowance
     `("ui/server.py", "http")`, and a test pins that module's imports of `http` to exactly those two
     names, as `volume_probes.py`'s `subprocess` is pinned to `run`. `SimpleHTTPRequestHandler`
     (serves the working directory), `CGIHTTPRequestHandler` (runs programs) and
     `ThreadingHTTPServer` stay refused by that pin. Every other module keeps every refusal, and
     `http.client`, `urllib` and the rest stay refused in `ui/server.py` too. W1 still does not parse
     the standard library, as now, so what `http.server` imports itself (`socket`, `socketserver`,
     `http.client`, `urllib.parse`) is trusted as Python's own, not checked.
   - **Loopback only, with no option to change it.** The server binds the constant `"127.0.0.1"`
     with port 0, so the system picks a free port each launch, over IPv4 (`AF_INET`, HTTPServer's
     default), with `allow_reuse_address` off. `pf ui` has no `--host` or `--port`. `HTTPServer`'s
     `server_bind` calls `socket.getfqdn`, a reverse name lookup: the subclass skips it and names
     itself `127.0.0.1`, so launching consults no resolver. One request at a time
     (`HTTPServer`, not threading), HTTP/1.0 so each connection closes, and a 10-second socket
     timeout, so one stalled client delays the owner by at most that.
   - **How a test shows it:** W1's AST check that the only server construction passes the constant
     tuple `("127.0.0.1", 0)`; a launch in the test whose `socket.getsockname()` is `127.0.0.1` and
     whose family is `AF_INET`, with `socket.getfqdn` and `gethostbyaddr` replaced by failures.
     Binding calls no `connect`, so the suite's socket guard (A19) stays exactly as it is. Requests
     reach the handler over `socket.socketpair()`, which needs no `connect` either: the real
     `http.server` parsing runs, and no test touches the network guard.
   - Alternatives: **a WSGI server from `wsgiref`** is also standard library but needs the same
     allowance (it imports `http.server`) and adds a layer. **A dependency** (Flask, Starlette with
     uvicorn) is a D-020 decision, brings far more code than the few routes need, and is not
     proposed. **Static HTML files written by the CLI** need no server and no allowance, but write
     financial data to disk (D-037) and cannot show live review state. **A Unix domain socket**
     would let file permissions stop other users, but browsers cannot connect to one.

2. **PRD §18's sections: part of 2 and 3 only.**
   - **In M8:** totals and the monthly report (the only aggregates the CLI has, standing in for no
     "dashboard"), import results as `documents` shows them, transactions as `transactions` lists
     them, the review queue (`review list`) and one item (`review show`).
   - **Left out:** 1 Dashboard, 5 Budgets, goals and planned expenses, and 6 Scenarios need Phase 1B
     features that do not exist (safe-to-spend, budgets, goals). 4 Accounts and household members:
     the CLI has no account list or household model, and adding accounts is a write. 7 Settings and
     backups: backups are writes to another volume, gated as D-058 sets out, and stay in the CLI.
     Search in section 2: no CLI command searches, and description search is a new rule over
     sensitive text (principle 1). Every required visual: categories and goals do not exist, and
     spending over time is the monthly report's numbers, so a chart would add only drawing code. A
     server-drawn SVG of it is a later slice on request. Importing through the browser: uploads are
     writes and file handling. CSV export (PRD's proposed scope) writes a file (D-037). `trace` and
     every decision history: they show creation timestamps (point 7).

3. **Read-only. Decisions stay in the CLI.**
   - The review item page shows the account ID, item ID and revision token, and the `pf review`
     command that decides it, for the owner to run in the terminal, where D-043's checks already
     hold. So M2.1's qualifications 1 and 2 hold unchanged, and qualification 3 by point 4's
     escaping.
   - No route writes: the server answers `GET` alone and opens every ledger connection read-only
     (`mode=ro`), so a forged request, or a bug, cannot change the ledger. plan.md's "CSRF checks"
     are then the refusal of every other method and of a foreign `Origin`, and a ledger unchanged by
     any request (UB5).
   - **Alternative, M8.4: decisions from the browser. Adds a write path, a security change.** Each
     form posts the account ID, item ID and revision token that the page was rendered with, and the
     server calls the very functions the CLI calls (`reject_pairs`, `confirm_groups`), which run
     D-043's order under one write lock: current account first, evidence recomputed inside the
     lock, then account, item ID and token together. Qualification 1 holds since the form carries
     all three and no route takes a token alone. Qualification 2: the UI never reconciles, has no
     reconcile button, and a token from a page rendered before any change (an import, a reconcile,
     another decision, which version 2 tokens cover) refuses, changing nothing. The refusal page
     links to the item again, which renders a fresh token for the owner to read before deciding:
     nothing is resubmitted or accepted for them. A resubmitted form refuses for the same reason.
     The write connection is opened per `POST`, through the same gate. CSRF, on top of point 4: a
     per-session form token in a hidden field, compared in constant time; `Origin` required and
     equal to `http://127.0.0.1:<port>`; a `Sec-Fetch-Site` other than `same-origin` refused when
     present; form encoding only, and a body of at most 8 KB. Recommended against for now: the CLI decides already, and each decision kind
     (reject, confirm with superseding, separate, correct, classify, match, resolve, undo) would
     need its own form, refusals and tests.

4. **Protections, on every response, and who provides them.** `http.server` provides request
   parsing, header limits (100 lines of 65,536 bytes) and nothing else used here: its defaults are
   overridden where they leak (point 5's logging and errors). The standard library provides
   `secrets` (random values), `hmac.compare_digest` (constant-time comparison) and `html.escape`.
   Everything below is written in `ui/server.py`, each with its test:

   | Threat | Protection | Test |
   |---|---|---|
   | DNS rebinding, a foreign Host | `Host` must equal `127.0.0.1:<port>` exactly, the address `pf ui` printed. A missing, repeated, other-port, `localhost`, uppercase-variant, trailing-dot or foreign Host gets a fixed `421` page, before any cookie or ledger is read | UB3 |
   | Other users on this Mac, and other local programs | A per-launch secret: `pf ui` prints `/start?key=<32 random bytes>`. That key works once, for a cookie holding a second random value, `HttpOnly; SameSite=Strict; Path=/`, and redirects to `/`, so the key leaves the address bar. Every other request needs that cookie, compared in constant time, else a fixed `403` with no data. A relaunch makes both values new | UB4 |
   | CSRF, and cross-site reads | `GET` only; every other method `405` with its body unread. `SameSite=Strict` keeps the cookie off cross-site requests. A request whose `Origin` is present and not `http://127.0.0.1:<port>` is refused. Read-only connections (point 3) | UB5 |
   | Injection from a cell | Every value is passed through `shown()` (D-040's escaping of control and format characters, U+202E included) and then `html.escape(quote=True)`, in one rendering function. No data reaches an attribute but an ID, a month or an account ID already validated | UC2 |
   | Scripts, framing, outside assets | `Content-Security-Policy: default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`, and `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-origin`. No JavaScript at all. One stylesheet, a string in the package served at `/style.css`. No page names any address but a path on this server, so it works offline | UB6 |
   | Browser disk cache | `Cache-Control: no-store` on every response | UB6 |

   **Residual, disclosed rather than solved:** anything running as the owner can read the ledger
   anyway (D-058 point A's limit), and could read the cookie from the browser. Cookies are not
   scoped by port, so if the owner, while `pf ui` runs, opens a page served on another loopback port
   by another local user, that server receives the cookie. The browser may keep history (addresses
   carry IDs and months, never amounts or descriptions, and titles are fixed) and session-restore
   snapshots, outside the application: `pf ui` says to use a private window.

5. **D-037 and D-058 on every request.**
   - **No request logging.** The handler overrides `log_message` (which `log_request` and
     `log_error` call) to do nothing, `send_error` to send a fixed page that repeats nothing from the
     request, `version_string` to say `pf` rather than Python's version, and the server's
     `handle_error`, which by default prints a traceback to stderr, to send the fixed unexpected-error
     page. Expected errors map as `main` does, by one shared function (principle 2's second use):
     `CommandError` and `UnsafeLocation` show their sanitized messages, a busy ledger
     `BUSY_EXPLANATION`, anything else `UNEXPECTED_ERROR`. Only the CLI prints: `pf ui` prints the
     address, then nothing until Ctrl-C, which stops it with exit code 0.
   - **Nothing on disk.** The server writes no file. Each request opens the ledger read-only and
     closes it. A real ledger's journal and temporary-store rules are unchanged (D-058 point 4).
   - **The gate on every open.** Each request calls `open_ledger(path, read_only=True)`, so a real
     ledger's location and encrypted-volume checks run per request, as they do per CLI command. `pf
     ui` opens the ledger once before binding, so an unsafe ledger is refused before any port opens.
     Each request runs `diskutil` and `hdiutil` again: that cost is accepted, so an image unmounted
     mid-session refuses the next page.

6. **UI totals match the CLI: one builder per report, the CLI printing its lines.**
   - M8.1 moves each command's output into `reports/report_text.py`: `totals_report_lines`,
     `monthly_report_lines`, `document_list_lines`, `transaction_list_lines`, `review_queue_lines`
     and `review_item_lines`, each taking a connection and the command's validated options and
     returning a list of `ReportLine(text, linked_review_item_id=None)`. Each `run_*` handler opens
     the ledger, calls its builder and prints each line's text. The CLI's output must stay byte for
     byte what it is now: captured in `build/` from the commit before M8.1 on every scenario ledger
     and generated ledgers, and compared after. Nothing about what is computed changes.
   - The UI renders the same lines, one element each, keeping indentation, with an item ID linked to
     its page. `ui/server.py` imports the builders and `open_ledger`, and no computation from
     `reports/` or `reconcile/`, and a test pins that, so the UI cannot total anything itself.
   - **The tests:** the visible text of each page, parsed with `html.parser` and unescaped, equals
     the command's stdout line for line, for the whole ledger, each account and month ranges, on the
     scenario ledgers of M3.4, M4.3 and M7.3 and on the generated ledgers M5.4's restore test builds.
   - Alternatives: **the UI calls each `run_*` with stdout redirected** guarantees equality with no
     move, but redirects a process-wide stream inside a server and finds IDs to link by parsing
     text. **Structured results rendered twice** (tables in HTML, text in the CLI) allow richer pages
     but leave two renderings to agree, comparing numbers rather than output.

7. **No creation timestamps, so F2 does not come first.** None of the six commands prints one: D-040
   keeps timestamps out of review evidence, `transactions` and `documents` print none, and totals and
   reports are aggregates. `trace` and the decision histories print them, and stay out (point 2). A
   test builds a ledger with an ID retired before migration 0004 and finds no timestamp on any page.
   A later slice showing `trace` needs F2's marker first.

8. **Acceptance IDs: two letters, `U` then the slice.** Every single letter is taken. No acceptance ID has two
   letters, and two capitals followed by a number appear in `docs/`, `src/` and `tests/` only as
   `AA11` and `RC4`, neither a criterion, checked on 2026-11-09. M8.1 is UA, M8.2 UB, M8.3 UC and M8.4 UD.

**Not in M8:** point 2's sections and visuals, search, browser imports, exports, decisions unless
point 3's alternative is chosen, `trace`, account management, backups, any address but `127.0.0.1`,
HTTPS (no certificate is needed on loopback, and one would be a secret to keep), access from another
device (Phase 1C's sync), JavaScript, a dependency, F2, F3, and the security proposal (D-025).

**For the owner's decision, with the lead engineer's recommendation first:**

- **A. Point 1's W1 allowance, a security change:** `http.server`'s two classes in `ui/server.py`
  alone, bound to `127.0.0.1` with no option. Alternatively no server, and no M8 as planned.
- **B. Read-only (point 3).** Alternatively M8.4, decisions from the browser, a second security
  change.
- **C. Point 4's cookie from a single-use launch key.** Alternatively the secret in every address
  (`/<secret>/...`), simpler, but kept in history and on every link; or HTTP Basic authentication,
  whose password the browser offers to store.
- **D. Point 6's line builders,** a refactor of the CLI's output gated on byte-identical output.
- **E. The scope of point 2,** and the slices M8.1 to M8.3 in that order.

**The owner's review, on 2026-11-09.** A to E approved as recommended: W1's allowance for
`http.server` in `ui/server.py`, a read-only M8 with decisions left to `pf review` in the terminal
(M8.4 not built), the launch key and cookie, the line builders, and the scope. M8.1 to M8.3
approved to build in order, each gated on the full suite and committed locally.

**How M8.1 was implemented:**

- `reports/report_text.py` holds the six builders, `account_choices` for the UI, and everything
  their text needs, moved from `cli.py` unchanged but for `print` becoming `out.add`: the notices
  and explanations, the `describe_*` helpers, and the `print_*` helpers, renamed `add_*` since they
  print nothing. `trace`, `review merge show`, `review transaction show` and the import summary use
  the moved helpers and still print. `review_item_report` also returns the item's ID, kind, account
  ID and revision token, for the item page's terminal commands.
- **Compared byte for byte:** the suite was run on the code before M8.1 with `--basetemp` in
  `build/`, keeping every ledger it built, 2,284 of them. The six commands, with each account,
  three month ranges and every review item, made 30,302 runs on those files before the move and
  again after. 30,300 are identical. The other two are `totals` on a ledger built to overflow
  SQLite's integer range, where an unexpected error used to follow one printed line and now follows
  none: a builder computes everything before anything is printed. That is the one change, as
  intended by the comment `run_totals` already carried.
- Tests that patched `cli.account_movement`, `cli.load_review_evidence` or `cli.DIRECT_PAIRS_SHOWN`
  to reach `totals` or `review show` now patch `report_text`, and tests importing the moved notices
  import them from there.
- **A test gap closed:** nothing checked that a report for one account leaves another account's
  staleness out. `test_report_text.py` now does, for `totals` and `report monthly`.

**How M8.2 was implemented:**

- **W1's allowance names a module, not a package:** `("ui/server.py", "http.server")`, so `import
  http.client` or `from http import client` there is still refused. Tests pin that module's
  network imports to the two classes, and its one address to `(LOOPBACK_ADDRESS, 0)` with that
  name the constant `127.0.0.1`.
- **What `http.server` needed overriding,** beyond point 5's list: it answers a request it cannot
  read as HTTP/0.9, which has no status line or headers, so the handler's default version is
  HTTP/1.0 and every refusal carries the security headers. Any `do_<METHOD>` lookup but `do_GET`
  returns the refusal, so an unknown method gets `405` too, not `501`.
- **Addresses:** a page takes only the parameters it names, each at most once, each value up to
  100 letters, digits, `-` or `_`, else a `400` before the ledger is opened, so no address is
  decoded. Accounts are chosen by ID in a form that reloads the page by `GET`. An expected error
  shows its message with `400`, and the unexpected one `500`, through `explained_error`, now shared
  with `main`.
- **`pf ui`** opens the ledger through its gate, then binds, prints the one-use address and asks
  for a private window. Ctrl-C stops it with exit code 0: it is how the server ends, so it is not
  the cancellation D-037 leaves uncaught.
- **Tests** (`test_local_ui.py`) send real requests over `socket.socketpair()`, so the handler's
  parsing is real and nothing connects. The pages equal `totals` and `report monthly` on a ledger
  with duplicates, types, a one-sided transfer and a stale account, on M7.3's CSV and PDF counting
  once, and on M4.3's generated ledgers, whose builder is now `generated_ledger()` for both tests.
- **Three test gaps closed** by deliberate breaks: `handle_error`'s traceback, HTML in account names
  on these pages, and a refused address told apart from an unknown account.
