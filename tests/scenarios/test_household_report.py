"""pf report household and its UI page, using synthetic data only (HC1 to HC4, D-065)."""

import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from local_ui_client import UiClient, page_text, parsed_page
from test_allocations import AllocationLedger, single
from test_local_ui import account_ids, cli_output
from test_spending_by_category import generated, rows
from test_category_rules import RuleLedger
from test_supersession import holding
from test_transfers import IN_ROW, OUT_ROW, TransferLedger, rows_of

from personal_finance.reconcile.household_effects import load_household
from personal_finance.reports.household import (
    HOUSEHOLD_COLUMN,
    household_report,
)
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.totals import GroupTotal, combined, income_and_spending

REFUND = "01/11/2026,SYNTHETIC CAFE,,6.51"
ODD = "01/10/2026,SYNTHETIC CAFE,6.51,"
MONTH_RANGES = [(None, None), ("2026-01", "2026-01"), ("2026-02", None)]


def groups_of(groups):
    """Every group a column holds, as comparable totals, by name."""
    found = {
        "income": groups.income, "spending": groups.spending,
        "confirmed": groups.confirmed_transfers,
        "unconfirmed": groups.unconfirmed_transfer_kinds, "unclassified": groups.unclassified,
    }
    found.update({f"type {kind}": total for kind, total in groups.spending_by_type})
    found.update({f"category {category}": total
                  for category, total in groups.spending_by_category})
    return found


def amounts(total):
    return (total.out_cents, total.in_cents)


def assert_members_add_to(columns, whole):
    """Every group's out and in, summed over the columns, equals the whole's exactly."""
    whole_groups = groups_of(whole.groups)
    for name in set().union(*(groups_of(column.groups) for column in columns)) | set(whole_groups):
        parts = [groups_of(column.groups).get(name, GroupTotal()) for column in columns]
        assert amounts(combined(parts)) == amounts(whole_groups.get(name, GroupTotal())), name


def with_household(ledger, choices):
    """Members, a 50/50 share, account defaults, and allocations as choices pick them."""
    ledger.__class__ = AllocationLedger
    ledger.add_member_ok("Michael", "M")
    ledger.set_share_ok("Michael=50", "M=50")
    defaults, ways = choices
    for account, member in zip(("A", "B"), defaults, strict=True):
        if member != "none":
            ledger.set_default_ok(account, None if member == "shared" else member)
    options = (None, ("--member", "M"), ("--shared",), ("--percent", "Michael=33.33", "--percent",
                                                         "M=66.67"))
    for account in ("A", "B"):
        if not (ledger.folder / f"{account}.csv").exists():
            continue
        for transaction, way in zip(rows_of(ledger, f"{account}.csv"), ways):
            if options[way]:
                ledger.allocate_ok(transaction, *options[way], account=account)
    return ledger


household_choices = st.tuples(
    st.tuples(*[st.sampled_from(["Michael", "M", "shared", "none"])] * 2),
    st.lists(st.integers(0, 3), max_size=8),
)


@settings(max_examples=15, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows, choices=household_choices)
def test_members_and_unattributed_add_to_the_household_which_equals_totals(  # HC1
        capsys, generated_rows, choices):
    with tempfile.TemporaryDirectory() as folder:
        ledger = with_household(generated(Path(folder), capsys, generated_rows), choices)
        conn = ledger.conn()
        for account in (None, ledger.account_id("A"), ledger.account_id("B")):
            for first, last in MONTH_RANGES:
                report = household_report(conn, account, first, last)
                *members, unattributed, household = report.columns
                assert household.heading == HOUSEHOLD_COLUMN
                assert_members_add_to([*members, unattributed], household)
                months = [month.income_and_spending
                          for month in monthly_report(conn, account, first, last).months]
                expected = income_and_spending(conn, account) if first is last is None else None
                for name, total in groups_of(household.groups).items():
                    if expected is not None:
                        assert total == groups_of(expected).get(name, GroupTotal()), name
                    assert total == combined(groups_of(month).get(name, GroupTotal())
                                             for month in months), name
                # One member's view and the shared view add up the same way.
                for member in load_household(conn).members:
                    *kinds, whole = household_report(conn, account, first, last,
                                                     member_id=member.member_id).columns
                    assert_members_add_to(kinds, whole)
                *shared_members, whole = household_report(conn, account, first, last,
                                                          shared_only=True).columns
                assert_members_add_to(shared_members, whole)
        conn.close()


class FullLedger(AllocationLedger, RuleLedger, TransferLedger):
    """Household, allocations, category rules and transfer matches on one ledger."""


def test_every_input_of_totals_reaches_the_household_column(tmp_path, capsys):  # HC1
    ledger = FullLedger(tmp_path, capsys)
    ledger.add_member_ok("Michael", "M")
    ledger.set_share_ok("Michael=50", "M=50")
    ledger.add_account("S", "savings")
    # Dated in January and posted in February, corrected across months, and income.
    ledger.checking("c.csv", "C-1,2026-01-31,2026-02-02,SYNTHETIC GROCER,-9.00,POSTED",
                    "C-2,2026-01-15,2026-01-16,SYNTHETIC SHOP,-4.00,POSTED",
                    "C-3,2026-01-20,2026-01-20,SYNTHETIC PAY,100.00,POSTED")
    grocer, shop, pay = rows_of(ledger, "c.csv")
    ledger.classify_ok(grocer, "purchase")
    ledger.classify_ok(shop, "purchase")
    ledger.classify_ok(pay, "income")
    ledger.correct_ok(shop, "transaction_date", "2026-02-20")
    ledger.add_rule_ok("Food", "grocer")
    ledger.card("out.csv", OUT_ROW)
    ledger.card("in.csv", IN_ROW, account="S")
    outflow = holding(ledger, "out.csv")
    ledger.classify_ok(outflow, "transfer")
    ledger.match_ok(outflow, holding(ledger, "in.csv"))
    ledger.set_default_ok()
    ledger.set_default_ok("S", "Michael")
    ledger.allocate_ok(pay, "--amount", "Michael=70", "--amount", "M=30")
    conn = ledger.conn()
    for account in (None, ledger.account_id("A"), ledger.account_id("S")):
        for first, last in MONTH_RANGES:
            *_, household = household_report(conn, account, first, last).columns
            months = [month.income_and_spending
                      for month in monthly_report(conn, account, first, last).months]
            expected = groups_of(income_and_spending(conn, account))
            for name, total in groups_of(household.groups).items():
                if first is last is None:
                    assert total == expected.get(name, GroupTotal()), (account, name)
                assert total == combined(groups_of(month).get(name, GroupTotal())
                                         for month in months), (account, first, name)
    conn.close()
    # January holds the grocer by its transaction date and February the shop by its correction.
    _, rows = table(ledger.run("report", "household", "--from", "2026-02")[1])
    assert rows["Spending, out"] == ["2.00", "2.00", "0.00", "4.00"]
    _, rows = table(ledger.run("report", "household", "--to", "2026-01")[1])
    assert rows["Spending, out"] == ["4.50", "4.50", "0.00", "9.00"]
    assert rows["Food, out"] == ["4.50", "4.50", "0.00", "9.00"]
    _, rows = table(ledger.run("report", "household")[1])
    assert rows["Income, in"] == ["70.00", "30.00", "0.00", "100.00"]
    assert rows["Income, out"] == ["0.00", "0.00", "0.00", "0.00"]
    assert rows["Confirmed transfers, out"] == ["25.00", "25.00", "0.00", "50.00"]
    assert rows["Confirmed transfers, in"] == ["50.00", "0.00", "0.00", "50.00"]


@pytest.fixture
def ledger(tmp_path, capsys):
    found = AllocationLedger(tmp_path, capsys)
    found.add_member_ok("Michael", "M")
    found.set_share_ok("Michael=50", "M=50")
    return found


def table(out):
    """The report's rows as label and cells."""
    lines = out.split("Disclosures:\n")[0].splitlines()[2:]
    header = lines[0].split()
    return header, {re.split(r"\s{2,}", line.strip())[0]: line.split()[-len(header):]
                    for line in lines[1:]}


class TestViews:  # HC1, HC2
    def test_side_by_side_divides_the_odd_cent_and_nets_a_full_refund_to_zero(self, ledger):
        for name, row in (("a.csv", ODD), ("b.csv", REFUND)):
            transaction = single(ledger, row, name)
            ledger.classify_ok(transaction, "purchase" if row == ODD else "refund")
            ledger.categorize_ok(transaction, "Food")
        ledger.set_default_ok()
        code, out, err = ledger.run("report", "household")
        assert (code, err) == (0, "")
        header, rows = table(out)
        assert header == ["Michael", "M", "unattributed", "household"]
        assert rows["Spending, out"] == ["3.26", "3.25", "0.00", "6.51"]
        assert rows["Spending, in"] == ["3.26", "3.25", "0.00", "6.51"]
        assert rows["Net account movement"] == ["0.00", "0.00", "0.00", "0.00"]
        assert rows["Food, out"] == rows["Spending, out"]
        assert rows["Transactions"] == ["2", "2", "0", "2"]

    def test_one_member_counts_personal_shared_and_allocated_apart(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.set_default_ok("B", "M")
        ledger.card("p.csv", "01/05/2026,SYNTHETIC SHOP,10.00,", account="B")
        shared = single(ledger, "01/06/2026,SYNTHETIC SHOP,20.00,", "s.csv")
        allocated = single(ledger, "01/07/2026,SYNTHETIC SHOP,30.00,", "t.csv")
        ledger.allocate_ok(shared, "--shared")
        ledger.allocate_ok(allocated, "--amount", "Michael=12", "--amount", "M=18")
        header, rows = table(ledger.run("report", "household", "--member", "M")[1])
        assert header == ["personal", "shared", "allocated", "M"]
        assert rows["Unclassified, out"] == ["10.00", "10.00", "18.00", "38.00"]
        header, rows = table(ledger.run("report", "household", "--shared")[1])
        assert header == ["Michael", "M", "whole"]
        assert rows["Unclassified, out"] == ["22.00", "28.00", "50.00"]
        assert rows["Transactions"] == ["2", "2", "2"]

    def test_scope_and_months(self, ledger):
        ledger.set_default_ok(member="Michael")
        single(ledger, "01/10/2026,SYNTHETIC CAFE,1.00,", "a.csv")
        single(ledger, "02/10/2026,SYNTHETIC CAFE,2.00,", "b.csv")
        out = ledger.run("report", "household", "--account", "A", "--from", "2026-02")[1]
        assert out.startswith("Household report: account A, 2026-02 to the last month\n")
        assert table(out)[1]["Unclassified, out"] == ["2.00", "0.00", "0.00", "2.00"]
        assert "- Transactions dated outside these months, not counted: 1\n" in out

    @pytest.mark.parametrize(("words", "message"), [
        (("--member", "Nobody"), "household member not found"),
        (("--from", "2026-13"), "--from must be a month"),
        (("--from", "2026-02", "--to", "2026-01"), "--from is after --to"),
    ])
    def test_refusals(self, ledger, words, message):
        code, _, err = ledger.run("report", "household", *words)
        assert code == 2 and message in err


class TestDisclosures:  # HC3
    def test_unattributed_by_reason_and_what_is_in_effect(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.card("b.csv", "01/05/2026,SYNTHETIC SHOP,10.00,", account="B")
        ledger.set_default_ok("A")
        single(ledger, "01/06/2026,SYNTHETIC SHOP,20.00,", "s.csv")
        transaction = single(ledger, "01/07/2026,SYNTHETIC SHOP,30.00,", "t.csv")
        ledger.allocate_ok(transaction, "--amount", "M=30")
        ledger.correct_ok(transaction, "amount", "-31.00")
        out = ledger.run("report", "household")[1].split("Disclosures:\n")[1]
        assert ("- Unattributed, an allocation by amount no longer sums to its amount: 1 "
                "transactions, 31.00 out and 0.00 in\n") in out
        assert ("- Unattributed, its account has no default: 1 transactions, 10.00 out and 0.00 "
                "in\n") in out
        assert "- Household share: Michael 50.00%, M 50.00%\n" in out
        assert "- Account defaults: A shared, B none\n" in out
        assert ledger.undo_share()[0] == 0
        out = ledger.run("report", "household")[1]
        assert "- Unattributed, attributed shared while no household share is active: 1 " in out

    def test_names_are_escaped(self, ledger):
        ledger.add_member_ok("Odd\x1b[2J\nname")
        single(ledger)
        ledger.set_default_ok(member="Odd\x1b[2J\nname")
        out = ledger.run("report", "household")[1]
        assert "Odd\\x1b[2J\\nname" in out and "\x1b" not in out


def report_words():
    return [("totals",), ("report", "monthly"), ("totals", "--account", "B"),
            ("report", "monthly", "--account", "A", "--from", "2026-02")]


@settings(max_examples=10, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows, choices=household_choices)
def test_totals_and_monthly_are_byte_for_byte_unchanged(capsys, generated_rows, choices):  # HC3
    with tempfile.TemporaryDirectory() as folder:
        ledger = generated(Path(folder), capsys, generated_rows)
        before = [ledger.run(*words) for words in report_words()]
        with_household(ledger, choices)
        assert [ledger.run(*words) for words in report_words()] == before


def household_views(ledger):
    members = [str(member.member_id) for member in load_household(ledger.conn()).members]
    return [("", ()), ("view=shared", ("--shared",)),
            *((f"member={member_id}", ("--member", name))
              for member_id, name in zip(members, member_names(ledger), strict=True))]


def member_names(ledger):
    conn = ledger.conn()
    found = [row[0] for row in conn.execute("SELECT name FROM household_member ORDER BY id")]
    conn.close()
    return found


def assert_household_pages_equal_the_cli(ledger):
    client = UiClient(ledger.path)
    client.sign_in()
    try:
        for account_id in (None, *account_ids(ledger.path)):
            for first, last in MONTH_RANGES:
                for view_query, view_words in household_views(ledger):
                    query = "&".join(part for part in (
                        account_id and f"account={account_id}", first and f"from={first}",
                        last and f"to={last}", view_query) if part)
                    words = [*(["--account", account_id] if account_id else []),
                             *(["--from", first] if first else []),
                             *(["--to", last] if last else []), *view_words]
                    assert page_text(client.get(f"/household?{query}").body) == cli_output(
                        ledger.capsys, "report", "household", "--db", ledger.db, *words), query
    finally:
        client.close()


@settings(max_examples=5, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows, choices=household_choices)
def test_pages_equal_the_cli_in_every_view(capsys, generated_rows, choices):  # HC4
    with tempfile.TemporaryDirectory() as folder:
        assert_household_pages_equal_the_cli(
            with_household(generated(Path(folder), capsys, generated_rows), choices))


class TestPage:  # HC4
    def test_a_name_holding_html_is_shown_as_text(self, ledger):
        odd = '<b>M&amp;"q\'</b><script>x</script>'
        ledger.add_member_ok(odd)
        single(ledger)
        ledger.set_default_ok(member=odd)
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            for target in ("/household", "/household?member=3"):
                page = parsed_page(client.get(target).body)
                assert not {"b", "script"} & set(page.tags), target
                assert any(odd in line for line in page.report_lines), target
        finally:
            client.close()
        assert_household_pages_equal_the_cli(ledger)

    @pytest.mark.parametrize("query", ["member=99", "member=x", "view=member",
                                       "member=1&view=shared", "member=1&member=2"])
    def test_a_value_it_does_not_take_is_refused(self, ledger, query):
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            assert client.get(f"/household?{query}").status == 400
        finally:
            client.close()
