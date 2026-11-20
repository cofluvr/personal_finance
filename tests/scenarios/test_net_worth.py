"""Net worth from observations, account links, retirement history and net worth by member, end
to end, using synthetic data only (LA1, LA2, LA4 and LA5, D-071 points 1 to 3). LA3 is
tests/unit/test_net_worth_counting.py and migration 0029 test_link_migration.py."""

import re

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from planning_digest import evidence_digest
from test_decisions import LINK_TABLES
from test_funds import FundLedger
from test_local_ui import cli_output

from personal_finance.planning.net_worth import (
    AGGREGATE_IS_SUBACCOUNT,
    ALREADY_LINKED,
    LINK_TO_ITSELF,
    NOT_A_LOAN,
    NOT_LINKED,
    STALE_LINK_REVISION,
    SUBACCOUNT_IS_AGGREGATE,
)

AS_OF = "2026-03-31"
LINK_TOKEN = r"al1-[0-9a-f]{16}"


class NetWorthLedger(FundLedger):
    def links_shown(self):
        code, out, err = self.run("account", "links")
        assert (code, err) == (0, ""), err
        return out

    def link_token(self, account, kind="Link revision, as aggregate"):
        block = self.links_shown().split(f"Loan {account} (")[1].split("\nLoan ")[0]
        return re.search(rf"{kind}: ({LINK_TOKEN})", block)[1]

    def link(self, subaccount, aggregate, revision=None):
        return self.run("account", "link", "--subaccount", subaccount, "--aggregate", aggregate,
                        "--revision", revision or self.link_token(aggregate))

    def link_ok(self, subaccount, aggregate):
        code, _, err = self.link(subaccount, aggregate)
        assert (code, err) == (0, ""), err

    def unlink(self, subaccount, revision=None):
        return self.run("account", "unlink", "--subaccount", subaccount, "--revision",
                        revision or self.link_token(subaccount, "Unlink revision"))

    def report(self, *words, as_of=AS_OF):
        code, out, err = self.run("report", "net-worth", "--as-of", as_of, *words)
        assert (code, err) == (0, ""), err
        return out

    def total(self, out):
        return re.search(r"^Net worth, observed: (\S+?)(,|$)", out, re.MULTILINE)[1]

    def link_tables(self):
        return self.dump(LINK_TABLES)

    def refused(self, attempt, message):
        before = (self.link_tables(), self.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (self.link_tables(), self.evidence()) == before

    def evidence(self):
        conn = self.conn()
        try:
            return evidence_digest(conn)
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    """Checking A, savings S, a mortgage with two parts, and a card, observed in March."""
    ledger = NetWorthLedger(tmp_path, capsys)
    ledger.add_typed_account("S", "savings")
    for name in ("Mortgage", "Part 1", "Part 2"):
        ledger.add_typed_account(name, "loan")
    ledger.add_typed_account("Card", "credit_card")
    ledger.observe("A", "2026-03-20", "1500.00")
    ledger.observe("S", "2026-03-15", "8000.00")
    ledger.observe("Mortgage", "2026-03-01", "100000.00", option="--owed")
    ledger.observe("Part 1", "2026-03-10", "60000.00", option="--owed")
    ledger.observe("Part 2", "2026-03-10", "39000.00", option="--owed")
    ledger.observe("Card", "2026-03-25", "250.00", option="--owed")
    return ledger


class TestNetWorth:  # LA2
    def test_it_adds_valuations_exactly_with_liabilities_negative(self, ledger):
        out = ledger.report()
        assert "Account Mortgage (loan): -100000.00, observed 2026-03-01" in out
        assert "Account Card (credit card): -250.00, observed 2026-03-25" in out
        # 1,500 + 8,000 − 100,000 − 60,000 − 39,000 − 250, before any link.
        assert ledger.total(out) == "-189750.00"

    def test_an_unvalued_account_is_listed_and_never_zero(self, ledger):
        ledger.add_typed_account("Brokerage", "investment")
        out = ledger.report()
        assert ("Account Brokerage (investment): not valued, no observation on or before "
                "2026-03-31") in out
        assert "Net worth, observed: -189750.00, incomplete: 1 account not valued" in out
        assert "  Not valued: Brokerage" in out

    @pytest.mark.parametrize("as_of, warned", [("2026-04-01", False), ("2026-04-02", True)])
    def test_an_old_valuation_is_disclosed_past_31_days(self, ledger, as_of, warned):
        # The mortgage, observed on 1 March, is 31 days old on 1 April and 32 on 2 April.
        out = ledger.report(as_of=as_of)
        assert ("Mixed dates" in out) is warned
        if warned:
            assert "older than 31 days: Mortgage" in out

    @pytest.mark.parametrize("observed_on, warned", [("2026-01-30", False),
                                                     ("2026-01-29", True)])
    def test_valuations_spanning_more_than_31_days_name_every_one(self, ledger, observed_on,
                                                                   warned):
        # As of 2 March, A observed then and S on 2 March: 31 or 32 days apart.
        ledger.observe("A", observed_on, "1400.00")
        ledger.observe("S", "2026-03-02", "8000.00")
        out = ledger.report(as_of="2026-03-02")
        assert ("Mixed dates" in out) is warned
        if warned:
            assert ("span more than 31 days, or some are older than 31 days: A, Mortgage, S"
                    in out)

    def test_it_reads_observations_never_transactions(self, ledger):
        before = ledger.report()
        ledger.pay("b1.csv", "2026-03-21", amount="-500.00", text="SYNTHETIC SHOP")
        assert ledger.report() == before


class TestLinks:  # LA1, point 2
    def test_parts_newer_than_the_aggregate_count_instead(self, ledger):
        for part in ("Part 1", "Part 2"):
            ledger.link_ok(part, "Mortgage")
        out = ledger.report()
        assert "Mortgage (loan): -100000.00, observed 2026-03-01, not counted: subaccounts valued" \
            in out
        # 1,500 + 8,000 − 60,000 − 39,000 − 250.
        assert ledger.total(out) == "-89750.00"

    def test_an_aggregate_newer_than_a_part_counts_instead(self, ledger):
        for part in ("Part 1", "Part 2"):
            ledger.link_ok(part, "Mortgage")
        ledger.observe("Mortgage", "2026-03-12", "98500.00", option="--owed")
        out = ledger.report()
        assert "Part 1 (loan): -60000.00, observed 2026-03-10, not counted: aggregate valued" in out
        assert ledger.total(out) == "-89250.00"

    def test_refusals(self, ledger):
        ledger.link_ok("Part 1", "Mortgage")
        token = ledger.link_token("Mortgage")
        ledger.refused(lambda: ledger.link("Card", "Mortgage", token),
                       NOT_A_LOAN.format(account="Card"))
        ledger.refused(lambda: ledger.link("Part 2", "Card", token),
                       NOT_A_LOAN.format(account="Card"))
        ledger.refused(lambda: ledger.link("Mortgage", "Mortgage", token), LINK_TO_ITSELF)
        ledger.refused(lambda: ledger.link("Part 2", "Part 1", token),
                       AGGREGATE_IS_SUBACCOUNT.format(account="Part 1", aggregate="Mortgage"))
        ledger.add_typed_account("Other", "loan")
        ledger.refused(lambda: ledger.link("Part 1", "Other", ledger.link_token("Other")),
                       ALREADY_LINKED.format(account="Part 1", aggregate="Mortgage"))
        ledger.refused(lambda: ledger.link("Mortgage", "Other", ledger.link_token("Other")),
                       SUBACCOUNT_IS_AGGREGATE.format(account="Mortgage", subaccounts="Part 1"))
        ledger.refused(lambda: ledger.unlink("Part 2", "al1-0000000000000000"),
                       NOT_LINKED.format(account="Part 2"))

    def test_a_stale_token_for_each_input(self, ledger):
        token = ledger.link_token("Mortgage")
        ledger.observe("Part 2", "2026-03-11", "38900.00", option="--owed")
        ledger.link_ok("Part 2", "Mortgage")
        # A new link and a new observation of a linked account each move the token.
        ledger.refused(lambda: ledger.link("Part 1", "Mortgage", token), STALE_LINK_REVISION)
        token = ledger.link_token("Mortgage")
        ledger.observe("Part 2", "2026-03-12", "38800.00", option="--owed")
        ledger.refused(lambda: ledger.link("Part 1", "Mortgage", token), STALE_LINK_REVISION)
        token = ledger.link_token("Mortgage")
        ledger.observe("Mortgage", "2026-03-12", "98000.00", option="--owed")
        ledger.refused(lambda: ledger.link("Part 1", "Mortgage", token), STALE_LINK_REVISION)
        token = ledger.link_token("Part 2", "Unlink revision")
        ledger.observe("Part 2", "2026-03-13", "38700.00", option="--owed")
        ledger.refused(lambda: ledger.unlink("Part 2", token), STALE_LINK_REVISION)

    def test_one_subaccount_s_unlink_token_never_unlinks_another(self, ledger):
        for part in ("Part 1", "Part 2"):
            ledger.link_ok(part, "Mortgage")
        ledger.refused(lambda: ledger.unlink("Part 2",
                                             ledger.link_token("Part 1", "Unlink revision")),
                       STALE_LINK_REVISION)

    def test_unlink_restores_and_changes_no_ledger_table(self, ledger):
        before = (ledger.report(), ledger.evidence())
        ledger.link_ok("Part 1", "Mortgage")
        assert ledger.evidence() == before[1]
        assert ledger.unlink("Part 1")[0] == 0
        assert (ledger.report(), ledger.evidence()) == before
        assert "Loan Part 1 (" in ledger.links_shown()


class TestHistory:  # point 3
    def test_retirement_observations_and_contributions_by_month(self, ledger):
        ledger.add_typed_account("Retire", "retirement")
        ledger.observe("Retire", "2026-01-31", "20000.00")
        ledger.observe("Retire", "2026-02-28", "20600.00")
        ledger.pay("c1.csv", "2026-02-10", amount="-300.00", text="SYNTHETIC 401K",
                   financial_type="investment_contribution")
        (transaction,) = ledger.classified
        code, _, err = ledger.one_sided(transaction, "Retire")
        assert code == 0, err
        out = ledger.report()
        assert "    Observed: 2026-01-31 20000.00, 2026-02-28 20600.00" in out
        assert ("    Contributions in, applied investment contributions, actual: 2026-02 300.00 "
                "(1)") in out
        assert "nothing here is subtracted twice" in out

    def test_a_matched_contribution_counts_only_into_its_own_account(self, ledger):
        for name in ("Retire", "Broker"):
            ledger.add_typed_account(name, "retirement" if name == "Retire" else "investment")
        outflow = ledger.pay("c1.csv", "2026-02-10", amount="-300.00", text="SYNTHETIC 401K",
                             financial_type="investment_contribution")
        inflow = ledger.deposit("c2.csv", "2026-02-10", amount="300.00", text="SYNTHETIC 401K",
                                financial_type="investment_contribution", account="Retire")
        ledger.match_ok(outflow, inflow, counterpart_account="Retire")
        out = ledger.report().split("Retirement and investment history:")[1]
        retire = out.split("Account Retire (retirement)")[1].split("  Account ")[0]
        broker = out.split("Account Broker (investment)")[1].split("  Account ")[0]
        assert "actual: 2026-02 300.00 (1)" in retire
        assert "actual: none" in broker


def household(ledger):
    for name in ("Alex", "Bea"):
        assert ledger.run("household", "member", "add", name)[0] == 0


def attribute(ledger, account, *how):
    show = ledger.run("household", "account", "show", "--account", account)[1]
    assert ledger.run("household", "account", "set", "--account", account, *how,
                      "--revision", re.search(r"Revision: (a1-\S+)", show)[1])[0] == 0


class TestByMember:  # LA4
    def test_an_account_not_counted_gives_no_member_a_part(self, ledger):
        household(ledger)
        for part in ("Part 1", "Part 2"):
            ledger.link_ok(part, "Mortgage")
        attribute(ledger, "Mortgage", "--member", "Bea")
        parts = dict(re.findall(r"^    (\S+): (\S+)$", ledger.report("--member", "Bea"),
                                re.MULTILINE))
        assert parts["Bea"] == "0.00"

    def test_parts_and_unattributed_add_exactly_to_net_worth(self, ledger):
        for name in ("Alex", "Bea"):
            assert ledger.run("household", "member", "add", name)[0] == 0
        show = ledger.run("household", "share", "show")[1]
        assert ledger.run("household", "share", "set", "--part", "Alex=33.33", "--part",
                          "Bea=66.67", "--revision",
                          re.search(r"Revision: (h1-\S+)", show)[1])[0] == 0
        for account, how in (("A", ("--shared",)), ("S", ("--member", "Bea"))):
            show = ledger.run("household", "account", "show", "--account", account)[1]
            assert ledger.run("household", "account", "set", "--account", account, *how,
                              "--revision", re.search(r"Revision: (a1-\S+)", show)[1])[0] == 0
        out = ledger.report("--member", "Alex")
        parts = dict(re.findall(r"^    (\S+): (\S+)$", out, re.MULTILINE))
        # A's 1,500.00 shared: 499.95 and 1,000.05. S is Bea's. The rest is unattributed.
        assert parts == {"Alex": "499.95", "Bea": "9000.05", "unattributed": "-199250.00"}
        cents = sum(int(value.replace(".", "")) for value in parts.values())
        assert cents == int(ledger.total(out).replace(".", ""))
        assert "Net worth of Alex, by account attribution, observed: 499.95" in out

    def test_an_unknown_member(self, ledger):
        code, _, err = ledger.run("report", "net-worth", "--as-of", AS_OF, "--member", "Nobody")
        assert code == 2 and "household member not found" in err


class TestPage:  # LA5
    def test_the_page_and_the_command_agree_line_for_line(self, ledger):
        ledger.link_ok("Part 1", "Mortgage")
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            for as_of in (AS_OF, "2026-03-05", "2026-04-02"):
                assert page_text(client.get(f"/net-worth?as_of={as_of}").body) == cli_output(
                    ledger.capsys, "report", "net-worth", "--db", ledger.db, "--as-of", as_of)
            assert client.get("/net-worth?member=99&as_of=2026-03-01").status == 400
            assert client.request("POST", "/net-worth").status == 404  # off the allowlist
        finally:
            client.close()

    def test_names_on_the_page_are_text(self, ledger):
        ledger.add_typed_account('<b>Home&"</b>', "savings")
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            page = parsed_page(client.get(f"/net-worth?as_of={AS_OF}").body)
            assert not {"b"} & set(page.tags)
            assert any('<b>Home&"</b>' in line for line in page.report_lines)
        finally:
            client.close()
