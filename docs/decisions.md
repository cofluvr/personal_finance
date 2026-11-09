# Decision Log

Required by `shared-contract.md` §6. Newest decisions go at the end, and a
replaced decision is marked rather than deleted.

Status values:

- **Approved:** agreed by the owner.
- **Default:** chosen by the lead engineer; open to change.
- **Pending:** must be decided by the milestone shown.

Status of the code behind each decision is in [status.md](status.md).

The full text of D-001 to D-059 is in [decisions-d001-d052.md](decisions-d001-d052.md). This file
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
| D-060 | M7 plan: text PDF statements, and CSV and PDF counting once — Approved, points 1 to 3 and 5 amended, M7.1 to M7.3 built |
| D-061 | Capital One bank format confirmed, and its rows' account number checked — Approved, implemented |

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

## D-060 M7 plan: text PDF statements, and CSV and PDF counting once — Approved, points 1 to 3 and 5 amended, M7.1 to M7.3 built

Proposed on 2026-11-09, for the owner's review. Delivers plan.md's M7 row (text PDFs and CSV-to-PDF
matching, "same activity in both formats counts once") against PRD-backend §5 (statements with
selectable text, extracting "account metadata, transactions, and available balances", balances
never fabricated) and §21 ("overlapping CSV/PDF records count once when confidently matched").
Changes none of D-042 to D-059. One fallback in point 4 would amend D-006, and is proposed only if a
format sample needs it. Point 1 adds the first runtime dependency, a D-020 decision for the owner.
Plan only: nothing is built until it is approved, and then each slice separately. Acceptance tests,
D1 to D14 and I1 to I11, are in [plan.md](plan.md).

**Slices:**

| Slice | Scope |
|---|---|
| M7.1 | Reading a PDF's text: the dependency, `ingest/pdf_reader.py`, `pf pdf text`, W1 extended (point 1). Needs the owner's D-020 approval and one network use, for the install |
| M7.2 | U.S. Bank's statement, `us_bank_statement_v1`: the first PDF layout, its stated period and balances (point 3), its in-document check (point 5), migration 0019. Waits for the owner's format sample (point 2) |
| M7.3 | U.S. Bank's CSV and PDF counting once (point 4) |
| M7.4 | Several accounts in one statement. Built only if U.S. Bank's statement holds them (point 3) |
| M7.5 | Capital One's card statement, `capital_one_card_statement_v1`, matched with `capital_one_card_v1` |

**Recommendations, each with its alternatives:**

1. **Text extraction: pypdf, pinned, as the first runtime dependency.**
   - pypdf is pure Python, BSD-licensed, with no required dependency on Python 3.12, each to be
     confirmed from its metadata at install. A release at least two weeks old, pinned by version and
     hash in a new `requirements.txt`, installed with `--require-hashes`, and declared in
     `pyproject.toml`. One network use, for that install.
   - Imported by one module, `ingest/pdf_reader.py`, which turns bytes into pages of text lines in
     one fixed extraction mode: pypdf's layout mode where the pinned release offers it, since
     statements separate money in and out by column. Nothing else sees pypdf, and its errors are
     caught at that one boundary.
   - W1 is extended to parse the installed pypdf modules with the same refusals. A release that
     imports a network module, `subprocess` or `ctypes`, or runs a program, fails the suite and is
     not adopted.
   - The extractor's version joins the stored parser version (`1+pypdf-<version>`), so an upgrade is
     a new interpretation of new documents, never a silent rereading of stored ones (D-026). The
     same bytes are still skipped on reimport (D-022).
   - Refused, each as a file failure: an encrypted PDF (`encrypted_pdf`, since AES needs a further
     cryptography dependency), one with no text layer (`no_text_layer`, a scan), and one the library
     cannot read (`unreadable_pdf`). If U.S. Bank's statement is encrypted (point 2c), this point
     returns to the owner before M7.1.

   Alternatives: **a standard-library reader** (zlib for streams, and its own parsing of objects,
   content streams, font encodings and character maps) needs no dependency, but is on the order of a
   thousand lines (principle 5) and would be designed blind: a statement's fonts are internal to the
   real file, which no session may read (D-019), and a wrong character map garbles text without
   failing. Recommended only if the owner refuses any dependency. **The owner converting outside
   the app** (Preview's export as text) needs no PDF code, but adds a manual step per statement,
   archives the text rather than the statement (D-017), and leaves line order to macOS.
   **pdfminer.six** brings further dependencies. **pdftotext**, or any program, is refused by W1
   (D-058 point 9), and macOS's PDFKit needs PyObjC.

2. **Layouts, in order: U.S. Bank's statement, then Capital One's card statement.** U.S. Bank first,
   as promised (D-059 point D), paired with `us_bank_v1`. Capital One's card second, because its CSV
   format is confirmed from a real export, so M7.5 tests matching against a known format. Amex,
   Capital One bank and BFSFCU statements are each a later slice on the same pattern, on request.
   What the owner supplies for each, format and structure only, every value invented, as D-059
   point E did:
   - a. **The lines `bin/pf pdf text STATEMENT.pdf` prints** (M7.1) for one statement, run by the
     owner on the image. It writes nothing and opens no ledger. From the account summary to the end
     of the last transaction section, plus one repeated page header and footer. Keep word for word
     every heading, column heading and label (the opening and closing balance labels, section
     names, subtotals), the date format, how money out is shown (a minus sign, its own column, a
     trailing `-`, parentheses), and how a long description wraps. Replace every name, address,
     account number beyond its last four digits, amount, date and description with invented ones of
     the same shape.
   - b. Whether the statement holds more than one account, and if so the lines where the next
     begins.
   - c. Whether it asks for a password, or Preview shows it as secured. **This one is needed before
     M7.1.**
   - d. Two or three transactions as they appear in both the CSV export and the PDF of the same
     period, values invented, each description's wording pattern kept: prefixes, suffixes,
     reference numbers, truncation. This decides point 4.
   - e. For U.S. Bank, the CSV header and a row or two, confirming `us_bank_v1`, as already awaited.

   Each layout is built from that format alone. Its tests read the supplied line structure
   directly, and a PDF generated in the test from those lines checks the reader. Neither shows that
   pypdf reads the real file the same way. Point 5's check does, on every import.

3. **What a statement adds, without reopening D-005, D-027 or D-057:**
   - **The stated period is coverage evidence:** `complete`, `document_metadata`, on the posting
     basis, as D-005's validated layout metadata, since the layout declares that its period lists
     every transaction posted in it. Recorded only when point 5's check agrees with no unresolved
     row, otherwise `partial` with the period, as D-005 asks of a period that does not prove
     completeness. A statement states no generation date, so under D-027 its closing day is not
     established: rows on that day stay possible duplicates against a CSV, disclosed. Reading the
     closing balance as proof of that day would reopen D-027, and is not proposed. A declaration on
     a PDF is refused as `coverage_conflict`, as for any document stating coverage.
   - **The opening and closing balances are neither coverage nor observations.** They are document
     evidence, stored per document and account by migration 0019, append-only, in the ledger's sign
     convention (a card's owed amount negated, D-057). The import's check and `trace` read them.
     `derive()`, `balance check` and every token never do. D-057 keeps observations to what a person
     states, so the owner may still `balance record` them. Making them observations is a later
     decision.
   - **Several accounts in one document are neither:** they are structure. D-005 already keeps
     coverage per account, and each source record carries its account. Until M7.4, a statement
     listing more than one account fails as `multiple_accounts`, importing nothing. M7.4, only if
     needed: one import names each section's account by its printed last four digits (`--account
     NAME --statement-account LAST4`, repeated), every section must be named or the file fails as
     `unmapped_statement_account`, and each section gets its own coverage and check. Importing the
     file once per account is not an option, since D-022 rejects the same bytes under another
     account.
   - A layout states the account types it fits, since a card's balance runs the other way to a
     bank's, and another type fails the file as `account_type_mismatch`.

4. **Matching a PDF row to its CSV counterpart:**
   - **Both sides ID-less, the expected case.** No CSV layout reads an ID (D-059 point B), and a
     statement prints none. D-006's exact rule applies unchanged: the same dates, amount, folded
     description and status class, both documents complete on the same basis over the day, inside
     both effective intervals, not a boundary date, and no unresolved row that could affect the
     count, paired one-for-one by count. The PDF layout states `posted`, as a statement lists posted
     activity, and D-006 compares it as compatible with the CSV's `unknown`. `us_bank_v1` reads only
     the posting date, as a checking statement prints, so the keys align.
   - **Descriptions.** The layout joins a wrapped description with one space, so `fold` sees the
     CSV's text wherever the bank prints the same words. If point 2d shows the PDF adds or drops
     words, exact matching never fires and every overlapping row goes to review: correct, but not
     counting once. Then, and only then, M7.3 asks the owner to amend D-006: under the same coverage
     conditions, a CSV row and a PDF row are a confident pair when each is the only row of that
     account, posting date and amount in its document. Uniqueness makes the pairing unambiguous.
     Two rows of one amount on one day stay possible duplicates, and similarity still never merges
     (D-032). Alternative: a description mapping per pair of layouts, which fails silently when a
     bank changes its wording. Not recommended.
   - **Dates.** Where two layouts read different dates, such as a card CSV with both against a
     statement with one, D-006's material-field rule is applied to the exact key: the basis date
     must be present on both and equal, the other date equal where both have it. Documents of one
     layout have the same dates present, so existing outcomes are unchanged, which a test shows.
     Built in M7.5 only if Capital One's statement needs it.
   - **One side with an ID: D-026's temporary limitation is settled by keeping it.** A row with a
     validated ID pairs only by ID, and against an ID-less row it can only be a possible duplicate,
     as `test_an_id_bearing_row_against_an_id_less_row_can_only_be_a_candidate` pins. No real layout
     reads an ID and none in M7 will, so real data never reaches the case. Letting such a row also
     pair by count would mix ID pairing and count pairing in one transaction, for no layout that
     needs it. It becomes D-026's rule, revisited when a real layout gains
     a guarantee, which needs two overlapping real exports (D-059 point B). Alternative: pair it by
     the exact rule, treating its ID as absent for that comparison.
   - **M1's case still holds.** Nothing merges without D-006's evidence, so each row stays its own
     transaction until confidently matched, and an unmatched overlap is a disclosed possible
     duplicate, never a lost row. Reimporting a PDF changes nothing (D-022). The CSV and PDF of one
     period counting once in either order is I1, by A16's comparison, and a CSV export overlapping
     two statements is I3.

5. **Point F on a PDF layout.** The statement carries its own check, so every PDF import runs it:
   - **Every line of a transaction section is accounted for:** a transaction, a continuation of one,
     or a line the layout names (a heading, a page header or footer, a subtotal). Any other line
     there is an unresolved row, `unrecognized_line`, keeping its text. A line the parser silently
     skips is a PDF's characteristic failure, so none is skipped.
   - **The in-document check.** With no unresolved row, the opening balance plus the parsed rows
     must equal the closing balance to the cent, and any subtotal the layout names must agree. A
     difference fails the file as `statement_out_of_balance`, importing nothing (principle 3): with
     every row parsed, a difference means the layout is wrong. With unresolved rows the check is not
     run, the period is `partial`, and the import says why.
   - **The owner's step,** added to [layout-verification.md](layout-verification.md) in M7.2: import
     one real statement into the throwaway ledger. It passes when it imports with complete coverage
     and no unresolved row, so the check agreed. Then import the CSV export of the same period into
     the same account, declaring that period: `totals` must be unchanged, with no open review group
     but closing-day rows. That verifies point 4 on real data. A PDF layout stays unverified until it
     passes.

6. **Where it is built.** A PDF layout parses a document's lines into rows, the stated period,
   balances and accounts, beside the CSV layouts. `import_files` chooses the reader by the layout and
   stores `format = 'pdf'`, which migration 0001 allows. A row's raw cells are its lines of text and
   its page, so fingerprints and occurrences work as for CSV, and identical rows in one statement
   stay separate (D-008). A date printed without a year takes the one year that places it in the
   period. One that places nowhere leaves the row `invalid_date`. New file failures:
   `encrypted_pdf`, `no_text_layer`, `unreadable_pdf`, `statement_structure_mismatch` (an expected
   heading or label missing, the PDF's `header_mismatch`), `statement_out_of_balance`,
   `multiple_accounts`, `account_type_mismatch` and, in M7.4, `unmapped_statement_account`. New
   unresolved reason: `unrecognized_line`.

**Not in M7:** scanned PDFs and OCR; encrypted PDFs; balances as observations (D-057); the closing
day as covered (D-027); IDs from PDFs, and ID-bearing rows pairing by count; detecting a layout
(`--layout` stays required); a PDF holding several periods; statement lines outside the transaction
sections beyond the balances and the period (rewards, payment due, minimum payment, year-to-date
totals), which stay unread; investment and loan statements; fee parents and split transfers (D-059
point C); the local UI (M8).

**The owner's review, on 2026-11-09.** D-060 approved, with pypdf as the dependency under D-020, and
M7.1 approved to build and commit locally. U.S. Bank's statement opens with no password and Preview
shows it not secured (point 2c), so point 1 stands.

**Point 1, as amended the same day.** The newest pypdf release at least two weeks old, 6.21.2,
failed point 1's own test: its `filters.py` imports `subprocess`, which its JBIG2 image decoder uses
to run `jbig2dec` when that program is on the path. The owner chose to adopt it with a fenced
allowance rather than look for an older release or write a standard-library reader: W1 allows
`subprocess` in pypdf's `filters.py` alone, and only as `run` calls inside its JBIG2 decoder, and
the reader runs pypdf with `jbig2dec` unset, so the program never runs. `jbig2dec` is not installed
on the owner's Mac.

**How M7.1 was implemented:**

- **The dependency.** pypdf 6.21.2, uploaded 2026-10-21, BSD-3-Clause, pure Python, needing
  `typing_extensions` only below Python 3.11, all confirmed from PyPI's metadata. Pinned with its
  wheel's SHA-256 in `requirements.txt`, installed with `--require-hashes --no-deps`, and declared
  in `pyproject.toml`. The network was used for PyPI's release list and that one install, and is
  closed.
- **`ingest/pdf_reader.py`** returns each page's lines in pypdf's layout mode, which keeps columns
  placed apart, where plain mode joins them with one space. Trailing spaces and blank lines are
  dropped, and a blank page keeps its place. An encrypted PDF is refused before any page is read,
  even one that opens with an empty password. Any error inside pypdf is `unreadable_pdf`, and a PDF
  whose pages hold no text is `no_text_layer`. `EXTRACTOR_VERSION` names the pypdf release, for the
  stored parser version from M7.2.
- **pypdf's log.** Its warnings can quote a file's bytes, such as `invalid pdf header: b'Date,'`,
  and Python prints them to stderr when no handler takes them. The reader gives pypdf's logger a
  null handler and stops it propagating. Its `warnings.warn` calls are API deprecations only, so
  nothing filters warnings. D-037's source rule refuses `logging` in `src/`, so it now allows it in
  `pdf_reader.py` alone, and a test pins that its only uses are that null handler and propagation,
  so no record is ever written.
- **The launcher tests** (D-038) gave each copied checkout a standard-library-only environment, to
  show the application needed no package. Each now gets the declared runtime dependencies copied
  from the project's `.venv`, with no network, showing it needs nothing more.
- **`pf pdf text FILE`** prints each page's lines, escaped as D-037, opening no ledger and writing
  nothing. A failure prints only its code, with exit code 2.
- **Tests.** PDFs are written by `tests/synthetic_pdf.py`, standard library only. The JBIG2 fence is
  shown with `subprocess.run` replaced by a failure: under a configuration naming a program, the
  decoder runs it without the reader and refuses inside it, and a PDF holding a JBIG2 image reads
  without running anything. pypdf's text extraction never decodes an image, so no file reaches the
  decoder through the reader: the promised test "fails as `unreadable_pdf`" became these two.
  pytest attaches its log capture to pypdf's logger, so the log is tested by running `bin/pf` in a
  subprocess, whose stderr must be the error line alone.
- **Moved to M7.2:** D2's import of a failing PDF and D4's stored parser version, since no PDF layout
  exists to import with.


**Points 2, 3 and 5, as amended for U.S. Bank's printout, on 2026-11-09.** The owner supplied the
structure of U.S. Bank's document, values redacted, and asked for M7.2, M7.3 and M7.5 to be built
unattended. The document is a credit card's Recent Activity List printed from the website, not a
statement: one account, unencrypted, each entry on one line with its account line below, a
printout header on every page, and no period or balance. So, without reopening D-005, D-027 or
D-057:

- **Coverage is a user declaration,** on the posting basis, as for the CSV layouts. Point 3's
  stated period and point 5's in-document check have nothing to read, so neither is built, nor
  migration 0019 for balances (principle 1). D8 to D11 of the plan fall away for this layout, and
  point F uses the card statement's balances, as in M6.
- **Every line is still accounted for** (point 5): a line the layout does not know is an
  `unrecognized_line` row, and an entry with no account line a `missing_account_line` row. The
  page header and `Posted` are required, else `statement_structure_mismatch`.
- **Several accounts are refused by the account line:** every entry names its card, which must be
  the account's `--last4`, as D-061 and the owner directed. `multiple_accounts` is not needed, and
  M7.4 is not built.
- **The CSV counterpart is not `us_bank_v1`.** The owner's card CSV rows hold a date `MM/DD/YYYY`,
  the description, a signed amount with a charge positive, and the account, where `us_bank_v1`
  expects `Date, Transaction, Name, Memo, Amount` with ISO dates. Its header was not supplied, so no
  production layout is written for it (D-059 point E). M7.3 shows the matching with a test-only
  layout of those fields.
- **M7.5 is not built:** no Capital One card PDF's structure has been supplied.

**How M7.2 was implemented:**

- **`us_bank_card_activity_pdf_v1`** in `ingest/layouts.py`, described in
  [layouts.md](layouts.md). A layout now states its `file_format`, how `group_lines` turns a PDF's
  pages into rows of cells, the `account_types` it fits, and `row_account_number`, which replaced
  D-061's column name so a row can name its account inside a line. Capital One bank's check reads
  the same way.
- **`ingest/pdf_documents.py`** reads a PDF layout's document, and `csv_reader.raw_records`, now
  shared, numbers rows and fingerprints their cells, so identical PDF entries stay separate
  (D-008). `import_files` reads by the layout's format and stores it in `source_document.format`.
- **Checks before rows are stored:** the account type (`account_type_mismatch`), then the
  structure, then each row's account number. Each fails the file, importing nothing.
- **Tests:** `tests/scenarios/test_us_bank_activity_pdf.py`, on printouts written in the test with
  invented values, positioned as the owner's, with an account line after a page break. D2's
  import half and D4's stored parser version are tested here.
- **Breaks:** 16 applied, 13 caught. `$` stripping was dead code, since `parse_cents` reads `$`, and
  was deleted. A branch for an account line without digits was unreachable and was removed. A last
  entry with no account line was a test gap, now closed and caught.

**How M7.3 was implemented.** No code: D-006's exact rule already counts the same activity once.
The owner's samples show the CSV and the printout with the same date, the same description and the
same signed amount, so point 4's amendment of D-006 and its date rule are not needed, and I7 and I11
fall away. `tests/scenarios/test_csv_pdf_matching.py` pairs the printout with a test-only CSV
layout of the owner's CSV fields, under an invented header, both declared complete on the posting
basis: I1 in either order by A16's comparison, I2 for a missing declaration, another basis, a row
outside an interval and an unresolved row, I3 for a CSV spanning two printouts, I4 for identical
rows, I5 for D-026's limitation as kept, and I6 for unchanged `totals` and `report monthly` output.
A declaration vouches for its whole end date (D-007), so no closing-day row stays a possible
duplicate. Breaks: 8 applied to the rules it relies on, 6 caught here. The different-basis and
boundary-date checks cannot change this pairing, since the CSV's rows carry no transaction date and
declared coverage has no boundary day, and both are caught by `tests/unit/test_cross_document.py`.
The real pairing waits for a production layout of U.S. Bank's card CSV, then one I1 test on it.
## D-061 Capital One bank format confirmed, and its rows' account number checked — Approved, implemented

Directed by the owner on 2026-11-09, outside M7's slices, with the header and two rows of each of
two real Capital One exports, a 360 Performance Savings account and a 360 Checking account. No
value from them is kept in this repository: the fixtures invent every value, keeping the format.

**The format matches `capital_one_bank_v1` as built,** so no parser changed: the exact header,
`MM/DD/YY` dates, `Transaction Amount` never negative with `Transaction Type` `Debit` or `Credit`
giving its direction, and `Balance` a running balance after each row, newest first. Amounts drop
trailing zeros (`1400`, `14.1`), which the parser already read. The fixture now lists newest first
in that style, with a Zelle receipt and a web payment in the wording the exports showed. Still
assumed: the date is the transaction date, and the export holds posted transactions only, which
D-059 point F checks.

**The owner's choices on the account layer,** each recommended by the lead engineer:

1. **The Account Number is checked.** Each row names its account's last four digits. A layout may
   name such a column, and `capital_one_bank_v1` names `Account Number`. Every row of a new
   document must name the importing account's registered last four digits (`pf account add
   --last4`), or the file fails as `account_number_mismatch`, importing nothing, so the savings
   export cannot import into checking. A row too short to hold the column is unresolved as before,
   and is not checked. An account registered without last four digits fails the file as
   `account_number_unknown`: nothing would show which account the file belongs to. A repeat import
   of identical bytes is unchanged (D-022). Files that pass are read exactly as before, so the
   layout keeps its ID and parser version: the check refuses files, and changes no meaning.
2. **A transfer between the two accounts uses M3.2 unchanged.** The savings export's "Withdrawal
   to 360 Checking" row, classified `transfer`, is a candidate against the checking deposit of the
   opposite amount, and `review transfer match` matches them (D-054). A scenario test shows it on
   invented exports. The checking side's wording is a guess, which matching never reads.

**Open:** `pf` has no command to change an account, so an account added without last four digits
cannot gain them. If the real ledger holds such a Capital One bank account, setting them once, never
changing them after, is a follow-up for the owner's approval.

**Tests:** `tests/scenarios/test_capital_one_accounts.py`, and the layout's J1 to J7 case on the
new fixture, with its account's last four digits. Seven deliberate breaks of the check, all caught.
