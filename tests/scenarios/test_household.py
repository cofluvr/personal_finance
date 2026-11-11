"""Household members, the household share and account attribution, end to end, using synthetic data
only (HA1 to HA6, D-065)."""

import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_categorizations import CategoryLedger
from test_classifications import single
from test_decisions import (
    ALL_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    HOUSEHOLD_TABLES,
    drop_household_tables,
)
from test_spending_by_category import generated, rows
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance import cli
from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.reconcile.apply import reconcile_account
from personal_finance.reconcile.decisions import STALE_ACCOUNT
from personal_finance.reconcile.household import (
    ATTRIBUTION_ACTIVE,
    ATTRIBUTION_NOT_ACTIVE,
    ATTRIBUTION_WITHOUT_SHARE,
    MEMBER_NAME_BLANK,
    MEMBER_NAME_RESERVED,
    MEMBER_NAME_USED,
    MEMBER_UNKNOWN,
    SHARE_ACTIVE,
    SHARE_MEMBER_REPEATED,
    SHARE_NOT_ACTIVE,
    SHARE_NOT_WHOLE,
    SHARE_ONE_PART,
    SHARE_PART_MALFORMED,
    STALE_ATTRIBUTION_REVISION,
    STALE_SHARE_REVISION,
)
from personal_finance.reconcile.household_effects import allocate_cents, parse_percent
from personal_finance.reconcile.rules import MatchingRules

LEDGER_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                 *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES)

ODD_ROW = "01/10/2026,SYNTHETIC CAFE,6.51,"
REFUND_ROW = "01/11/2026,SYNTHETIC CAFE,,6.51"


class HouseholdLedger(CategoryLedger):
    def add_member(self, name):
        return self.run("household", "member", "add", name)

    def add_member_ok(self, *names):
        for name in names:
            code, _, err = self.add_member(name)
            assert (code, err) == (0, ""), err

    def share_show(self):
        code, out, err = self.run("household", "share", "show")
        assert code == 0, err
        return out

    def share_revision(self):
        return re.search(r"Revision: (h1-[0-9a-f]{16})", self.share_show())[1]

    def set_share(self, *parts, revision=None):
        words = ["household", "share", "set"]
        for part in parts:
            words += ["--part", part]
        return self.run(*words, "--revision", revision or self.share_revision())

    def set_share_ok(self, *parts):
        code, out, err = self.set_share(*parts)
        assert (code, err) == (0, ""), err
        return out

    def undo_share(self, revision=None):
        return self.run("household", "share", "undo", "--revision",
                        revision or self.share_revision())

    def account_show(self, account="A"):
        code, out, err = self.run("household", "account", "show", "--account", account)
        assert code == 0, err
        return out

    def account_revision(self, account="A"):
        return re.search(r"Revision: (a1-[0-9a-f]{16})", self.account_show(account))[1]

    def set_default(self, account="A", member=None, revision=None):
        attributed = ["--member", member] if member else ["--shared"]
        return self.run("household", "account", "set", "--account", account, *attributed,
                        "--revision", revision or self.account_revision(account))

    def set_default_ok(self, account="A", member=None):
        code, out, err = self.set_default(account, member)
        assert (code, err) == (0, ""), err
        return out

    def undo_default(self, account="A", revision=None):
        return self.run("household", "account", "undo", "--account", account, "--revision",
                        revision or self.account_revision(account))

    def household_line(self, transaction):
        found = re.findall(r"^  Household: (.*)$", self.transaction_show(transaction),
                           re.MULTILINE)
        return found[0] if found else None

    def refused(self, message, *words):
        before = self.everything()
        code, _, err = self.run(*words)
        assert (code, err) == (2, f"Error: {message}\n")
        assert self.everything() == before

    def everything(self):
        return self.dump(LEDGER_TABLES)


@pytest.fixture
def ledger(tmp_path, capsys):
    return HouseholdLedger(tmp_path, capsys)


@pytest.fixture
def household(ledger):
    """Michael and M, a 50/50 share, and card A holding an odd-cent purchase and its refund."""
    ledger.add_member_ok("Michael", "M")
    ledger.set_share_ok("Michael=50", "M=50")
    ledger.card("a.csv", ODD_ROW)
    ledger.card("b.csv", REFUND_ROW)
    return ledger


def make_stale(ledger, account="A"):
    """Reconcile under other rules, so the account is not current under the default ones."""
    conn = ledger.conn()
    conn.execute("BEGIN IMMEDIATE")
    reconcile_account(conn, ledger.account_id(account), MatchingRules(date_window_days=1))
    conn.execute("COMMIT")
    conn.close()


class TestAllocateCents:  # HA5
    @settings(max_examples=400, deadline=None)
    @given(st.integers(-10**12, 10**12),
           st.lists(st.integers(1, 9_999), min_size=1, max_size=5), st.randoms())
    def test_parts_are_exact_close_and_independent_of_order(self, amount, raw, random):
        weights = [*raw[:-1], 10_000 - sum(raw[:-1])] if sum(raw[:-1]) < 10_000 else None
        if weights is None or weights[-1] <= 0:
            return
        parts = allocate_cents(amount, weights)
        assert sum(parts) == amount
        for part, weight in zip(parts, weights, strict=True):
            # Within one cent of the exact share amount × weight / 10,000.
            assert abs(part * 10_000 - amount * weight) < 10_000
        assert allocate_cents(-amount, weights) == tuple(-part for part in parts)
        # The same weights for the same members give the same parts in any typed order: the
        # caller orders them by member, so a shuffle undone by that order changes nothing.
        order = list(range(len(weights)))
        random.shuffle(order)
        typed = {member: weights[member] for member in order}
        assert allocate_cents(amount, [typed[member] for member in sorted(typed)]) == parts

    @pytest.mark.parametrize(("amount", "weights", "expected"), [
        (1, [5_000, 5_000], (1, 0)),
        (-1, [5_000, 5_000], (-1, 0)),
        (651, [5_000, 5_000], (326, 325)),
        (100, [3_334, 3_333, 3_333], (34, 33, 33)),
        (2, [3_334, 3_333, 3_333], (1, 1, 0)),
        # Remainders 0.6667 and 0.3333 for the first two: the largest takes the cent.
        (1, [3_333, 6_667], (0, 1)),
        (0, [5_000, 5_000], (0, 0)),
        (10_000, [1, 9_999], (1, 9_999)),
    ])
    def test_worked_examples(self, amount, weights, expected):
        assert allocate_cents(amount, weights) == expected

    @pytest.mark.parametrize("weights", [[], [5_000], [5_000, 4_999], [10_000, 0],
                                         [5_000, 5_001, -1]])
    def test_weights_not_summing_to_whole_are_refused(self, weights):
        if weights == [5_000]:
            with pytest.raises(ValueError):
                allocate_cents(1, [5_000])
            assert allocate_cents(1, [10_000]) == (1,)
            return
        with pytest.raises(ValueError):
            allocate_cents(1, weights)

    def test_floats_are_refused(self):
        with pytest.raises(TypeError):
            allocate_cents(1.0, [5_000, 5_000])

    @pytest.mark.parametrize(("text", "expected"), [
        ("50", 5_000), ("33.34", 3_334), ("33.3", 3_330), ("0.01", 1), ("100", 10_000),
        ("33.333", None), ("-1", None), ("1e2", None), ("", None), (" 50", None), ("50.", None),
        ("٥٠", None),
    ])
    def test_percent_parsing(self, text, expected):
        assert parse_percent(text) == expected


class TestMembers:  # HA2
    def test_added_in_order_and_listed(self, ledger):
        ledger.add_member_ok("Michael", "M")
        code, out, err = ledger.run("household", "members")
        assert (code, err, out) == (0, "", "Michael\nM\nHousehold members: 2\n")

    @pytest.mark.parametrize(("name", "message"), [
        ("", MEMBER_NAME_BLANK), ("  \t", MEMBER_NAME_BLANK),
        ("shared", MEMBER_NAME_RESERVED), ("unattributed", MEMBER_NAME_RESERVED),
        ("Michael", MEMBER_NAME_USED),
    ])
    def test_refusals_change_nothing(self, ledger, name, message):
        ledger.add_member_ok("Michael")
        ledger.refused(message, "household", "member", "add", name)

    def test_names_compare_exactly(self, ledger):
        ledger.add_member_ok("Michael", "michael", "Shared", "Michael ")
        assert ledger.run("household", "members")[1].endswith("Household members: 4\n")

    def test_names_are_escaped(self, ledger):
        code, out, _ = ledger.add_member("Odd\x1b[2J\nname‮")
        assert (code, out) == (0, "Added household member Odd\\x1b[2J\\nname\\u202e\n")
        assert ledger.run("household", "members")[1] == (
            "Odd\\x1b[2J\\nname\\u202e\nHousehold members: 1\n")

    @pytest.mark.parametrize("words", [("household", "members"), ("household", "share", "show"),
                                       ("household", "account", "show", "--account", "A")])
    def test_shows_open_the_ledger_read_only(self, ledger, monkeypatch, words):
        opened = []

        def recording_connect(path: Path, *, read_only=False):
            opened.append(read_only)
            return connect(path, read_only=read_only)

        monkeypatch.setattr(cli, "connect", recording_connect)
        assert ledger.run(*words)[0] == 0
        assert opened == [True]


class TestShare:  # HA3
    def test_set_shows_what_moved(self, ledger):
        ledger.add_member_ok("Michael", "M")
        ledger.card("a.csv", ODD_ROW)
        ledger.set_share_ok("Michael=60", "M=40")
        ledger.set_default_ok(member=None)
        show = ledger.share_show()
        assert show.startswith("Household share: Michael 60.00%, M 40.00%\n")
        assert "Accounts attributed shared: A\n" in show
        assert ("By member now: Michael, 1 transactions, 3.91 out and 0.00 in; "
                "M, 1 transactions, 2.60 out and 0.00 in\n") in show

    def test_three_members_by_thirds(self, ledger):
        ledger.add_member_ok("Michael", "M", "K")
        out = ledger.set_share_ok("K=33.34", "Michael=33.33", "M=33.33")
        assert "set: Michael 33.33%, M 33.33%, K 33.34%\n" in out

    @pytest.mark.parametrize(("parts", "message"), [
        (("Michael=50", "Nobody=50"), MEMBER_UNKNOWN),
        (("Michael=100",), SHARE_ONE_PART),
        (("Michael=50", "M=49.99"), SHARE_NOT_WHOLE),
        (("Michael=50", "M=50.01"), SHARE_NOT_WHOLE),
        (("Michael=100", "M=0"), SHARE_PART_MALFORMED),
        (("Michael=33.333", "M=66.667"), SHARE_PART_MALFORMED),
        (("Michael", "M=50"), SHARE_PART_MALFORMED),
        (("Michael=50", "Michael=50"), SHARE_MEMBER_REPEATED),
    ])
    def test_refusals_change_nothing(self, ledger, parts, message):
        ledger.add_member_ok("Michael", "M")
        words = ["household", "share", "set"]
        for part in parts:
            words += ["--part", part]
        ledger.refused(message, *words, "--revision", ledger.share_revision())

    def test_a_set_while_active_is_refused(self, household):
        household.refused(SHARE_ACTIVE, "household", "share", "set", "--part", "Michael=40",
                          "--part", "M=60", "--revision", household.share_revision())

    def test_undo_then_set_changes_it(self, household):
        household.set_default_ok()
        code, out, err = household.undo_share()
        assert (code, err) == (0, "")
        assert "From: Michael, 2 transactions" in out and "To: unattributed" in out
        transaction = holding(household, "a.csv")
        assert household.household_line(transaction) == (
            "unattributed: its account's default or its allocation is shared and no household share "
            "is active. Set one with household share set")
        household.set_share_ok("Michael=40", "M=60")
        assert household.household_line(transaction) == (
            "shared, by the account's default and the household share: Michael -2.60, M -3.91")
        assert household.share_show().count("Household share:") == 1

    def test_undo_with_none_active_is_refused(self, ledger):
        ledger.refused(SHARE_NOT_ACTIVE, "household", "share", "undo", "--revision",
                       ledger.share_revision())

    def test_a_stale_token_is_refused_after_each_change(self, household):
        token = household.share_revision()
        household.set_default_ok()
        household.refused(STALE_SHARE_REVISION, "household", "share", "undo", "--revision", token)
        token = household.share_revision()
        household.card("c.csv", "01/20/2026,SYNTHETIC SHOP,1.00,")
        household.refused(STALE_SHARE_REVISION, "household", "share", "undo", "--revision", token)
        token = household.share_revision()
        assert household.undo_share()[0] == 0
        household.set_share_ok("Michael=50", "M=50")
        # The same share again is a new statement, but says the same thing, so the token holds.
        assert household.share_revision() == token
        assert household.undo_share()[0] == 0
        household.set_share_ok("Michael=40", "M=60")
        household.refused(STALE_SHARE_REVISION, "household", "share", "undo", "--revision", token)

    def test_a_stale_token_is_refused_after_a_change_of_currency(self, household):
        household.set_default_ok()
        make_stale(household)
        token = household.share_revision()
        household.refused(STALE_ACCOUNT, "household", "share", "undo", "--revision", token)
        assert household.run("reconcile", "--account", "A")[0] == 0
        household.refused(STALE_SHARE_REVISION, "household", "share", "undo", "--revision", token)

    def test_a_stale_token_is_refused_after_a_default_the_share_does_not_reach(self, ledger):
        ledger.add_member_ok("Michael", "M")
        ledger.add_account("B", "credit_card")
        ledger.card("a.csv", ODD_ROW, account="B")
        token = ledger.share_revision()
        ledger.set_default_ok("B", "Michael")
        ledger.refused(STALE_SHARE_REVISION, "household", "share", "set", "--part", "Michael=50",
                       "--part", "M=50", "--revision", token)
        ledger.set_share_ok("Michael=50", "M=50")
        token = ledger.share_revision()
        assert ledger.undo_default("B")[0] == 0
        ledger.refused(STALE_SHARE_REVISION, "household", "share", "undo", "--revision", token)

    def test_it_reaches_only_accounts_attributed_shared(self, household):
        household.add_account("B", "credit_card")
        household.card("c.csv", ODD_ROW, account="B")
        household.set_default_ok("B", "Michael")
        assert "The share reaches: 0 transactions" in household.share_show()
        household.set_default_ok()
        assert "The share reaches: 2 transactions, 6.51 out and 6.51 in\n" in (
            household.share_show())

    def test_an_account_not_shared_does_not_block_the_share(self, household):
        household.add_account("B", "credit_card")
        household.card("c.csv", ODD_ROW, account="B")
        make_stale(household, "B")
        assert household.undo_share()[0] == 0


class TestAccountDefault:  # HA4
    def test_a_member_default(self, household):
        out = household.set_default_ok(member="M")
        assert out.splitlines()[0].startswith("Account A attributed to M: attribution ")
        assert household.household_line(holding(household, "a.csv")) == (
            "M, by the account's default")
        assert household.household_line(holding(household, "b.csv")) == (
            "M, by the account's default")

    def test_shared_follows_the_share_with_the_odd_cent_to_the_first_member(self, household):
        household.set_default_ok()
        assert household.household_line(holding(household, "a.csv")) == (
            "shared, by the account's default and the household share: Michael -3.26, M -3.25")
        # A full refund nets to zero for each member.
        assert household.household_line(holding(household, "b.csv")) == (
            "shared, by the account's default and the household share: Michael 3.26, M 3.25")

    def test_it_follows_a_corrected_amount(self, household):
        household.set_default_ok()
        transaction = holding(household, "a.csv")
        household.correct_ok(transaction, "amount", "-10.01")
        assert household.household_line(transaction) == (
            "shared, by the account's default and the household share: Michael -5.01, M -5.00")

    def test_it_reaches_transactions_imported_later(self, household):
        household.set_default_ok(member="Michael")
        household.card("c.csv", "01/20/2026,SYNTHETIC SHOP,1.00,")
        assert household.household_line(holding(household, "c.csv")) == (
            "Michael, by the account's default")

    def test_undo_reverses_it(self, household):
        household.set_default_ok(member="M")
        code, out, err = household.undo_default()
        assert (code, err) == (0, "")
        assert "undone. It stays on record." in out
        assert household.household_line(holding(household, "a.csv")) is None
        assert "default none" in household.account_show()

    @pytest.mark.parametrize(("words", "message"), [
        (("--member", "Nobody"), MEMBER_UNKNOWN),
    ])
    def test_an_unknown_member_is_refused(self, household, words, message):
        household.refused(message, "household", "account", "set", "--account", "A", *words,
                          "--revision", household.account_revision())

    def test_an_unknown_account_is_refused(self, household):
        before = household.everything()
        code, _, err = household.run("household", "account", "set", "--account", "Z", "--shared",
                                     "--revision", household.account_revision())
        assert (code, err) == (2, "Error: account not found: Z\n")
        assert household.everything() == before

    def test_shared_with_no_active_share_is_refused(self, ledger):
        ledger.add_member_ok("Michael", "M")
        ledger.refused(ATTRIBUTION_WITHOUT_SHARE, "household", "account", "set", "--account", "A",
                       "--shared", "--revision", ledger.account_revision())

    def test_a_second_active_default_is_refused(self, household):
        household.set_default_ok(member="M")
        household.refused(ATTRIBUTION_ACTIVE, "household", "account", "set", "--account", "A",
                          "--member", "Michael", "--revision", household.account_revision())

    def test_undo_with_none_active_is_refused(self, household):
        household.refused(ATTRIBUTION_NOT_ACTIVE, "household", "account", "undo", "--account",
                          "A", "--revision", household.account_revision())

    def test_a_stale_token_is_refused(self, household):
        token = household.account_revision()
        household.card("c.csv", "01/20/2026,SYNTHETIC SHOP,1.00,")
        household.refused(STALE_ATTRIBUTION_REVISION, "household", "account", "set", "--account",
                          "A", "--shared", "--revision", token)
        household.set_default_ok()
        token = household.account_revision()
        household.correct_ok(holding(household, "a.csv"), "amount", "-1.00")
        household.refused(STALE_ATTRIBUTION_REVISION, "household", "account", "undo",
                          "--account", "A", "--revision", token)
        token = household.account_revision()
        assert household.undo_share()[0] == 0
        household.set_share_ok("Michael=40", "M=60")
        household.refused(STALE_ATTRIBUTION_REVISION, "household", "account", "undo",
                          "--account", "A", "--revision", token)

    def test_a_stale_account_is_refused_first(self, household):
        make_stale(household)
        household.refused(STALE_ACCOUNT, "household", "account", "set", "--account", "A",
                          "--member", "Nobody", "--revision", "a1-0000000000000000")

    def test_another_accounts_token_is_refused(self, household):
        household.add_account("B", "credit_card")
        household.card("c.csv", ODD_ROW, account="B")
        household.refused(STALE_ATTRIBUTION_REVISION, "household", "account", "set", "--account",
                          "A", "--shared", "--revision", household.account_revision("B"))

    def test_the_token_is_the_same_in_any_ledger_holding_the_same(self, tmp_path, capsys):
        tokens = []
        for folder in ("one", "two"):
            (tmp_path / folder).mkdir()
            ledger = HouseholdLedger(tmp_path / folder, capsys)
            ledger.add_member_ok("Michael", "M")
            ledger.set_share_ok("Michael=50", "M=50")
            ledger.card("a.csv", ODD_ROW)
            ledger.set_default_ok()
            tokens.append((ledger.share_revision(), ledger.account_revision()))
        assert tokens[0] == tokens[1]


def shown_everywhere(ledger, transactions):
    words = [("totals",), ("report", "monthly"), ("totals", "--account", "B"),
             ("report", "monthly", "--account", "A", "--from", "2026-02"), ("transactions",),
             ("review", "list"), ("review", "classifications"), ("review", "categorizations")]
    words += [("review", "transaction", "show", transaction) for transaction in transactions]
    return [ledger.run(*command) for command in words]


def without_household_lines(shown):
    return [(code, re.sub(r"^  Household: .*\n", "", out, flags=re.MULTILINE), err)
            for code, out, err in shown]


@settings(max_examples=12, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(generated_rows=rows, defaults=st.tuples(st.sampled_from(["Michael", "M", None]),
                                               st.sampled_from(["Michael", "M", None])))
def test_members_and_defaults_change_nothing_else(capsys, generated_rows, defaults):  # HA6
    with tempfile.TemporaryDirectory() as folder:
        ledger = generated(Path(folder), capsys, generated_rows)
        conn = ledger.conn()
        transactions = [row[0] for row in conn.execute(
            "SELECT id FROM ledger_transaction ORDER BY id")]
        conn.close()
        before = shown_everywhere(ledger, transactions)
        ledger.__class__ = HouseholdLedger
        ledger.add_member_ok("Michael", "M")
        ledger.set_share_ok("Michael=50", "M=50")
        for account, member in zip(("A", "B"), defaults, strict=True):
            ledger.set_default_ok(account, member)
        after = shown_everywhere(ledger, transactions)
        assert without_household_lines(after) == before
        # Every transaction shows its attribution, and its parts add to its effective amount.
        for code, out, _ in after[8:]:
            assert code == 0
            (line,) = re.findall(r"^  Household: (.*)$", out, re.MULTILINE)
            amount = int(re.search(r"^    Amount: (\S+)$", out, re.MULTILINE)[1].replace(".", ""))
            parts = [int(cents.replace(".", "")) for cents in re.findall(r" (-?\d+\.\d\d)", line)]
            if line.startswith("shared"):
                assert sum(parts) == amount and len(parts) == 2


class TestReviewShow:  # HA6
    def test_nothing_where_no_default_reaches(self, household):
        household.add_account("B", "credit_card")
        household.set_default_ok("B", "Michael")
        out = household.transaction_show(holding(household, "a.csv"))
        assert "Household" not in out

    def test_review_show_gives_it_too(self, household):
        household.set_default_ok()
        household.card("c.csv", ODD_ROW)
        (item,) = household.items()
        assert ("  Household: shared, by the account's default and the household share: "
                "Michael -3.26, M -3.25\n") in household.show(item)

    def test_a_name_is_escaped(self, ledger):
        ledger.add_member_ok("Odd\x1b[2J\nname")
        ledger.card("a.csv", ODD_ROW)
        ledger.set_default_ok(member="Odd\x1b[2J\nname")
        assert ledger.household_line(holding(ledger, "a.csv")) == (
            "Odd\\x1b[2J\\nname, by the account's default")

    def test_tokens_do_not_move(self, household):
        transaction = holding(household, "a.csv")
        household.card("c.csv", ODD_ROW)
        (item,) = household.items()
        tokens = (household.transaction_revision(transaction), household.revision(item))
        household.set_default_ok()
        assert (household.transaction_revision(transaction), household.revision(item)) == tokens


VERSION_21_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES)
SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("review", "categorizations"), ("review", "classifications"),
                          ("category", "rules")]


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        *SHOWN_BEFORE_AND_AFTER, ("review", "transaction", "show", holding(ledger, "a.csv")))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Card A holding a categorized purchase, set back to 21, with what was shown before."""
    ledger = HouseholdLedger(tmp_path, capsys)
    ledger.spend(single(ledger))
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_household_tables(conn)
    conn.execute("PRAGMA user_version = 21")
    conn.close()
    return ledger


class TestMigration:  # HA1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_21_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-two", 22)) == 22
        for table in HOUSEHOLD_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_21_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_21_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("household", "members")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("household", "members")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 22)
        newest = load_migrations()[21].path
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_21_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 21
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(HOUSEHOLD_TABLES)
        conn.close()
        assert populated.dump(VERSION_21_TABLES) == before


@pytest.fixture
def history(household):
    """Two members, a share once undone and set again, and a default once undone and set again."""
    household.set_default_ok(member="M")
    assert household.undo_default()[0] == 0
    household.set_default_ok()
    assert household.undo_share()[0] == 0
    household.set_share_ok("Michael=40", "M=60")
    return household


def active_share(conn):
    return conn.execute(
        """SELECT share_id FROM household_share_event made WHERE event = 'made'
           AND NOT EXISTS (SELECT 1 FROM household_share_event undone
                           WHERE undone.share_id = made.share_id AND undone.event = 'undone')"""
    ).fetchone()[0]


class TestAppendOnly:  # HA1
    @pytest.mark.parametrize("statement", [
        "UPDATE household_member SET name = name",
        "DELETE FROM household_member",
        "INSERT INTO household_member SELECT * FROM household_member",
        "INSERT INTO household_member (name) VALUES ('Michael')",
        "UPDATE household_share SET created_at = created_at",
        "DELETE FROM household_share",
        "INSERT INTO household_share SELECT * FROM household_share",
        "UPDATE household_share_part SET basis_points = basis_points",
        "DELETE FROM household_share_part",
        "INSERT INTO household_share_part SELECT * FROM household_share_part",
        "UPDATE household_share_event SET event = event",
        "DELETE FROM household_share_event",
        "INSERT INTO household_share_event (share_id, event) SELECT share_id, event "
        "FROM household_share_event",
        "UPDATE account_attribution SET member_id = member_id",
        "DELETE FROM account_attribution",
        "INSERT INTO account_attribution SELECT * FROM account_attribution",
        "UPDATE account_attribution_event SET event = event",
        "DELETE FROM account_attribution_event",
        "INSERT INTO account_attribution_event (attribution_id, event) "
        "SELECT attribution_id, event FROM account_attribution_event",
    ])
    def test_history_refuses_change(self, history, statement):
        before = history.everything()
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.everything() == before

    def test_a_control_insert_of_each_succeeds(self, history):
        conn = history.conn()
        conn.execute("INSERT INTO household_member (name) VALUES ('K')")
        conn.execute("INSERT INTO household_share (id) VALUES ('control')")
        conn.execute("""INSERT INTO household_share_part (share_id, member_id, basis_points)
                        SELECT 'control', id, 5000 FROM household_member WHERE name IN ('M', 'K')""")
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES (?, 'undone')",
                     (active_share(conn),))
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES ('control', 'made')")
        conn.execute("""INSERT INTO account_attribution (id, account_id, member_id)
                        SELECT 'control', id, NULL FROM account""")
        (attribution,) = conn.execute(
            """SELECT attribution_id FROM account_attribution_event made WHERE event = 'made'
               AND NOT EXISTS (SELECT 1 FROM account_attribution_event undone
                               WHERE undone.attribution_id = made.attribution_id
                                 AND undone.event = 'undone')""").fetchone()
        conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                     "VALUES (?, 'undone')", (attribution,))
        conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                     "VALUES ('control', 'made')")
        conn.close()

    @pytest.mark.parametrize("name", ["", " ", "shared", "unattributed"])
    def test_the_schema_refuses_a_reserved_or_blank_name(self, ledger, name):
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO household_member (name) VALUES (?)", (name,))
        conn.execute("INSERT INTO household_member (name) VALUES ('control')")
        conn.close()

    @pytest.mark.parametrize("weights", [(5_000,), (5_000, 4_999), (5_000, 5_001)])
    def test_the_schema_refuses_a_share_not_summing_to_whole(self, ledger, weights):
        ledger.add_member_ok("Michael", "M")
        conn = ledger.conn()
        for share, parts in (("bad", weights), ("control", (5_000, 5_000))):
            conn.execute("INSERT INTO household_share (id) VALUES (?)", (share,))
            conn.executemany(
                "INSERT INTO household_share_part (share_id, member_id, basis_points) "
                "VALUES (?, ?, ?)", [(share, member, weight)
                                      for member, weight in enumerate(parts, start=1)])
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO household_share_event (share_id, event) VALUES ('bad', 'made')")
        conn.execute("INSERT INTO household_share_event (share_id, event) "
                     "VALUES ('control', 'made')")
        conn.close()

    @pytest.mark.parametrize("weight", [0, 10_000, -1])
    def test_the_schema_refuses_a_part_outside_its_range(self, ledger, weight):
        ledger.add_member_ok("Michael")
        conn = ledger.conn()
        conn.execute("INSERT INTO household_share (id) VALUES ('s')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO household_share_part VALUES ('s', 1, ?)", (weight,))
        conn.execute("INSERT INTO household_share_part VALUES ('s', 1, 9999)")
        conn.close()

    def test_the_schema_refuses_a_second_active_share(self, history):
        conn = history.conn()
        conn.execute("INSERT INTO household_share (id) VALUES ('second')")
        conn.execute("""INSERT INTO household_share_part (share_id, member_id, basis_points)
                        SELECT 'second', id, 5000 FROM household_member""")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO household_share_event (share_id, event) "
                         "VALUES ('second', 'made')")
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES (?, 'undone')",
                     (active_share(conn),))
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES ('second', 'made')")
        conn.close()

    def test_the_schema_refuses_a_part_added_once_made(self, history):
        history.add_member_ok("K")
        conn = history.conn()
        share = active_share(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO household_share_part (share_id, member_id, basis_points)
                            SELECT ?, id, 1 FROM household_member WHERE name = 'K'""", (share,))
        conn.execute("INSERT INTO household_share (id) VALUES ('control')")
        conn.execute("""INSERT INTO household_share_part (share_id, member_id, basis_points)
                        SELECT 'control', id, 1 FROM household_member WHERE name = 'K'""")
        conn.close()

    def test_the_schema_refuses_a_second_active_default(self, history):
        history.add_account("B", "credit_card")
        conn = history.conn()
        for attribution, account in (("second", "A"), ("control", "B")):
            conn.execute("""INSERT INTO account_attribution (id, account_id, member_id)
                            SELECT ?, id, NULL FROM account WHERE display_name = ?""",
                         (attribution, account))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                         "VALUES ('second', 'made')")
        conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                     "VALUES ('control', 'made')")
        conn.close()
