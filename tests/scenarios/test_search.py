"""pf transactions with filters (WC2, D-073 point 4), using synthetic data only. Each filter
selects exactly, filters compose with AND, malformed values are refused, the list stops at 500
with the rest counted, and with no filter it is as before."""

import re

import pytest
from test_decisions import CHECKING_HEADER
from test_tags import TagLedger

from personal_finance.reports.report_text import FILTERED_LIST_CAP

ROWS = (
    "S-1,2026-01-05,2026-01-05,SYNTHETIC  Coffee   HOUSE,-4.50,POSTED",
    "S-2,2026-01-10,2026-01-10,SYNTHETIC GROCER,-82.10,POSTED",
    "S-3,2026-01-15,2026-01-15,SYNTHETIC PAYROLL,2500.00,POSTED",
    "S-4,2026-02-01,2026-02-01,SYNTHETIC COFFEE HOUSE,-5.25,POSTED",
)


@pytest.fixture
def ledger(tmp_path, capsys):
    """Four checking rows in A, one card purchase in B, the grocer categorized Food, and the
    January coffee tagged Trip."""
    found = TagLedger(tmp_path, capsys)
    found.checking("a.csv", *ROWS)
    found.add_account("B")
    found.load_path(found.write("b.csv", CHECKING_HEADER,
                                ["S-9,2026-01-20,2026-01-20,SYNTHETIC COFFEE CART,-7.00,POSTED"]),
                    account="B", layout="synthetic_checking_v1")
    found.ids = {description: transaction for transaction, description in re.findall(
        r"^([0-9a-f-]{36})  \S+ +\S+  \S+ +(.+)$", found.run("transactions")[1], re.MULTILINE)}
    grocer = found.ids["SYNTHETIC GROCER"]
    for words in (("--type", "purchase"),):
        assert found.run("review", "classify", grocer, "--account", "A", "--revision",
                         found.transaction_revision(grocer), *words)[0] == 0
    assert found.run("review", "categorize", grocer, "--account", "A", "--revision",
                     found.transaction_revision(grocer), "--category", "Food")[0] == 0
    assert found.run("tag", "add", "Trip")[0] == 0
    found.tag_ok(found.ids["SYNTHETIC  Coffee   HOUSE"], "Trip")
    return found


def listed(ledger, *filters):
    code, out, err = ledger.run("transactions", *filters)
    assert code == 0, err
    return sorted(description for description in re.findall(
        r"^[0-9a-f-]{36}  \S+ +\S+  \S+ +(.+)$", out, re.MULTILINE))


class TestEachFilter:  # WC2
    def test_search_ignores_case_and_repeated_spaces(self, ledger):
        assert listed(ledger, "--search", "coffee house") == [
            "SYNTHETIC  Coffee   HOUSE", "SYNTHETIC COFFEE HOUSE"]

    def test_account(self, ledger):
        assert listed(ledger, "--account", "B") == ["SYNTHETIC COFFEE CART"]

    def test_dates_are_inclusive(self, ledger):
        assert listed(ledger, "--from", "2026-01-10", "--to", "2026-01-15") == [
            "SYNTHETIC GROCER", "SYNTHETIC PAYROLL"]

    def test_amounts_are_inclusive_and_signed(self, ledger):
        assert listed(ledger, "--min=-5.25", "--max=-4.50") == [
            "SYNTHETIC  Coffee   HOUSE", "SYNTHETIC COFFEE HOUSE"]

    def test_the_category_in_effect(self, ledger):
        assert listed(ledger, "--category", "Food") == ["SYNTHETIC GROCER"]

    def test_a_tag_applying(self, ledger):
        assert listed(ledger, "--tag", "Trip") == ["SYNTHETIC  Coffee   HOUSE"]

    def test_filters_compose_with_and(self, ledger):
        assert listed(ledger, "--search", "coffee", "--account", "A", "--from", "2026-01-20") == [
            "SYNTHETIC COFFEE HOUSE"]
        assert listed(ledger, "--search", "coffee", "--tag", "Trip", "--from",
                      "2026-01-20") == []

    def test_the_filters_are_shown_back_escaped(self, ledger):
        out = ledger.run("transactions", "--search", "co‮ffee", "--account", "B")[2]
        assert "printable" in out
        out = ledger.run("transactions", "--search", "<b>&", "--min=-1.00")[1]
        assert out.splitlines()[0] == "Transactions matching search <b>&, min -1.00:"
        assert out.splitlines()[-1] == "No transactions match."


class TestRefusals:  # WC2
    @pytest.mark.parametrize("words, message", [
        (("--from", "2026-13-01"), "--from"), (("--to", "yesterday"), "--to"),
        (("--from", "2026-02-01", "--to", "2026-01-01"), "after"),
        (("--min", "ten"), "--min"), (("--min=5.00", "--max=1.00"), "above"),
        (("--category", "Nope"), "category not found"), (("--tag", "Nope"), "tag not found"),
        (("--account", "Nope"), "account"), (("--search", "   "), "printable"),
        (("--search", "x" * 201), "printable"), (("--search", "a\x1bb"), "printable")])
    def test_a_malformed_filter_is_refused(self, ledger, words, message):
        code, out, err = ledger.run("transactions", *words)
        assert code == 2 and message in err and out == ""


def test_with_no_filter_the_list_is_as_before(ledger):
    code, out, _ = ledger.run("transactions")
    assert code == 0 and not out.startswith("Transactions matching")
    assert out.count("\n") == 5 and "Matching" not in out


def test_the_list_stops_at_500_with_the_rest_counted(tmp_path, capsys):
    ledger = TagLedger(tmp_path, capsys)
    ledger.checking("many.csv", *(f"S-{number},2026-01-{1 + number % 28:02d},,SYNTHETIC ROW "
                                  f"{number},-1.00,POSTED" for number in range(503)))
    out = ledger.run("transactions", "--search", "row")[1]
    lines = out.splitlines()
    assert len(lines) == 1 + FILTERED_LIST_CAP + 1
    assert lines[-1] == ("Matching: 503, the first 500 shown. 3 more match: narrow the filters to "
                         "see them.")
    out = ledger.run("transactions", "--search", "row 50")[1]
    assert out.splitlines()[-1] == "Matching: 4"  # rows 50 and 500 to 502


class TestThePage:  # WC2, D-073 point 4
    def page(self, ledger, query):
        from test_local_ui_writes import Browser

        browser = Browser(ledger.path)
        try:
            return browser.get(f"/transactions?{query}")
        finally:
            browser.close()

    def test_the_page_with_filters_equals_the_command(self, ledger):
        from local_ui_client import page_text

        account = re.search(r"\(([0-9a-f-]{36})\)", ledger.run(
            "review", "transaction", "show", ledger.ids["SYNTHETIC GROCER"])[1])[1]
        for query, words in (
                ("search=coffee+house&from=2026-01-01", ("--search", "coffee house", "--from",
                                                          "2026-01-01")),
                (f"account={account}&min=-90.00&max=-5.00", ("--account", account,
                                                            "--min=-90.00", "--max=-5.00")),
                ("category=Food&tag=", ("--category", "Food")),
                ("tag=Trip", ("--tag", "Trip")),
                ("search=%3Cb%3E%26", ("--search", "<b>&"))):
            response = self.page(ledger, query)
            assert response.status == 200, (query, response.text)
            assert page_text(response.body) == ledger.run("transactions", *words)[1], query

    def test_with_no_filter_the_page_is_as_before(self, ledger):
        from local_ui_client import page_text

        for query in ("", "search=&tag="):
            assert page_text(self.page(ledger, query).body) == ledger.run("transactions")[1]

    @pytest.mark.parametrize("query", ["search=a%1Bb", "from=2026-1-1", "min=ten", "x=1",
                                       "search=a&search=b", "search=%zz", "account=--db"])
    def test_a_malformed_filter_is_refused(self, ledger, query):
        assert self.page(ledger, query).status == 400

    def test_an_unknown_category_shows_the_clis_refusal(self, ledger):
        response = self.page(ledger, "category=Nope")
        assert response.status == 400 and "category not found" in response.text

    def test_rows_link_to_their_transaction_pages(self, ledger):
        from local_ui_client import parsed_page

        addresses = parsed_page(self.page(ledger, "search=coffee").body).addresses
        linked = sorted(address.split("=", 1)[1] for address in addresses
                        if address.startswith("/transaction?id="))
        assert linked == sorted((ledger.ids["SYNTHETIC  Coffee   HOUSE"],
                                 ledger.ids["SYNTHETIC COFFEE HOUSE"],
                                 ledger.ids["SYNTHETIC COFFEE CART"]))
