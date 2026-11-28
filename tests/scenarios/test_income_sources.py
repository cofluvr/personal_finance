"""Income sources stated by a person, end to end, using synthetic data only (IA1 to IA7, D-068 and
its M12.1 slice plan)."""

import itertools
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from planning_digest import evidence_digest
from migration_checks import markers, migrations_up_to
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    HOUSEHOLD_TABLES,
    INCOME_TABLES,
    drop_income_tables,
)
from test_one_sided_transfers import OneSidedLedger
from test_supersession import holding

from personal_finance.db.backups import logical_digest
from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.planning import income_sources
from personal_finance.planning.income_sources import (
    AMOUNT_INVALID,
    AMOUNT_TOLERANCE_INVALID,
    ANCHOR_OFF_CADENCE,
    CADENCE_INVALID,
    MEMBER_UNKNOWN,
    NAME_BLANK,
    NAME_TAKEN,
    PROPOSAL_NOT_FOUND,
    SALARY_CADENCE,
    SAME_MATCHER,
    SOURCE_NOT_ACTIVE,
    SOURCE_NOT_FOUND,
    SOURCE_SUPERSEDED,
    STALE_INCOME_PREVIEW,
    STALE_INCOME_REVISION,
    SUPERSEDE_ACCOUNT_DIFFERS,
    SUPERSEDE_TERMS_GIVEN,
    TERMS_CADENCE_PAIR,
    TERMS_CLOSED_MONTH,
    TERMS_NOT_LATER,
    TERMS_REQUIRED,
    TEXT_BLANK,
    TOLERANCE_DAYS_RANGE,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT

PAYROLL = "SYNTHETIC PAYROLL"
VERSION_23_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES)
TOKEN = r"in1-[0-9a-f]{16}"


class IncomeLedger(OneSidedLedger):
    def deposit(self, name, day, amount="2500.00", text=PAYROLL, financial_type="income",
                account="A"):
        """One checking row in its own file, typed financial_type unless None."""
        row = f"{name.removesuffix('.csv')},{day},{day},{text},{amount},POSTED"
        self.load_path(self.write(name, "Transaction ID,Transaction Date,Posted Date,"
                                        "Description,Amount,Status\n", [row]),
                       account=account, layout="synthetic_checking_v1")
        transaction = holding(self, name)
        if financial_type:
            self.classified = getattr(self, "classified", {})
            self.classified[transaction] = self.classify_ok(transaction, financial_type,
                                                            account=account)
        return transaction

    def classification_of(self, transaction):
        return self.classified[transaction]

    def source_words(self, name="Pay", kind="salary", match="synthetic payroll",
                     cadence="biweekly", anchor="2026-01-02", amount="2500.00", account="A",
                     tolerance_days=None, amount_tolerance=None, member=None, tax_eligible=False,
                     from_proposal=None, supersedes=None):
        words = ["--account", account, "--name", name, "--kind", kind, "--match", match]
        for option, value in (("--cadence", cadence), ("--anchor", anchor), ("--amount", amount),
                              ("--tolerance-days", tolerance_days),
                              ("--amount-tolerance", amount_tolerance), ("--member", member),
                              ("--from-proposal", from_proposal), ("--supersedes", supersedes)):
            if value is not None:
                words += [option, str(value)]
        if tax_eligible:
            words.append("--tax-eligible")
        return words

    def preview(self, **options):
        return self.run("income", "preview", *self.source_words(**options))

    def preview_ok(self, **options):
        code, out, err = self.preview(**options)
        assert (code, err) == (0, ""), err
        return out

    def preview_revision(self, **options):
        return re.search(rf"Revision: ({TOKEN})", self.preview_ok(**options))[1]

    def add(self, revision=None, **options):
        return self.run("income", "add", *self.source_words(**options), "--revision",
                        revision or self.preview_revision(**options))

    def add_ok(self, **options):
        code, out, err = self.add(**options)
        assert (code, err) == (0, ""), err
        return re.search(r"Income source (\S+) recorded", out)[1]

    def show(self, source, as_of="2026-12-31"):
        code, out, err = self.run("income", "source", "show", source, "--as-of", as_of)
        assert code == 0, err
        return out

    def token(self, source, kind):
        return re.search(rf"{kind} revision: ({TOKEN})", self.show(source))[1]

    def terms(self, source, effective_from, amount, as_of="2026-01-01", revision=None,
              cadence=None, anchor=None):
        words = ["income", "terms", source, "--effective-from", effective_from, "--amount",
                 amount, "--as-of", as_of, "--revision", revision or self.token(source, "Terms")]
        if cadence:
            words += ["--cadence", cadence]
        if anchor:
            words += ["--anchor", anchor]
        return self.run(*words)

    def undo(self, source, revision=None):
        return self.run("income", "undo", source, "--revision",
                        revision or self.token(source, "Undo"))

    def outcomes(self):
        """Each reached deposit as its file names, its source's name, state and pay date."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (tuple(sorted(names[transaction_id])), source, state, nominal)
            for transaction_id, source, state, nominal in conn.execute(
                """SELECT derived.transaction_id, source.name, derived.state,
                          derived.nominal_date
                   FROM transaction_income_source derived
                   JOIN income_source source ON source.id = derived.source_id""")
        )
        conn.close()
        return found

    def income_tables(self):
        return self.dump(INCOME_TABLES)

    def evidence(self):
        conn = self.conn()
        try:
            return evidence_digest(conn)
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    return IncomeLedger(tmp_path, capsys)


@pytest.fixture
def paid(ledger):
    """Three biweekly paychecks from Friday 2026-01-02, typed income."""
    for name, day in (("p1.csv", "2026-01-02"), ("p2.csv", "2026-01-16"),
                      ("p3.csv", "2026-01-30")):
        ledger.deposit(name, day)
    return ledger


# IA1: the migration and the append-only tables.

SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("review", "classifications"), ("category", "rules"),
                          ("household", "members"), ("review", "allocations")]


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        *SHOWN_BEFORE_AND_AFTER, ("review", "transaction", "show", holding(ledger, "p1.csv")))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Checking A holding a paycheck typed income, set back to 23, with what was shown before."""
    ledger = IncomeLedger(tmp_path, capsys)
    ledger.deposit("p1.csv", "2026-01-02")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_income_tables(conn)
    conn.execute("PRAGMA user_version = 23")
    conn.close()
    return ledger


class TestMigration:  # IA1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_23_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-four", 24)) == 24
        for table in INCOME_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_23_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_23_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("income", "sources")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("income", "sources")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 24)
        newest = load_migrations()[23].path
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_23_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 23
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(INCOME_TABLES)
        conn.close()
        assert populated.dump(VERSION_23_TABLES) == before


@pytest.fixture
def history(paid):
    """A source with a later terms row, and a second one undone."""
    source = paid.add_ok()
    assert paid.terms(source, "2026-03-06", "2600.00")[0] == 0
    other = paid.add_ok(name="Other", match="payroll")
    assert paid.undo(other)[0] == 0
    return paid


class TestAppendOnly:  # IA1
    @pytest.mark.parametrize("statement", [
        "UPDATE income_source SET name = name",
        "DELETE FROM income_source",
        "INSERT INTO income_source SELECT * FROM income_source",
        "UPDATE income_source_terms SET amount_cents = amount_cents",
        "DELETE FROM income_source_terms",
        "INSERT INTO income_source_terms (chain_id, effective_from, cadence, anchor, amount_cents) "
        "SELECT chain_id, effective_from, cadence, anchor, amount_cents FROM income_source_terms",
        "UPDATE income_source_event SET event = event",
        "DELETE FROM income_source_event",
        "INSERT INTO income_source_event (source_id, event) SELECT source_id, event "
        "FROM income_source_event",
    ])
    def test_history_refuses_change(self, history, statement):
        before = history.income_tables()
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.income_tables() == before

    def test_a_control_insert_of_each_succeeds(self, history):
        conn = history.conn()
        account = history.account_id("A")
        conn.execute("""INSERT INTO income_source (id, account_id, name, kind, description_contains,
                                                   normalization_version, tolerance_days,
                                                   amount_tolerance_cents, tax_eligible, chain_id)
                        VALUES ('new', ?, 'New', 'side', 'x', 1, 3, 0, 0, 'new')""", (account,))
        conn.execute("""INSERT INTO income_source_terms (chain_id, effective_from, cadence, anchor,
                                                         amount_cents)
                        VALUES ('new', '2026-01-01', 'weekly', '2026-01-01', 1)""")
        conn.execute("INSERT INTO income_source_event (source_id, event) VALUES ('new', 'made')")
        conn.close()

    @pytest.mark.parametrize(("columns", "values"), [
        ("cadence, first_day", "'semimonthly', 15"),
        ("cadence", "'monthly'"),
        ("cadence, first_day", "'weekly', 3"),
        ("cadence, first_day, interval_months", "'every_months', 3, 1"),
        ("cadence, amount_cents", "'weekly', 0"),
    ])
    def test_terms_refuse_a_shape_their_cadence_does_not_take(self, history, columns, values):
        conn = history.conn()
        chain = conn.execute("SELECT chain_id FROM income_source_terms LIMIT 1").fetchone()[0]
        fields = dict(zip([name.strip() for name in columns.split(",")],
                          [value.strip() for value in values.split(",")], strict=True))
        fields.setdefault("amount_cents", "1")
        names, values = ", ".join(fields), ", ".join(fields.values())
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"""INSERT INTO income_source_terms (chain_id, effective_from, anchor,
                                                              {names})
                             VALUES (?, '2027-01-01', '2027-01-01', {values})""", (chain,))
        conn.close()


# IA3: what a source reaches.

class TestReach:  # IA3
    def test_only_income_typed_money_in_whose_description_contains_its_text(self, ledger):
        ledger.add_account("B")
        ledger.deposit("pay.csv", "2026-01-02")
        ledger.deposit("refund.csv", "2026-01-16", financial_type="refund")
        ledger.deposit("other.csv", "2026-01-16", text="SYNTHETIC BONUS")
        ledger.deposit("out.csv", "2026-01-16", amount="-2500.00", financial_type="purchase")
        ledger.deposit("elsewhere.csv", "2026-01-16", account="B")
        ledger.add_ok()
        assert ledger.outcomes() == [(("pay.csv",), "Pay", "received", "2026-01-02")]

    def test_a_source_on_another_account_reaches_none_of_these(self, ledger):
        # With sources on both accounts, both accounts' deposits are read.
        ledger.add_account("B")
        ledger.deposit("pay.csv", "2026-01-02")
        ledger.deposit("elsewhere.csv", "2026-01-02", account="B")
        ledger.add_ok()
        ledger.add_ok(name="Bonus", match="synthetic bonus", account="B")
        assert ledger.outcomes() == [(("pay.csv",), "Pay", "received", "2026-01-02")]

    def test_a_corrected_description_is_what_it_reads(self, ledger):
        transaction = ledger.deposit("pay.csv", "2026-01-02", text="SYNTHETIC BONUS")
        ledger.add_ok()
        assert ledger.outcomes() == []
        ledger.correct_ok(transaction, "description", "Synthetic   PAYROLL 01")
        assert ledger.outcomes() == [(("pay.csv",), "Pay", "received", "2026-01-02")]

    def test_an_unclassified_match_is_a_possible_paycheck_never_counted(self, ledger):
        transaction = ledger.deposit("pay.csv", "2026-01-02", financial_type=None)
        source = ledger.add_ok()
        assert ledger.outcomes() == []
        shown = ledger.show(source, as_of="2026-01-10")
        assert "Possible paychecks, unclassified, never counted: 1" in shown
        assert f"Transaction {transaction}:" in shown
        assert "2026-01-02 (baseline): missed" in shown

    def test_two_sources_on_one_deposit_count_toward_neither(self, ledger):
        ledger.deposit("pay.csv", "2026-01-02")
        first = ledger.add_ok()
        preview = ledger.preview_ok(name="Again", match="payroll")
        assert f"source_conflict with {first}, counted toward neither" in preview
        second = ledger.add_ok(name="Again", match="payroll")
        assert ledger.outcomes() == [(("pay.csv",), "Again", "source_conflict", None),
                                     (("pay.csv",), "Pay", "source_conflict", None)]
        assert f"source_conflict with {second}" in ledger.show(first)
        assert ledger.undo(second)[0] == 0
        assert ledger.outcomes() == [(("pay.csv",), "Pay", "received", "2026-01-02")]

    def test_a_confirmed_transfer_is_not_a_possible_paycheck(self, ledger):
        ledger.add_account("S", "savings")
        inflow = ledger.deposit("pay.csv", "2026-01-02", financial_type=None)
        source = ledger.add_ok()
        assert "Possible paychecks, unclassified, never counted: 1" in ledger.show(source)
        outflow = ledger.deposit("move.csv", "2026-01-02", amount="-2500.00",
                                 financial_type="transfer", account="S")
        ledger.match_ok(outflow, inflow, account="S", counterpart_account="A")
        assert "Possible paychecks, unclassified, never counted: 0" in ledger.show(source)

    def test_a_later_import_is_reached_and_a_repeat_changes_nothing(self, ledger):
        ledger.add_ok()
        ledger.deposit("pay.csv", "2026-01-02")
        before = ledger.outcomes()
        assert before == [(("pay.csv",), "Pay", "received", "2026-01-02")]
        ledger.load_path(ledger.folder / "pay.csv", layout="synthetic_checking_v1")
        assert ledger.outcomes() == before


# IA4: pairing and its states.

class TestStates:  # IA4
    def test_each_state_is_produced(self, ledger):
        ledger.deposit("on.csv", "2026-01-02")
        ledger.deposit("raised.csv", "2026-01-16", amount="2600.00")
        ledger.deposit("again.csv", "2026-01-17")
        source = ledger.add_ok()
        # The pay date 2026-01-30 is expected until its 3 days have passed, on 2026-02-03.
        shown = ledger.show(source, as_of="2026-02-02")
        assert re.search(r"2026-01-02 \(baseline\): received, expected 2500\.00, received "
                         r"2500\.00 on 2026-01-02", shown)
        assert "2026-01-16 (baseline): amount_changed, expected 2500.00, received 2600.00" in shown
        assert "2026-01-30 (extra): expected, expected 2500.00" in shown
        assert "differs by 100.00" in shown
        assert re.search(r"Transaction \S+: A, 2026-01-17, 2500\.00, SYNTHETIC PAYROLL: "
                         r"unscheduled", shown)
        assert "2026-01-30 (extra): missed" in ledger.show(source, as_of="2026-02-03")

    def test_missed_and_expected_change_no_token(self, paid):
        source = paid.add_ok()
        tokens = {paid.run("income", "source", "show", source, "--as-of", as_of)[1].split(
            "Pay dates as of")[1].split("Reaches:")[1] for as_of in ("2026-01-01", "2027-06-30")}
        assert len(tokens) == 1

    def test_an_as_of_must_be_a_date(self, paid):
        source = paid.add_ok()
        code, _, err = paid.run("income", "source", "show", source, "--as-of", "2026-02-30")
        assert code == 2 and "--as-of must be a date" in err


FILES = {
    "a.csv": ("2026-01-01", "2500.00"),
    "b.csv": ("2026-01-03", "2500.00"),
    "c.csv": ("2026-01-16", "2600.00"),
    "d.csv": ("2026-01-17", "2500.00"),
}


@pytest.mark.slow
def test_pairing_is_the_same_in_every_import_order(capsys):  # IA4, exhaustively for four files
    found = set()
    for order in itertools.permutations(sorted(FILES)):
        with tempfile.TemporaryDirectory() as folder:
            ledger = IncomeLedger(Path(folder), capsys)
            ledger.add_ok()
            for name in order:
                ledger.deposit(name, *FILES[name])
            found.add(tuple(ledger.outcomes()))
    assert found == {(
        (("a.csv",), "Pay", "received", "2026-01-02"),
        (("b.csv",), "Pay", "unscheduled", None),
        (("c.csv",), "Pay", "amount_changed", "2026-01-16"),
        (("d.csv",), "Pay", "unscheduled", None),
    )}


# IA5: proposals.

class TestProposals:  # IA5
    def proposals(self, ledger):
        code, out, err = ledger.run("income", "proposals")
        assert (code, err) == (0, ""), err
        return out

    def key(self, ledger):
        return re.search(r"Proposal ([0-9a-f]{16})", self.proposals(ledger))[1]

    def test_three_biweekly_paychecks_are_proposed_deterministically(self, paid):
        shown = self.proposals(paid)
        assert "description synthetic payroll, biweekly" in shown
        assert "Deposits: 3, from 2026-01-02 to 2026-01-30, actual amounts 2500.00 to 2500.00" \
            in shown
        assert ("Suggested: --cadence biweekly --anchor 2026-01-02 --amount 2500.00, expected "
                "next 2026-02-13") in shown
        assert self.proposals(paid) == shown
        paid.load_path(paid.folder / "p2.csv", layout="synthetic_checking_v1")
        assert self.proposals(paid) == shown

    def test_a_monthly_group_paid_a_day_early_anchors_on_its_pay_date(self, ledger):
        for name, day, amount in (("m1.csv", "2026-01-14", "1000.00"),
                                  ("m2.csv", "2026-02-15", "1050.00"),
                                  ("m3.csv", "2026-03-15", "1020.00")):
            ledger.deposit(name, day, amount)
        shown = self.proposals(ledger)
        # The median of 1000.00, 1050.00 and 1020.00.
        assert "--cadence monthly:15 --anchor 2026-01-15 --amount 1020.00" in shown

    def test_a_median_of_two_rounds_half_down(self, ledger):
        for name, day, amount in (("q1.csv", "2026-01-10", "100.01"),
                                  ("q2.csv", "2026-04-10", "100.02")):
            ledger.deposit(name, day, amount)
        assert "--cadence quarterly:10 --anchor 2026-01-10 --amount 100.01" in \
            self.proposals(ledger)

    @pytest.mark.parametrize("rows", [
        (("x1.csv", "2026-01-02", "2500.00"), ("x2.csv", "2026-01-16", "2500.00")),
        (("x1.csv", "2026-01-02", "2500.00"), ("x2.csv", "2026-01-16", "2500.00"),
         ("x3.csv", "2026-01-30", "2800.00")),
        (("x1.csv", "2026-01-02", "2500.00"), ("x2.csv", "2026-01-09", "2500.00"),
         ("x3.csv", "2026-01-25", "2500.00")),
    ])
    def test_groups_below_the_thresholds_are_not_proposed(self, ledger, rows):
        for name, day, amount in rows:
            ledger.deposit(name, day, amount)
        assert "Income proposals: 0" in self.proposals(ledger)

    def test_unclassified_deposits_are_never_proposed(self, ledger):
        for name, day in (("u1.csv", "2026-01-02"), ("u2.csv", "2026-01-16"),
                          ("u3.csv", "2026-01-30")):
            ledger.deposit(name, day, financial_type=None)
        assert "Income proposals: 0" in self.proposals(ledger)

    def test_a_group_a_source_reaches_is_withdrawn(self, paid):
        key = self.key(paid)
        paid.add_ok(from_proposal=key)
        assert "Income proposals: 0" in self.proposals(paid)

    def test_a_token_made_before_an_import_that_changes_the_group_refuses(self, paid):
        key = self.key(paid)
        revision = paid.preview_revision(from_proposal=key)
        paid.deposit("p4.csv", "2026-02-13")
        assert self.key(paid) == key
        before = (paid.income_tables(), paid.evidence())
        code, _, err = paid.add(revision=revision, from_proposal=key)
        assert (code, err.strip()) == (2, f"Error: {STALE_INCOME_PREVIEW}")
        assert (paid.income_tables(), paid.evidence()) == before
        paid.add_ok(from_proposal=key)

    def test_a_token_covers_the_proposal_even_where_the_reach_is_unchanged(self, paid):
        key = self.key(paid)
        revision = paid.preview_revision(from_proposal=key)
        # Two weeks before the anchor: the proposal now starts there, the source does not reach it.
        paid.deposit("p0.csv", "2025-12-19")
        assert self.key(paid) == key
        assert "from 2025-12-19 to 2026-01-30" in self.proposals(paid)
        assert "Before the first pay date, not reached: 1" in paid.preview_ok(from_proposal=key)
        before = (paid.income_tables(), paid.evidence())
        code, _, err = paid.add(revision=revision, from_proposal=key)
        assert (code, err.strip()) == (2, f"Error: {STALE_INCOME_PREVIEW}")
        assert (paid.income_tables(), paid.evidence()) == before

    def test_an_unknown_proposal_is_refused(self, paid):
        code, _, err = paid.preview(from_proposal="0" * 16)
        assert (code, err.strip()) == (2, f"Error: {PROPOSAL_NOT_FOUND}")


# IA6: refusals, each changing nothing, and G3's checks.

class TestRefusals:  # IA6
    def refused(self, ledger, message, revision="in1-0000000000000000", **options):
        before = (ledger.income_tables(), ledger.evidence())
        code, _, err = ledger.add(revision=revision, **options)
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (ledger.income_tables(), ledger.evidence()) == before

    @pytest.mark.parametrize(("options", "message"), [
        ({"name": " "}, NAME_BLANK),
        ({"match": "  "}, TEXT_BLANK),
        ({"cadence": "quarterly:2", "anchor": "2026-01-02"}, SALARY_CADENCE),
        ({"cadence": "annual:01-02"}, SALARY_CADENCE),
        ({"tolerance_days": 8}, TOLERANCE_DAYS_RANGE),
        ({"tolerance_days": -1}, TOLERANCE_DAYS_RANGE),
        ({"amount": "0.00"}, AMOUNT_INVALID),
        ({"amount": "-1.00"}, AMOUNT_INVALID),
        ({"amount": "1.001"}, AMOUNT_INVALID),
        ({"amount_tolerance": "-0.01"}, AMOUNT_TOLERANCE_INVALID),
        ({"cadence": "semimonthly:15,1"}, CADENCE_INVALID),
        ({"cadence": "monthly:32"}, CADENCE_INVALID),
        ({"cadence": "every:1-months:2", "kind": "side"}, CADENCE_INVALID),
        ({"cadence": "fortnightly"}, CADENCE_INVALID),
        ({"cadence": "monthly:15", "anchor": "2026-01-16"}, ANCHOR_OFF_CADENCE),
        ({"cadence": "annual:02-01", "anchor": "2026-03-01", "kind": "side"}, ANCHOR_OFF_CADENCE),
        ({"member": "Nobody"}, MEMBER_UNKNOWN),
        ({"cadence": None}, TERMS_REQUIRED),
        ({"amount": None}, TERMS_REQUIRED),
    ])
    def test_what_was_typed(self, paid, options, message):
        self.refused(paid, message, **options)

    def test_an_anchor_must_be_a_date(self, paid):
        self.refused(paid, "--anchor must be a date written YYYY-MM-DD. Nothing was changed.",
                     anchor="2026-02-30")

    def test_an_unknown_account(self, paid):
        code, _, err = paid.add(revision="in1-0000000000000000", account="Nowhere")
        assert (code, err.strip()) == (2, "Error: account not found: Nowhere")

    def test_a_repeated_name_and_the_same_matcher(self, paid):
        source = paid.add_ok()
        self.refused(paid, NAME_TAKEN.format(source=source), match="bonus")
        self.refused(paid, SAME_MATCHER.format(source=source), name="Again",
                     match="  Synthetic PAYROLL ")

    def test_a_stale_token(self, paid):
        revision = paid.preview_revision()
        paid.deposit("p4.csv", "2026-02-13")
        self.refused(paid, STALE_INCOME_PREVIEW, revision=revision)

    @pytest.mark.parametrize("change", [
        {"name": "Renamed"}, {"kind": "side"}, {"match": "payroll"}, {"amount": "2500.01"},
        {"tolerance_days": 2}, {"amount_tolerance": "1.00"}, {"tax_eligible": True},
        {"anchor": "2026-01-16"}, {"cadence": "weekly"},
    ])
    def test_a_token_covers_every_field_typed(self, paid, change):
        revision = paid.preview_revision()
        self.refused(paid, STALE_INCOME_PREVIEW, revision=revision, **change)

    def test_a_token_covers_a_correction_and_a_classification(self, paid):
        revision = paid.preview_revision()
        paid.correct_ok(holding(paid, "p3.csv"), "amount", "2400.00")
        self.refused(paid, STALE_INCOME_PREVIEW, revision=revision)
        revision = paid.preview_revision()
        transaction = holding(paid, "p2.csv")
        paid.classify_ok(transaction, "refund", supersedes=paid.classification_of(transaction))
        self.refused(paid, STALE_INCOME_PREVIEW, revision=revision)

    def test_a_stale_account_is_checked_first(self, paid):
        conn = paid.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        assert "adding it will be refused until it is" in paid.preview_ok()
        self.refused(paid, STALE_ACCOUNT, name=" ", amount="0")

    def test_a_race_between_preview_and_add_refuses(self, paid):
        revision = paid.preview_revision()
        # Another connection commits a paycheck the source would reach, between the two.
        paid.deposit("p4.csv", "2026-02-13")
        self.refused(paid, STALE_INCOME_PREVIEW, revision=revision)

    def test_a_fault_after_the_first_insert_leaves_nothing(self, paid, monkeypatch):
        revision = paid.preview_revision()
        conn = paid.conn()
        before = logical_digest(conn)
        conn.close()

        def fail(conn, chain_id, terms):
            raise RuntimeError("injected")

        monkeypatch.setattr(income_sources, "insert_terms", fail)
        code, _, err = paid.add(revision=revision)
        assert code == 2 and "unexpected" in err
        conn = paid.conn()
        assert logical_digest(conn) == before
        conn.close()


class TestTermsAndUndoRefusals:  # IA6
    def refused(self, ledger, attempt, message):
        before = (ledger.income_tables(), ledger.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (ledger.income_tables(), ledger.evidence()) == before

    def test_an_effective_date_in_a_closed_month(self, paid):
        source = paid.add_ok()
        self.refused(paid, lambda: paid.terms(source, "2026-02-27", "2600.00", as_of="2026-03-01"),
                     TERMS_CLOSED_MONTH)
        assert paid.terms(source, "2026-03-13", "2600.00", as_of="2026-03-01")[0] == 0

    def test_an_effective_date_not_after_the_latest_terms(self, paid):
        source = paid.add_ok()
        self.refused(paid, lambda: paid.terms(source, "2026-01-02", "2600.00"),
                     TERMS_NOT_LATER.format(latest="2026-01-02"))

    def test_a_cadence_needs_its_anchor(self, paid):
        source = paid.add_ok()
        self.refused(paid, lambda: paid.terms(source, "2026-03-01", "2600.00", cadence="weekly"),
                     TERMS_CADENCE_PAIR)
        self.refused(paid, lambda: paid.terms(source, "2026-03-01", "2600.00",
                                              cadence="quarterly:1", anchor="2026-04-01"),
                     SALARY_CADENCE)

    def test_a_stale_terms_or_undo_token(self, paid):
        source = paid.add_ok()
        terms, undo = paid.token(source, "Terms"), paid.token(source, "Undo")
        assert terms != undo
        self.refused(paid, lambda: paid.terms(source, "2026-03-01", "2600.00", revision=undo),
                     STALE_INCOME_REVISION)
        self.refused(paid, lambda: paid.undo(source, revision=terms), STALE_INCOME_REVISION)
        paid.deposit("p4.csv", "2026-02-13")
        self.refused(paid, lambda: paid.undo(source, revision=undo), STALE_INCOME_REVISION)

    def test_unknown_undone_and_superseded_sources(self, paid):
        source = paid.add_ok()
        newer = paid.add_ok(name="Pay 2", match="synthetic payroll", cadence=None, anchor=None,
                            amount=None, supersedes=source)
        self.refused(paid, lambda: paid.undo("nope", revision="in1-0000000000000000"),
                     SOURCE_NOT_FOUND)
        self.refused(paid, lambda: paid.undo(source, revision="in1-0000000000000000"),
                     SOURCE_SUPERSEDED.format(newest=newer))
        assert paid.undo(newer)[0] == 0
        self.refused(paid, lambda: paid.undo(newer, revision="in1-0000000000000000"),
                     SOURCE_NOT_ACTIVE)

    def test_supersede_takes_no_terms_and_keeps_its_account(self, paid):
        paid.add_account("B")
        source = paid.add_ok()
        for options, message in (({}, SUPERSEDE_TERMS_GIVEN),
                                 ({"cadence": None, "anchor": None, "amount": None,
                                   "account": "B"}, SUPERSEDE_ACCOUNT_DIFFERS)):
            before = (paid.income_tables(), paid.evidence())
            code, _, err = paid.preview(supersedes=source, **options)
            assert (code, err.strip()) == (2, f"Error: {message}")
            assert (paid.income_tables(), paid.evidence()) == before

    def test_no_income_write_changes_the_evidence(self, paid):
        before = paid.evidence()
        source = paid.add_ok()
        assert paid.terms(source, "2026-03-06", "2600.00")[0] == 0
        newer = paid.add_ok(name="Narrow", match="synthetic payroll", cadence=None, anchor=None,
                            amount=None, supersedes=source)
        assert paid.undo(newer)[0] == 0
        assert paid.undo(source)[0] == 0
        assert paid.evidence() == before


# IA7: dated terms and the chain.

class TestTermsAndChains:  # IA7
    def test_a_later_terms_row_changes_only_later_pay_dates(self, paid):
        source = paid.add_ok()
        before = paid.show(source, as_of="2026-03-31")
        assert paid.terms(source, "2026-01-20", "2600.00")[0] == 0
        after = paid.show(source, as_of="2026-03-31")
        assert "2026-01-16 (baseline): received, expected 2500.00" in after
        assert "2026-01-30 (extra): amount_changed, expected 2600.00" in after
        assert "2026-02-13 (baseline): missed, expected 2600.00" in after
        early = lambda text: [line for line in text.splitlines() if line.startswith("  2026-01-0")]
        assert early(after) == early(before)
        assert ("Terms from 2026-01-20: biweekly, anchor 2026-01-02, expected 2600.00"
                in after)

    def test_a_new_cadence_from_a_date(self, paid):
        source = paid.add_ok()
        assert paid.terms(source, "2026-02-01", "2500.00", cadence="semimonthly:1,15",
                          anchor="2026-02-01")[0] == 0
        shown = paid.show(source, as_of="2026-02-20")
        assert "2026-02-15 (baseline): missed" in shown
        assert "2026-02-13" not in shown.split("Pay dates as of")[1].split("Reaches:")[0]

    def test_superseding_narrows_the_matcher_and_undo_steps_back(self, paid):
        paid.deposit("bonus.csv", "2026-02-13", text="SYNTHETIC PAYROLL BONUS")
        source = paid.add_ok(match="payroll")
        assert paid.terms(source, "2026-03-06", "2600.00")[0] == 0
        wide = paid.outcomes()
        assert (("bonus.csv",), "Pay", "received", "2026-02-13") in wide
        newer = paid.add_ok(name="Pay", match="synthetic payroll 0", cadence=None, anchor=None,
                            amount=None, supersedes=source)
        assert paid.outcomes() == []
        newest = paid.add_ok(name="Pay", match="synthetic payroll", cadence=None, anchor=None,
                             amount=None, supersedes=newer)
        assert (("bonus.csv",), "Pay", "received", "2026-02-13") in paid.outcomes()
        shown = paid.show(newest)
        assert "Terms from 2026-03-06: biweekly, anchor 2026-01-02, expected 2600.00" in shown
        assert f"Superseded by {newer}" in paid.show(source)
        assert paid.undo(newest)[0] == 0
        assert paid.outcomes() == []
        assert paid.undo(newer)[0] == 0
        assert paid.outcomes() == wide
        assert paid.undo(source)[0] == 0
        assert paid.outcomes() == []
        listed = paid.run("income", "sources")[1]
        assert listed.count(": undone, ") == 3


class TestListAndShow:
    def test_names_and_text_are_escaped(self, paid):
        source = paid.add_ok(name="Pay\x1b[2J", match="synthetic\npayroll")
        for words in (("income", "sources"), ("income", "source", "show", source, "--as-of",
                                              "2026-02-01")):
            out = paid.run(*words)[1]
            assert "\x1b" not in out and "synthetic\npayroll" not in out

    def test_sources_lists_what_each_reaches(self, paid):
        paid.add_ok(member=None)
        listed = paid.run("income", "sources")[1]
        assert "Reaches: received 3" in listed
        assert "Income sources: 1" in listed

    def test_a_member_and_the_tax_flag_are_stated(self, paid):
        assert paid.run("household", "member", "add", "Michael")[0] == 0
        source = paid.add_ok(member="Michael", tax_eligible=True)
        assert "paid to Michael, tax eligible" in paid.show(source)
