"""Migration 0034, scenarios, their inputs and promotions, on a populated ledger (XA1, D-067 G10,
D-074), using synthetic data only. Its tables are empty, nothing else shown changes, a ledger at
33 is refused until migrate, a failure leaves everything as it was, and its tables are
append-only, each check refusing on its own with a control that succeeds."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_it_adds_empty_tables_and_changes_nothing_shown,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
)
from test_decisions import CAFE, SCENARIO_TABLES, TAG_TABLES, drop_scenario_tables
from test_funds import FundLedger
from test_tag_migration import VERSION_32_TABLES

from personal_finance.db.migrate import connect

VERSION_33_TABLES = (*VERSION_32_TABLES, *TAG_TABLES)


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("transactions",), ("review", "list"),
        ("funds", "--as-of", "2026-03-15"), ("report", "net-worth", "--as-of", "2026-03-15"))]


@pytest.fixture
def populated(tmp_path, capsys):
    """A purchase, a possible duplicate and a goal, set back to 33, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE)
    ledger.add_fund_ok(name="House", monthly="100.00", as_of="2026-03-15")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_scenario_tables(conn)
    conn.execute("PRAGMA user_version = 33")
    conn.close()
    return ledger


class TestMigration:  # XA1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        assert_it_adds_empty_tables_and_changes_nothing_shown(
            populated, tmp_path, version=34, tables_before=VERSION_33_TABLES,
            new_tables=SCENARIO_TABLES, shown_now=shown_now)

    def test_a_ledger_at_33_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "scenarios")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=34, migration_name="0034_scenarios.sql",
            tables_before=VERSION_33_TABLES, new_tables=SCENARIO_TABLES)


INPUT = ("INSERT INTO scenario_input (id, scenario_id, kind, amount_cents, from_date, to_date, "
         "cadence, anchor, replaces_kind, replaces_id, uncertain, gross, take_home_basis_points, "
         "down_payment_cents, closing_costs_cents, ownership_costs_cents, loan_rate_millionths, "
         "loan_months, loan_terms_id, account_id, match_text) VALUES (:id, 'sc', :kind, :amount, "
         ":from_date, :to_date, :cadence, :anchor, :replaces_kind, :replaces_id, :uncertain, "
         ":gross, :take_home, :down, :closing, :ownership, :rate, :months, :loan_terms_id, "
         ":account_id, :match_text)")
PURCHASE = {"kind": "purchase", "amount": 100, "from_date": "2026-06-01",
            "to_date": None, "cadence": "once", "anchor": None, "replaces_kind": None,
            "replaces_id": None, "uncertain": 0, "gross": 0, "take_home": None, "down": None,
            "closing": None, "ownership": None, "rate": None, "months": None,
            "loan_terms_id": None, "account_id": None, "match_text": None}
INCOME = {**PURCHASE, "kind": "income", "cadence": "monthly:1"}
HOME = {**PURCHASE, "kind": "home_purchase", "amount": 30000000, "down": 6000000,
        "closing": 600000, "ownership": 40000, "rate": 6000000, "months": 360}


@pytest.fixture
def stated(tmp_path, capsys):
    """One scenario with a purchase, its events, and a promotion with one entry."""
    ledger = FundLedger(tmp_path, capsys)
    conn = ledger.conn()
    conn.execute("INSERT INTO scenario (id, name, include_uncertain) VALUES ('sc', 'Move', 0)")
    conn.execute("INSERT INTO scenario_event (scenario_id, event) VALUES ('sc', 'made')")
    conn.execute(INPUT, {**PURCHASE, "id": "i"})
    conn.execute("INSERT INTO scenario_input_event (input_id, event) VALUES ('i', 'made')")
    conn.execute("INSERT INTO scenario_promotion (id, scenario_id) VALUES ('p', 'sc')")
    conn.execute("INSERT INTO scenario_promotion_event (promotion_id, event) VALUES ('p', 'made')")
    conn.execute("INSERT INTO scenario_promotion_entry (promotion_id, input_id, entry_kind, "
                 "entry_id) VALUES ('p', 'i', 'fund', 'f')")
    conn.close()
    return ledger


def insert_input(ledger, **changes):
    """An input as PURCHASE with changes, as ID x unless one is given."""
    conn = ledger.conn()
    try:
        conn.execute(INPUT, {**PURCHASE, "id": "x", **changes})
    finally:
        conn.close()


class TestAppendOnly:  # XA1, G2
    @pytest.mark.parametrize("table", SCENARIO_TABLES)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, SCENARIO_TABLES)

    def test_control_inserts_succeed(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO scenario_event (scenario_id, event) VALUES ('sc', 'undone')")
        conn.execute("INSERT INTO scenario_input_event (input_id, event) VALUES ('i', 'undone')")
        conn.execute("INSERT INTO scenario_promotion_event (promotion_id, event) "
                     "VALUES ('p', 'undone')")
        conn.execute("INSERT INTO scenario_promotion_entry (promotion_id, input_id, entry_kind, "
                     "terms_row_id) VALUES ('p', 'i', 'fund_terms', 7)")
        conn.close()
        for index, changes in enumerate((
                INCOME, {**INCOME, "to_date": "2026-06-01"}, HOME,
                {**PURCHASE, "kind": "bonus", "gross": 1, "take_home": 100},
                {**INCOME, "gross": 1, "take_home": 10000},
                {**INCOME, "replaces_kind": "income_source", "replaces_id": "s"},
                {**INCOME, "account_id": None, "match_text": None},
                {**PURCHASE, "kind": "borrowing", "rate": 0, "months": 1},
                {**PURCHASE, "kind": "annual_expense", "cadence": "annual:09-01"},
                {**PURCHASE, "amount": 0})):
            insert_input(stated, **{**changes, "id": f"ok{index}"})


REFUSED = [
    {"kind": "rent"},
    {"amount": -1},
    {"from_date": "2026-02-30"},
    {**INCOME, "to_date": "2026-05-31"},
    {"cadence": ""},
    {"cadence": "monthly:1"},
    {**INCOME, "cadence": "once"},
    {**PURCHASE, "kind": "annual_expense", "cadence": "monthly:1"},
    {"to_date": "2026-07-01"},
    {**INCOME, "anchor": "2026-02-30"},
    {"anchor": "2026-06-01"},
    {**INCOME, "replaces_kind": "income_source"},
    {**INCOME, "replaces_id": "s"},
    {**INCOME, "replaces_kind": "fund", "replaces_id": "f"},
    {"replaces_kind": "fund", "replaces_id": "f"},
    {**PURCHASE, "kind": "expense", "cadence": "monthly:1", "replaces_kind": "income_source",
     "replaces_id": "s"},
    {**INCOME, "gross": 1},
    {**INCOME, "take_home": 5000},
    {**INCOME, "gross": 1, "take_home": 99},
    {**INCOME, "gross": 1, "take_home": 10001},
    {"gross": 1, "take_home": 5000},
    {**HOME, "down": None},
    {**HOME, "closing": None},
    {**HOME, "ownership": None},
    {**HOME, "down": 30000001},
    {"down": 0},
    {**HOME, "rate": None},
    {**HOME, "months": 0},
    {**HOME, "months": 601},
    {**HOME, "rate": 100000001},
    {"rate": 5000000, "months": 12},
    {"kind": "loan_payoff"},
    {"uncertain": 2},
    {**INCOME, "match_text": "x"},
    {**INCOME, "match_text": " "},
]


class TestChecks:  # XA1, each refusing on its own
    @pytest.mark.parametrize("changes", REFUSED)
    def test_each_check_refuses_alone(self, stated, changes):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            insert_input(stated, **changes)

    def test_an_account_is_for_an_additional_income_or_expense(self, stated):
        conn = stated.conn()
        (account,) = conn.execute("SELECT id FROM account").fetchone()
        conn.close()
        insert_input(stated, **{**INCOME, "account_id": account, "match_text": "x"})
        for changes in ({**PURCHASE, "account_id": account, "match_text": "x"},
                        {**INCOME, "account_id": account, "match_text": "x",
                         "replaces_kind": "income_source", "replaces_id": "s"}):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                insert_input(stated, **{**changes, "id": "y"})

    def test_a_scenario_name_is_trimmed_and_the_flag_a_bit(self, stated):
        conn = stated.conn()
        for name, flag in ((" Move", 0), ("", 0), ("Move", 2)):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO scenario (id, name, include_uncertain) "
                             "VALUES ('x', ?, ?)", (name, flag))
        conn.execute("INSERT INTO scenario (id, name, include_uncertain) VALUES ('x', 'Move', 1)")
        conn.close()

    @pytest.mark.parametrize("kind, entry_id, terms_row_id", [
        ("fund", None, 7), ("fund_terms", "f", None), ("fund", None, None),
        ("fund_terms", "f", 7), ("loan_terms", "f", None)])
    def test_a_promotion_entry_names_an_entry_or_a_terms_row(self, stated, kind, entry_id,
                                                              terms_row_id):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO scenario_promotion_entry (promotion_id, input_id, "
                         "entry_kind, entry_id, terms_row_id) VALUES ('p', 'i', ?, ?, ?)",
                         (kind, entry_id, terms_row_id))
        conn.close()

    def test_an_event_it_does_not_take_is_refused(self, stated):
        conn = stated.conn()
        for table, column, key in (("scenario_event", "scenario_id", "sc"),
                                   ("scenario_input_event", "input_id", "i"),
                                   ("scenario_promotion_event", "promotion_id", "p")):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"INSERT INTO {table} ({column}, event) VALUES (?, 'paused')",
                             (key,))
        conn.close()
