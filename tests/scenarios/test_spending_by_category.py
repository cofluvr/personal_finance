"""Spending by category in totals, report monthly and the UI's pages, using synthetic data only
(CC1 to CC5, D-063)."""

import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_categorizations import CategoryLedger, purchase
from test_classifications import single
from test_local_ui import UiClient, account_ids, assert_pages_equal_the_cli, parsed_page
from test_separations import merged_two
from test_supersession import holding
from test_transfers import rows_of

from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.totals import IncomeAndSpendingTally, combined, income_and_spending

REFUND = "01/12/2026,SYNTHETIC CAFE,,4.00"


@pytest.fixture
def ledger(tmp_path, capsys):
    found = CategoryLedger(tmp_path, capsys)
    assert found.run("category", "add", "Groceries", "--parent", "Food")[0] == 0
    return found


def by_category(ledger, account=None):
    """The 'By category' lines of totals, as indent, name, count and amount."""
    totals = ledger.totals()
    if "    By category:\n" not in totals:
        return None
    section = totals.split("    By category:\n")[1].split("  Confirmed transfers:")[0]
    return re.findall(r"^( {6,8})(.+): (\d+) transactions, (\S+)$", section, re.MULTILINE)


def spending_line(ledger):
    return re.search(r"^  Spending: (\d+) transactions, (\S+)$", ledger.totals(), re.MULTILINE)


def row(day, cents, money_in=False, name="SYNTHETIC SHOP"):
    money = f"{cents // 100}.{cents % 100:02d}"
    return f"01/{day:02d}/2026,{name},{',' + money if money_in else money + ','}"


class TestTotals:  # CC1, CC2
    def test_a_ledger_never_categorized_shows_nothing_new(self, ledger):
        purchase(ledger)
        assert by_category(ledger) is None
        assert "categoriz" not in ledger.totals()
        assert "categoriz" not in ledger.run("report", "monthly")[1]

    def test_each_category_and_uncategorized_add_to_spending(self, ledger):
        ledger.card("a.csv", row(5, 1000), row(6, 250), row(7, 300), row(8, 99))
        first, second, third, fourth = rows_of(ledger, "a.csv")
        ledger.spend(first, "Travel")
        ledger.spend(second, "Food")
        ledger.spend(third, "Travel", financial_type="fee")
        ledger.classify_ok(fourth, "purchase")
        assert spending_line(ledger).groups() == ("4", "16.49")
        assert by_category(ledger) == [("      ", "Food", "1", "2.50"),
                                       ("      ", "Travel", "2", "13.00"),
                                       ("      ", "uncategorized", "1", "0.99")]

    def test_a_subcategory_is_under_its_parent_and_in_its_line(self, ledger):
        ledger.card("a.csv", row(5, 1000), row(6, 250), row(7, 300))
        first, second, third = rows_of(ledger, "a.csv")
        ledger.spend(first, "Groceries")
        ledger.spend(second, "Food")
        ledger.spend(third, "Groceries")
        assert by_category(ledger) == [("      ", "Food", "3", "15.50"),
                                       ("        ", "Groceries", "2", "13.00"),
                                       ("      ", "uncategorized", "0", "0.00")]

    def test_a_parent_shows_with_only_its_subcategory_spent(self, ledger):
        ledger.spend(single(ledger), "Groceries")
        assert by_category(ledger) == [("      ", "Food", "1", "6.50"),
                                       ("        ", "Groceries", "1", "6.50"),
                                       ("      ", "uncategorized", "0", "0.00")]

    def test_a_refund_reduces_its_category(self, ledger):
        ledger.card("a.csv", row(5, 1000), row(6, 400, money_in=True))
        bought, refunded = rows_of(ledger, "a.csv")
        ledger.spend(bought, "Food")
        ledger.spend(refunded, "Food", financial_type="refund")
        assert by_category(ledger)[0] == ("      ", "Food", "2", "6.00")
        assert spending_line(ledger).groups() == ("2", "6.00")

    def test_a_categorization_that_does_not_apply_counts_nowhere_in_categories(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        ledger.categorize_ok(transaction, "Food")
        ledger.card("b.csv", row(20, 300))
        ledger.classify_ok(holding(ledger, "b.csv"), "purchase")
        ledger.classify_ok(transaction, "transfer", supersedes=classification)
        assert by_category(ledger) == [("      ", "uncategorized", "1", "3.00")]

    def test_one_account_counts_its_own(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.spend(single(ledger), "Food")
        ledger.card("b.csv", row(9, 900), account="B")
        transaction = holding(ledger, "b.csv")
        ledger.classify_ok(transaction, "purchase", account="B")
        ledger.categorize_ok(transaction, "Travel", account="B")
        totals = ledger.run("totals", "--account", "B")[1]
        section = totals.split("    By category:\n")[1].split("  Confirmed transfers:")[0]
        assert section == "      Travel: 1 transactions, 9.00\n      uncategorized: 0 transactions, 0.00\n"


    def test_names_are_escaped(self, ledger):
        assert ledger.run("category", "add", "Odd\x1b[2J\nname")[0] == 0
        ledger.spend(single(ledger), "Odd\x1b[2J\nname")
        for out in (ledger.totals(), ledger.run("report", "monthly")[1]):
            assert "      Odd\\x1b[2J\\nname: 1 transactions, 6.50\n" in out
            assert "\x1b" not in out

    @pytest.mark.parametrize(("financial_type", "confirmed"), [
        ("income", False), ("transfer", False), (None, False), ("transfer", True), ("purchase", True)])
    def test_a_category_outside_spending_stops_the_report(self, financial_type, confirmed):
        with pytest.raises(AssertionError, match="outside spending"):
            IncomeAndSpendingTally().add(-100, financial_type, confirmed, 1)
        IncomeAndSpendingTally().add(-100, "purchase", False, 1)


class TestDisclosures:  # CC3
    def test_uncategorized_spending_is_disclosed_with_its_amount(self, ledger):
        ledger.card("a.csv", row(5, 1000), row(6, 250))
        first, second = rows_of(ledger, "a.csv")
        ledger.spend(first, "Food")
        ledger.classify_ok(second, "purchase")
        assert ("- Spending not categorized: 1 transactions, 2.50. It counts in Spending, as "
                "uncategorized. Run review categorize on each.\n") in ledger.totals()

    def test_none_once_every_spending_transaction_is_categorized(self, ledger):
        ledger.spend(single(ledger), "Food")
        assert "Spending not categorized" not in ledger.totals()

    def test_each_reason_a_categorization_does_not_apply(self, ledger):
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        ledger.spend(holding(ledger, "a.csv"), "Food")
        ledger.spend(holding(ledger, "b.csv"), "Travel")
        assert ledger.undo(separation)[0] == 0
        ledger.card("c.csv", row(25, 300))
        moved = holding(ledger, "c.csv")
        classification = ledger.classify_ok(moved, "purchase")
        ledger.categorize_ok(moved, "Food")
        ledger.classify_ok(moved, "transfer", supersedes=classification)
        totals = ledger.totals()
        assert ("- Transactions left uncategorized because categorizations disagree: 1. Run "
                "review categorizations.\n") in totals
        assert ("- Transactions left uncategorized because their transaction is no longer "
                "spending: 1. Run review categorizations.\n") in totals
        assert "binds records now in several transactions: " not in totals.split(
            "uncategorized because categorizations disagree")[1]
        monthly = ledger.run("report", "monthly")[1]
        assert "  With an unsettled categorization: 2 transactions\n" in monthly

    def test_one_account_discloses_its_own(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.card("b.csv", row(9, 900), account="B")
        other = holding(ledger, "b.csv")
        ledger.classify_ok(other, "purchase", account="B")
        ledger.categorize_ok(other, "Food", account="B")
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        ledger.categorize_ok(transaction, "Food")
        ledger.classify_ok(transaction, "transfer", supersedes=classification)
        assert "no longer spending: 1" in ledger.run("totals", "--account", "A")[1]
        assert "no longer spending" not in ledger.run("totals", "--account", "B")[1]

    def test_a_split_is_disclosed(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (transaction,) = ledger.merges()
        ledger.spend(transaction)
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        assert ("- Transactions left uncategorized because a categorization binds records now in "
                "several transactions: 2. Run review categorizations.\n") in ledger.totals()


class TestMonthly:  # CC1
    def test_each_month_lists_its_own(self, ledger):
        ledger.card("a.csv", row(5, 1000), "02/03/2026,SYNTHETIC SHOP,2.50,")
        january, february = rows_of(ledger, "a.csv")
        ledger.spend(january, "Food")
        ledger.classify_ok(february, "purchase")
        monthly = ledger.run("report", "monthly")[1]
        first, second = monthly.split("2026-02:")
        assert "    By category:\n      Food: 1 transactions, 10.00\n      uncategorized: 0 " \
               "transactions, 0.00\n" in first
        assert "    By category:\n      uncategorized: 1 transactions, 2.50\n" in second


IN_TYPES = (None, "refund", "income", "transfer")
OUT_TYPES = (None, "purchase", "fee", "interest", "transfer")
CATEGORIES = (None, "Food", "Groceries", "Travel", "Other")

rows = st.lists(
    st.tuples(st.integers(1, 9999), st.booleans(), st.integers(0, 4), st.integers(0, 4),
              st.integers(1, 59), st.booleans()),
    min_size=1, max_size=8,
)


def generated(folder, capsys, generated_rows):
    """Card A and card B, random rows over two months, random types and categories, and some
    types changed after categorizing, so that a categorization no longer applies."""
    ledger = CategoryLedger(folder, capsys)
    ledger.add_account("B", "credit_card")
    assert ledger.run("category", "add", "Groceries", "--parent", "Food")[0] == 0
    for account in ("A", "B"):
        mine = [entry for index, entry in enumerate(generated_rows) if index % 2 == (account == "B")]
        if not mine:
            continue
        name = f"{account}.csv"
        ledger.card(name, *(
            f"{1 + day // 30:02d}/{1 + day % 28:02d}/2026,SYNTHETIC ROW {index},"
            + (f",{cents // 100}.{cents % 100:02d}" if money_in else
               f"{cents // 100}.{cents % 100:02d},")
            for index, (cents, money_in, _, _, day, _) in enumerate(mine)
        ), account=account)
        for transaction, (_, money_in, type_choice, category_choice, _, change) in zip(
                rows_of(ledger, name), mine, strict=True):
            types = IN_TYPES if money_in else OUT_TYPES
            financial_type = types[type_choice % len(types)]
            if financial_type is None:
                continue
            classification = ledger.classify_ok(transaction, financial_type, account=account)
            category = CATEGORIES[category_choice]
            if category and financial_type in ("purchase", "fee", "interest", "refund"):
                ledger.categorize_ok(transaction, category, account=account)
                if change:
                    ledger.classify_ok(transaction, "transfer", account=account,
                                       supersedes=classification)
    return ledger


def assert_categories_add_to_spending(found):
    parts = [group for _, group in found.spending_by_category]
    total = combined(parts)
    assert (total.transactions, total.out_cents, total.in_cents) == (
        found.spending.transactions, found.spending.out_cents, found.spending.in_cents)


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows)
def test_categories_add_to_spending_on_generated_ledgers(capsys, generated_rows):  # CC1
    with tempfile.TemporaryDirectory() as folder:
        ledger = generated(Path(folder), capsys, generated_rows)
        conn = ledger.conn()
        for account in (None, ledger.account_id("A"), ledger.account_id("B")):
            assert_categories_add_to_spending(income_and_spending(conn, account))
            for month in monthly_report(conn, account).months:
                assert_categories_add_to_spending(month.income_and_spending)
        conn.close()
        lines = by_category(ledger)
        if lines is not None:
            top = [line for line in lines if line[0] == "      "]
            count, amount = spending_line(ledger).groups()
            assert sum(int(line[2]) for line in top) == int(count)
            assert sum(round(float(line[3]) * 100) for line in top) == round(float(amount) * 100)


class TestPages:  # CC5
    @settings(max_examples=8, deadline=None,
              suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @given(generated_rows=rows)
    def test_pages_equal_the_cli_on_categorized_ledgers(self, capsys, generated_rows):
        with tempfile.TemporaryDirectory() as folder:
            ledger = generated(Path(folder), capsys, generated_rows)
            assert_pages_equal_the_cli(capsys, ledger.path, account_ids(ledger.path),
                                       [(None, None), ("2026-01", "2026-01"), ("2026-02", None)])

    def test_category_names_holding_html_show_as_text(self, ledger):
        name = '<b>F&amp;"q\'</b><script>x</script>'
        assert ledger.run("category", "add", name)[0] == 0
        ledger.spend(single(ledger), name)
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            for target in ("/", "/monthly"):
                page = parsed_page(client.get(target).body)
                assert not {"b", "script"} & set(page.tags), target
                assert any(name in line for line in page.report_lines), target
        finally:
            client.close()
        assert_pages_equal_the_cli(ledger.capsys, ledger.path, account_ids(ledger.path),
                                   [(None, None)])


def without_categories(text):
    """A report's lines without the 'By category' block, its uncategorized disclosure and the lines
    disclosing categorizations that do not apply."""
    lines, kept, in_block = text.splitlines(), [], False
    for line in lines:
        if line == "    By category:":
            in_block = True
            continue
        if in_block and line.startswith("      "):
            continue
        in_block = False
        if "Spending not categorized" in line or "uncategorized because" in line or (
                "unsettled categorization" in line):
            continue
        kept.append(line)
    return kept


@settings(max_examples=15, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows)
def test_every_other_line_is_as_without_categories(capsys, monkeypatch, generated_rows):  # CC4
    from personal_finance.reports import monthly, report_text
    from personal_finance.reports.totals import UnsettledCategorizations

    with tempfile.TemporaryDirectory() as folder:
        ledger = generated(Path(folder), capsys, generated_rows)
        commands = [("totals",), ("report", "monthly"), ("totals", "--account", "B"),
                    ("report", "monthly", "--account", "A", "--from", "2026-02")]
        shown = [ledger.run(*words) for words in commands]
        with monkeypatch.context() as patch:
            patch.setattr(report_text, "categories_in_use", lambda conn: None)
            patch.setattr(report_text, "unsettled_categorizations_by_state",
                          lambda conn, account: UnsettledCategorizations(0, 0, 0))
            real = monthly._transactions_with_unsettled_effects
            patch.setattr(monthly, "_transactions_with_unsettled_effects",
                          lambda conn: {**real(conn), "categorization": set()})
            plain = [ledger.run(*words) for words in commands]
        for (code, out, err), (plain_code, plain_out, plain_err) in zip(shown, plain, strict=True):
            assert (code, err) == (plain_code, plain_err)
            assert without_categories(out) == plain_out.splitlines()
