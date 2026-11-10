# Benchmarks

Reconciliation measurements, moved out of [status.md](status.md) on 2026-11-08, unchanged. Read
this when a task touches performance or adds a benchmark, and add new measurements here.


Measured 2026-11-05 with `tests/benchmarks/measure_reconciliation.py`.

**Machine:** Mac14,7 with an Apple M2, 8 cores, 8 GB memory, macOS 27.2, Python 3.12.6,
SQLite 3.45.3. Other work on the machine was not controlled.

**Fixtures:** one account, `synthetic_card_v1`, unknown coverage, 24 monthly files. Each
later file repeats the last 10% of the month before.

| Fixture | Parameters |
|---|---|
| Ordinary | Seed 7, 400 merchants, random amounts from 1.00 to 199.99, random day in the month |
| Dense | One merchant, one amount (5.00), rows spread evenly over 30 days |

**What a timing covers:** one `import_files` call, which reads and parses the file,
writes records, reconciles the account and commits. Setup is excluded: generating data,
writing the CSV files and creating the database.

| Fixture | Rows a month | Source records | Logical transactions | Last import | Slowest import | All 24 imports |
|---|---|---|---|---|---|---|
| Ordinary | 200 | 5,260 | 5,260 | 0.14s | 0.14s | 1.84s |
| Ordinary | 1,000 | 26,300 | 26,300 | 0.90s | 0.90s | 11.44s |
| Ordinary | 4,000 | 105,200 | 105,200 | 4.92s | 4.92s | 61.34s |
| Dense | 200 | 5,260 | 5,260 | 0.16s | 0.16s | 2.03s |
| Dense | 1,000 | 26,300 | 26,300 | 1.16s | 1.18s | 14.19s |
| Dense | 4,000 | 105,200 | 105,200 | 5.32s | 5.57s | 67.74s |

The 4,000-row fixtures meet the D-034 benchmarks.

Unknown coverage means nothing merges, so source records equal logical transactions.
These fixtures therefore measure candidate discovery, not the cost of applying many
merges at once.

**Known stress limitations, which are not covered by the benchmarks:**

- Full re-exports of 2,000 dense rows: 6 files took 2.48s in total, 12 files 8.04s and 24
  files 32.38s. Candidate steps were 59,985, 263,934 and 1,103,724, so work grows about 4
  times each time the file count doubles. **This is quadratic in overlapping files.**
- 12 re-exports of 8,000 dense rows: 96,000 records, slowest import 6.09s, 39.45s in total.
- Distinct spellings of one amount in one similarity block, derivation alone, measured
  before the closeout, which did not change this code: 1,000 took 0.45s, 2,000 took
  1.85s, 5,000 took 10.24s and 10,000 took 40.72s. **This is quadratic in distinct
  spellings.** It is not expected in practice, but nothing prevents it.
- These are measurements of these shapes, not general guarantees. The expected dataset of
  about 100,000 rows across 30 accounts is nearer the smallest rows above.

**Dense constrained groups (S16),** measured 2026-11-06 on the same machine with
`measure_reconciliation.py --constrained`. Each candidate group is one amount, date and description
across two unmerged documents, the worst shape for this code. Discovery stores no pairs (D-031), so
any group a constraint touches has its direct links compared again, pair by pair.

| Units in the group | Derivation, no constraints | One constraint | Constraints on 10% of units | Pairs compared |
|---|---|---|---|---|
| 100 | 0.001s | 0.005s | 0.005s | 4,950 |
| 500 | 0.004s | 0.115s | 0.112s | 124,750 |
| 1,000 | 0.008s | 0.479s | 1.056s | 499,500 |
| 2,000 | 0.037s | 2.611s | 1.898s | 1,999,000 |
| 4,000 | 0.046s | 7.542s | 9.613s | 7,998,000 |

**This is quadratic in the units of a touched group.** Doubling the group compares 4 times as many
pairs, and the number of constraints does not change that count. Every later import and reconcile of that account
pays it. Groups no constraint touches are not recomputed. Matching semantics were not changed to
reduce this. A real ledger holds such a group only if the same amount and description recur within
the date window across thousands of rows.

| Transactions in the item | Loading evidence and token | Whole `review reject`, under the write lock | Undo token and preview | Whole `review undo`, under the write lock |
|---|---|---|---|---|
| 100 | 0.006s | 0.013s | 0.008s | 0.012s |
| 500 | 0.016s | 0.162s | 0.123s | 0.132s |
| 1,000 | 0.031s | 0.499s | 0.531s | 0.509s |
| 2,000 | 0.066s | 2.170s | 1.962s | 3.105s |

The first version of `review reject` took 19.6s at 2,000 because validation listed every direct
pair in the item. It now checks only the stated pairs. `review show` lists at most 50 pairs for the
same reason. These timings vary by up to about 2 times between runs here, and other work on the
machine was not controlled. Pairs compared are exact.

**Confirmation (C19),** measured 2026-11-07 on the same machine with
`measure_reconciliation.py --confirmed`. Three unmerged documents, so that a confirmed transaction
still links with the third and stays in the group, which is the worst shape. With only two
documents a confirmed transaction holds both and links with nothing, which made confirmation look
far cheaper than it is. That first run was discarded.

| Units in the group | One rejection | One confirmation | One partition | Confirmations on 10% | Partitions on 10% |
|---|---|---|---|---|---|
| 100 | 0.006s | 0.001s | 0.006s | 0.001s | 0.004s |
| 500 | 0.130s | 0.004s | 0.132s | 0.004s | 0.102s |
| 1,000 | 0.576s | 0.009s | 0.563s | 0.008s | 0.443s |
| 2,000 | 2.118s | 0.017s | 2.046s | 0.018s | 1.590s |
| 4,000 | 8.573s | 0.034s | 8.333s | 0.032s | 6.277s |

Derivation alone. A confirmation that only joins writes no `different_event` pair, so it touches no
group and compares nothing again. A partition keeps its groups apart, which touches the group just
as a rejection does, and costs the same. Confirmed units are fewer, so many confirmations compare
slightly fewer pairs.

| Transactions in the item | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,001 | Rejection | 2.189s | 2.118s | 2.145s | 2.129s |
| 2,001 | Confirmation | 0.106s | 0.037s | 0.067s | 0.109s |
| 2,001 | Partition | 2.247s | 2.181s | 2.174s | 2.250s |

Through a real ledger, under the write lock. Smaller items scale the same way, and the full output
is in `build/m2.3-bench/confirmed.txt`, which is ignored and may not survive. **Confirmation does
not make the quadratic recomputation worse.** A partition costs what a rejection costs, within the
variation of these runs, and a plain confirmation costs far less. Matching was not changed.

**Separation (P19),** measured 2026-11-07 on the same machine with
`measure_reconciliation.py --separated`. Two documents with complete coverage pair every row exactly,
and a third of unknown coverage holds the same rows, so every merge and every separated record
links with all of the third, in one group. With only the two merging documents a separated record
would link with nothing, which would make separating look far cheaper than it is.

| Merges | Units in the group | One rejection | One partition | One separation | Separations on 10% | Pairs compared, one separation | On 10% |
|---|---|---|---|---|---|---|---|
| 50 | 100 | 0.005s | 0.005s | 0.005s | 0.005s | 5,050 | 5,460 |
| 250 | 500 | 0.110s | 0.112s | 0.122s | 0.127s | 125,250 | 137,550 |
| 500 | 1,000 | 0.444s | 0.523s | 0.436s | 0.495s | 500,500 | 550,725 |
| 1,000 | 2,000 | 1.720s | 1.706s | 1.664s | 1.881s | 2,001,000 | 2,203,950 |
| 2,000 | 4,000 | 6.957s | 6.817s | 6.614s | 7.726s | 8,002,000 | 8,817,900 |

Derivation alone. A rejection and a partition compare n(n − 1)/2 pairs for n units. A separation
touches the group the same way and adds one unit for each record it takes out of a merge, so ten
percent of merges separated makes about ten percent more units and about ten percent more pairs.

| Transactions | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,000 | Rejection | 1.892s | 1.740s | 1.754s | 1.764s |
| 2,000 | Separation | 1.690s | 1.740s | 1.812s | 1.783s |

Through a real ledger, under the write lock. A rejection of the merged transaction against a row of
the third file is the baseline, since a partition into single transactions on a candidate item is
refused (D-046). Smaller ledgers scale the same way, and the full output is in
`build/m2.4-bench/separated.txt`, which is ignored and may not survive. **Separating does not make
the quadratic recomputation worse** than a rejection or a partition, apart from the units it adds.
Matching was not changed.

**Superseding (N18),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --superseded`. Three unmerged documents, so that a record separated from
a confirmed pair still links with all of the third, in one group. A partition keeps a confirmed
pair apart from a record of the third. A separation superseding a plain confirmation leaves only its
pair of different events, which touches the group the same way.

| Units in the group | One partition | One superseding separation | Partitions on 1 in 30 | Superseding on 1 in 30 | Pairs compared, superseding |
|---|---|---|---|---|---|
| 100 | 0.006s | 0.006s | 0.005s | 0.006s | 4,950 |
| 500 | 0.131s | 0.128s | 0.120s | 0.128s | 124,750 |
| 1,000 | 0.513s | 0.516s | 0.468s | 0.512s | 499,500 |
| 2,000 | 2.412s | 2.100s | 1.887s | 2.077s | 1,999,000 |
| 4,000 | 8.940s | 8.472s | 9.083s | 10.261s | 7,998,000 |

Derivation alone. Partitions compare slightly fewer pairs because their confirmed pairs are one unit,
while a superseding separation leaves both records as units.

| Transactions | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,001 | Partition | 2.340s | 2.077s | 2.228s | 2.185s |
| 2,001 | Superseding separation | 2.662s | 2.151s | 2.145s | 2.272s |

Through a real ledger, under the write lock. The confirmation being superseded is made first and not
timed. Smaller ledgers scale the same way, and the full output is in `build/m2.5-bench/superseded.txt`,
which is ignored and may not survive. **A superseding separation does not make the quadratic
recomputation worse** than a partition, within the variation of these runs. Matching was not changed.

`decision_states` read 50 chained decisions in 0.0001s and 2,000 in 0.0016s, reading each decision
once. The alike listing in `review show` stops at the 51 it needs: 0.0014s on 2,000 lookalike
transactions and 0.023s on 20,000. Its first version built every match before printing 50, a million
at 2,000 lookalikes taking 0.99s, and was made lazy.

**Corrections (V18),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --corrected`. Full output is in `build/m2.6-bench/corrected.txt`, which is
ignored and may not survive.

First, three unmerged files of one dense group with a partition touching it, the shape where
derivation is quadratic. A correction moves no record, so it does not derive, while the later import
pays derivation in full. This shape reaches that cost: the later import takes 2.1s at 2,000.

| Transactions | Transaction show and token | Correct | Later import | Correction show and token | Undo |
|---|---|---|---|---|---|
| 98 | 0.000s | 0.001s | 0.010s | 0.001s | 0.001s |
| 500 | 0.000s | 0.002s | 0.137s | 0.002s | 0.003s |
| 998 | 0.000s | 0.002s | 0.523s | 0.003s | 0.006s |
| 2,000 | 0.001s | 0.003s | 2.104s | 0.007s | 0.012s |

Second, one account where every transaction but one has an active amount correction. Every
correction and every reconcile rewrites the account's derived rows, which is linear in corrections.

| Corrections | Rewrite of derived rows | Totals | Transaction show and one correction | Later import |
|---|---|---|---|---|
| 99 | 0.002s | 0.000s | 0.003s | 0.005s |
| 499 | 0.010s | 0.001s | 0.016s | 0.023s |
| 999 | 0.013s | 0.001s | 0.032s | 0.032s |
| 1,999 | 0.022s | 0.002s | 0.048s | 0.060s |
| 3,999 | 0.065s | 0.006s | 0.113s | 0.152s |

A chain of 50 corrections reads its states in 0.0001s and 2,000 in 0.0017s, and correction show on
the newest of 2,000 takes 0.011s. **Corrections add no quadratic recomputation.** A correction stays
below a later import of the same account in every row, though with thousands of corrections and
nothing else to derive the two are close, because both rewrite every derived row. Matching was not
changed.

**Resolutions (U19),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --resolved`. Two exports of the same purchases under complete coverage, with
one row of the first that the parser cannot read. That row blocks every confident pair, so resolving it
pays for every merge it unblocks, and undoing it for every split. The shape asserts that it does:
merged and split equal the pairs in every run. Full output is in `build/m2.7-bench/`, which is ignored
and may not survive.

| Kind | Pairs | Item show | Resolve | Later import | Resolution show | Undo |
|---|---|---|---|---|---|---|
| Dismiss | 500 | 0.005s | 0.243s | 0.044s | 0.128s | 0.408s |
| Dismiss | 2,000 | 0.002s | 1.141s | 0.222s | 0.526s | 1.962s |
| Dismiss | 5,000 | 0.003 to 0.059s | 1.094 to 4.568s | 0.305 to 0.440s | 0.788 to 1.046s | 3.116 to 11.551s |
| Complete | 500 | 0.001s | 0.132s | 0.039s | 0.106s | 0.220s |
| Complete | 2,000 | 0.004s | 1.217s | 0.738s | 0.545s | 2.132s |
| Complete | 5,000 | 0.004 to 0.014s | 1.500 to 3.023s | 0.235 to 0.886s | 0.561 to 1.510s | 2.611 to 5.420s |

The 5,000 rows were run three times, and the machine was loaded during the first run. For comparison,
an import that makes the same merges, the second export into a ledger without the unreadable row,
took 0.238s at 500, 1.309s at 2,000 and 6.745s at 5,000. **A resolution costs what the merges or
splits it causes cost.** The later import in the table merges nothing, so it is cheaper by design.
D-050's stop rule compared against that import, which this shows to be the wrong comparison.
Matching was not changed.

**Coverage declarations (K17),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --declared`. Two exports of the same purchases, the first of unknown
coverage and the second complete. Declaring the first complete pays for every merge that makes, and
the shape asserts it: merged and split equal the pairs. The last column imports the second export into
a ledger where the first was declared complete at import, which makes the same merges. Full output is
in `build/m2.8-bench/declared.txt`, which is ignored and may not survive.

| Pairs | Coverage show | Declare | Later import | Undo show | Undo | Merging import |
|---|---|---|---|---|---|---|
| 500 | 0.000s | 0.060s | 0.017s | 0.029s | 0.104s | 0.073s |
| 2,000 | 0.000s | 0.298s | 0.067s | 0.112s | 0.492s | 0.439s |
| 5,000 | 0.000s | 0.864s | 0.165s | 0.308s | 1.415s | 1.892s |

**A declaration costs no more than an import making the same merges.** Matching was not changed.

**Pending to posted (Q17),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --pending`. A pending export and a posted export of the same purchases on
one day, each posted at another amount. The shape asserts that it raises pending-to-posted
candidates. Full output is in `build/m2.9-bench/pending.txt`, which is ignored and may not survive.

| Descriptions | Pairs | Items | Steps | Posted import | Derive | Later import |
|---|---|---|---|---|---|---|
| Distinct merchants | 100 | 100 | 100 | 0.018s | 0.005s | 0.010s |
| Distinct merchants | 500 | 500 | 500 | 0.082s | 0.031s | 0.045s |
| Distinct merchants | 2,000 | 2,000 | 2,000 | 0.470s | 0.153s | 0.214s |
| One block | 100 | 1 | 10,000 | 0.066s | 0.057s | 0.064s |
| One block | 500 | 1 | 250,000 | 1.462s | 1.491s | 1.435s |
| One block | 2,000 | 1 | 4,000,000 | 24.021s | 40.590s | 30.960s |

The first version compared every pending unit with every posted unit in its window, so distinct
merchants cost what one block now costs: 4,000,000 steps and 35s at 2,000. **Distinct merchants are now
linear.** In one block every description is alike under D-032, so every pending row really is related
to every posted row, the output is one item of 4,000 transactions, and the cost is quadratic and paid
by every later import. That is the documented limit of distinct spellings per block, reached here
through amounts that differ.

**Classifications (F14),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --classified`. Full output is in `build/m3.1-bench/classified.txt`, which
is ignored and may not survive.

First, the dense shape of the corrections, three unmerged files of one group with a partition
touching it. A classification moves no record, so it does not derive, while the later import pays
derivation in full: 2.4s at 2,000. The partition's undo token covers the classification under both
derivations, and costs the same with it as without.

| Transactions | Transaction show | Classify | Later import | Classification show | Undo | Decision show before, after |
|---|---|---|---|---|---|---|
| 98 | 0.000s | 0.001s | 0.010s | 0.001s | 0.001s | 0.010s, 0.010s |
| 500 | 0.001s | 0.002s | 0.155s | 0.005s | 0.031s | 0.162s, 0.160s |
| 998 | 0.001s | 0.003s | 0.594s | 0.004s | 0.005s | 0.623s, 0.618s |
| 2,000 | 0.001s | 0.005s | 2.397s | 0.012s | 0.009s | 2.767s, 2.398s |

Second, one account where every transaction but one has an active classification. Every import,
correction and classification rewrites the account's derived rows. The shape asserts that every one
applies.

| Classifications | Rewrite | Totals | Show and classify | Show and correct | Classification show | Later import |
|---|---|---|---|---|---|---|
| 99 | 0.001s | 0.001s | 0.003s | 0.003s | 0.002s | 0.006s |
| 499 | 0.005s | 0.001s | 0.011s | 0.010s | 0.009s | 0.019s |
| 999 | 0.011s | 0.002s | 0.024s | 0.021s | 0.015s | 0.037s |
| 1,999 | 0.021s | 0.004s | 0.044s | 0.043s | 0.034s | 0.079s |
| 3,999 | 0.041s | 0.008s | 0.093s | 0.086s | 0.064s | 0.159s |

A chain of 2,000 reads its states in 0.0019s, and classification show on its newest takes 0.012s.
**Classifications add no quadratic recomputation.** `--corrected` rerun on the same code matches the
M2.6 figures above within noise, before and after the rewrite lost its early return, so ledgers
without classifications pay nothing measurable.


**Transfers (X14),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --transfers`. Full output is in `build/m3.2-bench/transfers.txt`, which is
ignored and may not survive.

First, a checking and a savings account where every transaction but one pair is matched, written
directly. Every import, decision, correction and classification in either account rewrites every
match's outcome. The shape asserts that the later import rewrites them once, all of them, and that
every one applies.

| Matches | Rewrite | Totals | Show and match | Show and undo | Later import |
|---|---|---|---|---|---|
| 100 | 0.002s | 0.001s | 0.006s | 0.004s | 0.007s |
| 1,000 | 0.022s | 0.009s | 0.048s | 0.034s | 0.061s |
| 4,000 | 0.103s | 0.039s | 0.222s | 0.152s | 0.259s |

Second, candidates, computed whenever `review transfers` or `totals` runs. Distinct amounts give one
candidate per transfer-kind transaction. Equal amounts on one day give every pair, which is the
quadratic case, and the shape asserts that count.

| Shape | Transactions per account | Candidates | List | Totals |
|---|---|---|---|---|
| Distinct amounts | 1,000 | 1,000 | 0.008s | 0.009s |
| Distinct amounts | 4,000 | 4,000 | 0.034s | 0.042s |
| One amount, one day | 50 | 2,500 | 0.004s | 0.004s |
| One amount, one day | 200 | 40,000 | 0.064s | 0.070s |
| One amount, one day | 400 | 160,000 | 0.272s | 0.314s |

**Matches add linear work to every write, and candidates are quadratic only in one amount on nearby
dates.**

**One-sided transfers (O14),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --one-sided`. Full output is in `build/m3.3-bench/one-sided.txt`, which
is ignored and may not survive.

A checking account of equal outflows on 01/10, each classified as a transfer and all but one stated
one-sided, written directly, against a savings counterpart holding equal opposite inflows on 01/20,
outside the window, and single-day documents of complete coverage outside the window. Each
outcome then checks every opposite inflow as a pair and finds none, and reads every span. The shape
asserts that the later import, into the counterpart, rewrites every statement once and that every
one applies. "Show and state" rewrites twice, once to write and once to check that it applies.

| One-sided | Opposite amounts | Spans | Rewrite | Totals | Show and state | Show and undo | Later import |
|---|---|---|---|---|---|---|---|
| 100 | 1 | 1 | 0.003s | 0.000s | 0.007s | 0.004s | 0.005s |
| 1,000 | 1 | 1 | 0.025s | 0.002s | 0.057s | 0.034s | 0.029s |
| 100 | 1,000 | 1 | 0.345s | 0.000s | 0.693s | 0.339s | 0.785s |
| 1,000 | 1,000 | 1 | 3.449s | 0.002s | 6.981s | 3.465s | 3.911s |
| 1,000 | 1 | 300 | 0.067s | 0.002s | 0.139s | 0.077s | 0.097s |
| 1,000 | 1,000 | 300 | 3.526s | 0.002s | 7.059s | 3.550s | 4.042s |

The M3.2 transfers shapes, rerun on M3.3's code (`build/m3.3-bench/transfers.txt`), are unchanged
within noise up to 1,000 matches. At 4,000 the rewrite takes 0.147s against 0.103s, from bookkeeping
both kinds share, and stays linear.

**One-sided transfers cost every write their count times the equal opposite amounts in their
counterparts.** Coverage spans add little, because they are read once per counterpart. Only many
equal amounts in one counterpart make it quadratic, and a date filter on the search would remove
that, if needed.

**Income and spending (T12),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --income`. Full output is in `build/m3.4-bench/`, which is ignored and
may not survive.

Count matched pairs, one-sided transfers, unconfirmed transfer kinds, purchases, income and
unclassified inflows, written directly, with amounts that differ by group so nothing is a candidate.
The groups ask, for each transaction, whether an applied match or one-sided transfer names it. The
shape asserts every group's count, that every match and statement applies, and no candidates.
"Transfers" is the existing transfer summary, which runs the candidate search.

| Count | Transactions | Applied effects | Groups | Account movement | Transfers |
|---|---|---|---|---|---|
| 1,000 | 7,000 | 2,000 | 0.017s | 0.011s | 0.034s |
| 4,000 | 28,000 | 8,000 | 0.088s | 0.052s | 0.166s |
| 8,000 | 56,000 | 16,000 | 0.243s | 0.186s | 0.410s |

**The groups are linear,** and grow as account movement does. A lookup that cannot use the effect
indexes, tried as a deliberate break, took 0.722s and 11.359s at 1,000 and 4,000, so the shape
reaches the quadratic cost it guards against.

**Writes fail above 32,766 transactions bound by transfers.** At 16,000 matches and 16,000 one-sided
transfers, building the shape failed in `write_transfer_effects` with SQLite's "too many SQL
variables", because it passes one per bound transaction. This is M3.2 and M3.3 code, left for the
owner's review with M3.4.

**The 100,000-transaction shape (M4.4, Z1 to Z5),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --scale`. Full output is in `build/m4.4-bench/`, which is ignored and may
not survive.

100,000 transactions over 60 months (2022-01 to 2026-12) in four accounts, checking, savings, a
card and a loan, imported as one `synthetic_checking_v1` file per account and month, each declaring
complete coverage of its month: transaction basis for checking and savings, posting basis for the
card and loan. Written directly: 20,000 applied matches on four routes, so 40,000 matched sides
(above 32,766), about 10% of them crossing months; 2,000 one-sided transfers to an investment
account with no documents; 53,000 applied classifications; and 240 month-end balance observations,
each interval agreeing. The shape asserts every count, no open review items, 60 months in the
report, agreement in every interval, and that the classification and the import each rewrite all
20,000 match outcomes. Building it takes about 170s, most of it the imports and the quadratic
match-side trigger in [status.md](status.md).

| Operation | Time | Provisional target |
|---|---|---|
| `pf totals` | 1.389s | Below 2s: met |
| `pf report monthly` | 0.629s | Below 2s: met |
| `pf balance check`, checking, 59 intervals | 0.047s | Below 2s: met |
| One classification, a savings inflow | 1.275s, of which 0.885s rewrites every match outcome | None |
| One import of one row into savings | 2.013s, of which 0.976s rewrites every match outcome | None |

Reports are timed through the CLI, output discarded, so they include opening the ledger and the
stale-account check. An earlier run on the same shape gave 1.544s for `totals` and 1.006s for
`report monthly`, so the margin under two seconds varies between runs.

**The shape reaches the variable limit (Z3).** Run on a copy of the source with M4.1 reversed
(`build/z3-pre-m41/`), it fails while building, in `transaction_facts` called by
`write_transfer_effects`, with "too many SQL variables".

**Every write pays for every match.** About 0.9s of each write above is rewriting the 20,000 match
outcomes, linear in matches, as recorded for M3.2. Writes have no PRD target yet. If one is set,
this rewrite is the cost behind it, and changing it is its own decision (D-057, Z5).

**Category rules on the 100,000-transaction shape (M10.3, RC4, D-064 point 9),** measured
2026-11-10 with `measure_reconciliation.py --scale --category-rules 300`, nothing else running.
Full output is in `build/m10/bench/`, which is ignored and may not survive.

M4.4's shape, then 300 rules written directly over its spending descriptions, number prefixes so
that shorter ones reach what longer ones do, their categories cycling so that some agree and some
disagree, every fifth narrowed to an account, a type or a first date, and 500 person's
categorizations on card purchases the rules reach. The shape asserts its counts: of 26,000 spending
transactions, rules categorize 15,664 and leave 1,075 in `rule_conflict`, and a person's
categorization comes first on 500, reached by 28 rules. The timed rule changes 2,002 transactions.

| Operation | 300 rules | No rules, same session | Provisional target |
|---|---|---|---|
| `pf totals` | 1.906s | 1.951s | Below 2s: met, narrowly |
| `pf report monthly` | 0.880s | 0.764s | Below 2s: met |
| `pf category rule preview` | 0.796s | | None, stopping rule below |
| `rule add`, under the write lock | 1.199s | | None, stopping rule below |
| `rule undo`, under the write lock | 1.182s | | None |
| One classification | 2.027s | 1.626s | None |
| One import of one row | 3.077s | 2.528s | None |

**Point 9's stopping rule is not met:** a preview and an add each cost less than twice the import of
one row, and both reports run below two seconds. Rewriting 300 rules' outcomes on every write adds
about 0.4s to a classification and 0.55s to an import, linear in rules and spending transactions.
`totals` reads the derived outcome, so rules add nothing measurable to it, but its margin under two
seconds is thin with or without rules: M4.4 recorded 1.389s on this shape, and the same machine gave
1.951s with no rules in this session. A run made while the suite's deliberate breaks were running
gave 2.219s for `totals`, which is why these figures were taken with nothing else running.
