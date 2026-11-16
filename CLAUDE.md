# personal_finance: standing rules

Loaded every session. These rules hold for the whole project. Current state, the next task and
the reading list are in [docs/handoff.md](docs/handoff.md): read it first.

## Session rules

- You are the lead engineer. Work only inside this repository and start every command from it.
- Do not read external memory, user-level configuration, or parent or sibling directories, and do
  not write scratchpad files outside the repository. Synthetic pytest temporary artifacts are the
  only exception.
- Use `build/` for walkthroughs, breaks and benchmarks, with `TMPDIR=build/tmp`.
- Before changing anything: confirm the branch named in the handoff, a clean working tree, and run
  the suite with a real exit code.
- Do only what the owner's task says. Do not reopen D-042 to D-061 unless you find a concrete
  contradiction. A new milestone needs its own plan as the next free decision number, and approval
  before any of it is built.
- No network, no GitHub, no new dependencies, no security changes, unless the owner's task for this
  session explicitly allows them. Pushing needs the owner's explicit approval each time.
- Synthetic data only.

**Never approved, and not to be assumed:** rewriting history; modifying the parent repository;
reading real statements, databases, backups or credentials, or the owner's data folder, disk images
or backup volume (paths in the handoff's "Current state"); applying the security proposal.

## Working principles

Given by the owner on 2026-11-08, for the entirety of the project:

1. Don't build it until you need it.
2. Extract patterns after the second duplication, not before.
3. Explicit errors beat silent failures: fail fast.
4. Write the obvious solution, and optimize only if needed.
5. Delete aggressively: less code means fewer bugs.
6. Name variables, parameters and API endpoints semantically, with verbose, self-documenting names
   that optimize for comprehension by both humans and LLMs, not brevity.

Much existing code uses short names such as `held`, `bound` and `rows`. Principle 6 applies to new
and changed code. Renaming existing code wholesale is a separate change for the owner to approve.

## Qualifications on M2.1, binding later slices

1. **Revision tokens:** decision commands must validate account, item ID and revision token
   together. A matching token alone does not identify a decision target.
2. **Stale accounts:** before accepting a decision, the workflow must ensure the displayed evidence
   is current. Never silently reconcile changed evidence and then accept an old token.
3. **Output escaping:** keep the escaping, and the tests for embedded newlines and terminal control
   characters.

## Commit hygiene

- Gate every commit on pytest's own exit code, chained as in `pytest -q && git commit`. A pipe such
  as `pytest | tail` hides that exit code (zsh has no `PIPESTATUS`). `bd095bf` is a broken commit
  made when they were not chained, and history is not rewritten to remove it.
- While a slice is in progress, gate each commit on the test files for the code it changes and the
  scenario files that exercise it. Gate the last commit before stopping for review on the full
  suite (duration in the handoff's latest gating run). If a gate fails, rerun only the failing
  tests with `pytest --lf` while fixing, then rerun the gate itself before committing.

## Testing for review

Set by the owner on 2026-11-08. The bar: every break must be caught by a relevant test, or be shown
to be a test gap, closed, or equivalent code. A test that fails on unbroken code proves nothing
about a deliberate break.

1. **Fewer, targeted breaks.** About 20 to 25 a slice (G12 for M12 onward), aimed at refusals,
   money and direction rules, token inputs, and the new invariants and migrations. Skip wording,
   messages and paths that only save work.
2. **Narrow first.** Run each break against the one or two test files that cover the broken code,
   with the most relevant file first. Widen to the slice's wider set only for a break that survives
   there, before calling it a gap.
3. **Stop at the first failure.** Run breaks with `pytest -x -q --tb=no`. One relevant failure is a
   catch. Record which test failed, and treat a catch by an unrelated test as a survivor.
4. **Rerun only what needs it.** On the final code, rerun only the breaks that survived, those whose
   target code changed since, and those that did not apply.
5. **The unbroken control** still runs once, on the same narrow files, before any break.
6. **No repeat runs** of a test file to look for flakiness, unless the work touches random or
   order-dependent tests.
7. **Parallel worktrees** only if a break run still takes more than about 15 minutes: two to four
   worktrees under `build/`, each with its own `TMPDIR`. No new dependency for it.

Report the counts: applied, caught, survived and why, and rerun. Check that a benchmark shape can
reach the cost it claims to measure.

## Lessons for new work

- **Migration tests** that build a ledger at the latest version and set it back break when a newer
  migration adds tables. Each migration's tests stop at their own version or drop newer tables.
- **Order dependence.** `pair_up`'s first transaction follows content hashes, and generated IDs are
  random, so tests name files rather than assume an order. A test that failed at random once took the
  credit for four surviving breaks.
- **Deliberate breaks.** Removing a loop's only line is a syntax error, not a catch: use `pass`. A
  replacement that renames a function is a bad break. A break that matches nothing must stop the
  script, not run on unchanged code. Give every break run a fresh bytecode cache
  (`PYTHONPYCACHEPREFIX`): in M4.2 a stale `.pyc` credited a catch to the wrong break.
- **Closed review items.** D-045 closes an item by removing it. Only D-052's same-document
  pending and posted items stay as `resolved` rows, so a test about resolved items needs that shape.
- **A broader refusal can stand in for the one under test.** Test each refusal on a state where it
  alone applies. A schema test must refuse on the trigger under test alone (M5.1, M11.2).
- **Tests that pass for the wrong reason.** Give each schema refusal a control insert that succeeds.
  Pass test helper arguments by keyword. Count the tests actually run: a nested function or a test
  class imported by name changes the count.
- **Renaming a test** breaks `docs/m1-acceptance.md` if a criterion names it. Gate such a commit on
  `tests/unit/test_acceptance_matrix.py` too.
- **Check the schema before planning a case.** Read the table's CHECKs before designing for a state.
- **New command groups** need adding to the test `Ledger.run` helper, which inserts `--db` after
  the group's words.
- **Name benchmark rows by stable keys.** Key by account and external ID, never by generated ID
  order. Benchmarks must be able to reach the cost they claim to measure: three documents, not two,
  are needed for a confirmation to link anything.
- **Privacy checks against an amount** must strip ISO timestamps first (`16.502Z` holds `6.50`).
- **Learn an outside tool's output from a real run before designing on it** (diskutil in M5.2).
- **Shell.** Never pipe a gate: redirect to a file and chain the commit to pytest itself. An
  unquoted `--include=*.py` fails, and `echo ====` is read as a command. `mktemp -d` ignores
  `TMPDIR` here. The harness refuses `rm -rf` of a `build/` folder, so use a new folder.
- **Long runs read the source live.** Run a baseline from `git archive HEAD` under `build/`, and an
  after-capture from a copy of `src/`. The export has no `.git` or `.venv`, so
  `test_ignore_rules.py`, `test_entry_point.py` and one `test_pdf_reader.py` test fail there by
  design, 16 in all.
- **A break that renames a key** of token material keeps the data in the digest: drop it instead.
- **Import cycles in `planning/`.** Effects modules may import `planning/schedules.py` (pure) but
  never `planning/entries.py`, `reconcile.decisions` or `reports.totals`. Report figures go in
  `reports/`.
- **A G1 test must assert before it reassigns.**
- **A benchmark's first command after a long build runs slow** (about 1.2s in M12.3). Attribute a
  cost on one ledger in one session before calling the stopping rule.
- **The suite's ledgers and a suite gate compete.** Run a G6 capture and a full-suite gate apart.

## Keeping the docs small

At the end of a task:

- Replace [docs/handoff.md](docs/handoff.md)'s state rather than appending to it, and rewrite its
  "Next task" section for the next session: task, reading list, warnings, stopping point. Move the
  finished milestone's "as built" section and anything only historical to
  [docs/archive/handoff-history.md](docs/archive/handoff-history.md).
- Record each fact in one place: standing rules here, rules of the product in decisions, current
  limits in status, measurements in benchmarks, history in git and the archive. Link rather than
  restate. Never restate this file's rules in the handoff or a kickoff prompt.
- When a decision is accepted and a newer one is written, move its full text to
  [docs/decisions-d001-d052.md](docs/decisions-d001-d052.md) and keep its index line.
- Report test runs and break results in the commit message or the session report, and in the
  handoff only the latest gating run.
- Write session boundary notes only when something went wrong.
