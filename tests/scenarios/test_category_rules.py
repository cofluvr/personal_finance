"""Category rules stated by a person, end to end, using synthetic data only (RA1 to RA6, D-064)."""

import re
import sqlite3

import pytest
from test_categorizations import CategoryLedger
from test_classifications import single
from test_confirmations import confirm_ok
from test_decisions import (
    ALL_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    pair_up,
)
from test_separations import ID_ROW, merged_two
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.reconcile.apply import reconcile_account
from personal_finance.reconcile.categorizations import CATEGORY_UNKNOWN
from personal_finance.reconcile.category_rule_effects import (
    NORMALIZATION_VERSION,
    UnknownNormalization,
    load_active_rules,
    normalized_text,
)
from personal_finance.reconcile.category_rules import (
    RULE_ALREADY_ACTIVE,
    RULE_DATE_INVALID,
    RULE_NOT_ACTIVE,
    RULE_NOT_FOUND,
    RULE_TEXT_BLANK,
    STALE_PREVIEW,
    STALE_RULE_REVISION,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reports import category_rule_evidence

LEDGER_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                 *CATEGORY_RULE_TABLES)

CAFE_ROW = "01/10/2026,SYNTHETIC CAFE,6.50,"
SHOP_ROW = "01/12/2026,SYNTHETIC SHOP,9.00,"


class RuleLedger(CategoryLedger):
    def rule_words(self, category, contains, account=None, financial_type=None, from_date=None):
        words = ["--category", category, "--description-contains", contains]
        if account:
            words += ["--account", account]
        if financial_type:
            words += ["--type", financial_type]
        if from_date:
            words += ["--from", from_date]
        return words

    def preview(self, category, contains, **options):
        return self.run("category", "rule", "preview", *self.rule_words(category, contains,
                                                                         **options))

    def preview_ok(self, category, contains, **options):
        code, out, err = self.preview(category, contains, **options)
        assert (code, err) == (0, ""), err
        return out

    def preview_revision(self, category, contains, **options):
        return re.search(r"Revision: (p1-[0-9a-f]{16})",
                         self.preview_ok(category, contains, **options))[1]

    def add_rule(self, category, contains, revision=None, **options):
        return self.run("category", "rule", "add", *self.rule_words(category, contains, **options),
                        "--preview",
                        revision or self.preview_revision(category, contains, **options))

    def add_rule_ok(self, category, contains, **options):
        code, out, err = self.add_rule(category, contains, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Category rule (\S+) recorded", out)[1]

    def rule_show(self, rule):
        code, out, err = self.run("category", "rule", "show", rule)
        assert code == 0, err
        return out

    def rule_revision(self, rule):
        return re.search(r"Revision: (q1-[0-9a-f]{16})", self.rule_show(rule))[1]

    def undo_rule(self, rule, revision=None):
        return self.run("category", "rule", "undo", rule,
                        "--revision", revision or self.rule_revision(rule))

    def undo_rule_ok(self, rule, **options):
        code, out, err = self.undo_rule(rule, **options)
        assert (code, err) == (0, ""), err
        return out

    def rule_outcomes(self):
        """Each transaction a rule reaches as its file names, its state and its category."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (tuple(sorted(names[transaction_id])), state, category)
            for transaction_id, state, category in conn.execute(
                """SELECT derived.transaction_id, derived.state, category.name
                   FROM transaction_rule_category derived
                   LEFT JOIN category ON category.id = derived.category_id"""
            )
        )
        conn.close()
        return found

    def everything(self):
        return self.dump(LEDGER_TABLES)


@pytest.fixture
def ledger(tmp_path, capsys):
    return RuleLedger(tmp_path, capsys)


def bought(ledger, name, row, financial_type="purchase", account="A"):
    """One card row in its own file, classified."""
    ledger.card(name, row, account=account)
    transaction = holding(ledger, name)
    ledger.classify_ok(transaction, financial_type, account=account)
    return transaction


class TestNormalization:  # RA2
    @pytest.mark.parametrize(("text", "expected"), [
        ("Trader  Joe's", "trader joe's"),
        ("  CAFÉ\tNOIR  ", "café noir"),
        ("ＳＨＯＰ", "shop"),
        ("Straße", "strasse"),
        ("   ", ""),
    ])
    def test_it_folds_case_width_and_spaces(self, text, expected):
        assert normalized_text(text) == expected

    def test_its_version_is_stored_and_an_unknown_one_is_refused(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        conn = ledger.conn()
        assert conn.execute("SELECT normalization_version FROM category_rule").fetchone() == (
            NORMALIZATION_VERSION,)
        conn.execute("DROP TRIGGER category_rule_no_update")
        conn.execute("UPDATE category_rule SET normalization_version = 2")
        with pytest.raises(UnknownNormalization, match=rule):
            load_active_rules(conn)
        conn.close()


class TestMatching:  # RA2
    def test_contains_ignores_case_and_repeated_spaces(self, ledger):
        bought(ledger, "a.csv", "01/10/2026,SYNTHETIC   COFFEE BAR,6.50,")
        bought(ledger, "b.csv", SHOP_ROW)
        ledger.add_rule_ok("Food", "coffee bar")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_a_corrected_description_is_what_it_reads(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Travel", "airline")
        assert ledger.rule_outcomes() == []
        correction = ledger.correct_ok(transaction, "description", "SYNTHETIC AIRLINE")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Travel")]
        assert ledger.undo_correction(correction)[0] == 0
        assert ledger.rule_outcomes() == []

    def test_an_account_narrows_it(self, ledger):
        ledger.add_account("B", "credit_card")
        bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", CAFE_ROW, account="B")
        ledger.add_rule_ok("Food", "cafe", account="B")
        assert ledger.rule_outcomes() == [(("b.csv",), "applied", "Food")]

    def test_every_account_without_one(self, ledger):
        ledger.add_account("B", "credit_card")
        bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", CAFE_ROW, account="B")
        ledger.add_rule_ok("Food", "cafe")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food"),
                                          (("b.csv",), "applied", "Food")]

    def test_a_type_narrows_it(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", "01/11/2026,SYNTHETIC CAFE,1.00,", financial_type="fee")
        ledger.add_rule_ok("Interest and financial fees", "cafe", financial_type="fee")
        assert ledger.rule_outcomes() == [(("b.csv",), "applied", "Interest and financial fees")]

    def test_a_refund_is_reached(self, ledger):
        bought(ledger, "a.csv", "01/12/2026,SYNTHETIC CAFE,,4.00", financial_type="refund")
        ledger.add_rule_ok("Food", "cafe")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_a_first_date_narrows_it_on_the_effective_date(self, ledger):
        early = bought(ledger, "a.csv", "01/09/2026,SYNTHETIC CAFE,6.50,")
        bought(ledger, "b.csv", "01/11/2026,SYNTHETIC CAFE,6.50,")
        ledger.add_rule_ok("Food", "cafe", from_date="2026-01-10")
        assert ledger.rule_outcomes() == [(("b.csv",), "applied", "Food")]
        ledger.correct_ok(early, "transaction_date", "2026-01-10")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food"),
                                          (("b.csv",), "applied", "Food")]

    def test_matching_configuration_changes_nothing(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        outcomes = ledger.rule_outcomes()
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, ledger.account_id("A"), MatchingRules(date_window_days=1))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.rule_outcomes() == outcomes


class TestRefusals:  # RA2, RA3
    def refused(self, ledger, message, *arguments, **options):
        before = ledger.everything()
        code, out, err = ledger.add_rule(*arguments, **options)
        assert (code, out) == (2, "") and err == f"Error: {message}\n"
        assert ledger.everything() == before

    def preview_refused(self, ledger, message, *arguments, **options):
        code, out, err = ledger.preview(*arguments, **options)
        assert (code, out) == (2, "") and err == f"Error: {message}\n"

    @pytest.mark.parametrize("category", ["Nothing like it", "food", "uncategorized"])
    def test_an_unknown_category(self, ledger, category):
        bought(ledger, "a.csv", CAFE_ROW)
        self.preview_refused(ledger, CATEGORY_UNKNOWN, category, "cafe")
        self.refused(ledger, CATEGORY_UNKNOWN, category, "cafe", revision="p1-0000000000000000")

    @pytest.mark.parametrize("contains", ["", "   ", "\t"])
    def test_blank_text(self, ledger, contains):
        bought(ledger, "a.csv", CAFE_ROW)
        self.preview_refused(ledger, RULE_TEXT_BLANK, "Food", contains)
        self.refused(ledger, RULE_TEXT_BLANK, "Food", contains, revision="p1-0000000000000000")

    @pytest.mark.parametrize("from_date", ["2026-02-30", "2026-1-05", "yesterday", "20260105"])
    def test_a_malformed_date(self, ledger, from_date):
        bought(ledger, "a.csv", CAFE_ROW)
        self.refused(ledger, RULE_DATE_INVALID, "Food", "cafe", from_date=from_date,
                     revision="p1-0000000000000000")

    def test_a_type_outside_spending(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        before = ledger.everything()
        with pytest.raises(SystemExit):
            ledger.add_rule("Food", "cafe", financial_type="income",
                            revision="p1-0000000000000000")
        assert "invalid choice" in ledger.capsys.readouterr().err
        assert ledger.everything() == before

    def test_an_unknown_account(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        before = ledger.everything()
        code, _, err = ledger.add_rule("Food", "cafe", account="Nowhere",
                                       revision="p1-0000000000000000")
        assert code == 2 and "account not found" in err
        assert ledger.everything() == before

    def test_a_stale_preview(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        self.refused(ledger, STALE_PREVIEW, "Food", "cafe", revision="p1-0000000000000000")

    @pytest.mark.parametrize("change", ["import", "correction", "classification",
                                        "categorization", "rule"])
    def test_a_preview_made_before_a_change(self, ledger, change):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        token = ledger.preview_revision("Food", "cafe")
        if change == "import":
            bought(ledger, "b.csv", CAFE_ROW)
        elif change == "correction":
            ledger.correct_ok(transaction, "description", "SYNTHETIC SHOP")
        elif change == "classification":
            ledger.classify_ok(transaction, "transfer", supersedes=re.search(
                r"Classification (\S+):", ledger.run("review", "classifications")[1])[1])
        elif change == "categorization":
            ledger.categorize_ok(transaction, "Travel")
        else:
            ledger.add_rule_ok("Travel", "synthetic")
        self.refused(ledger, STALE_PREVIEW, "Food", "cafe", revision=token)

    def test_the_same_rule_twice_even_typed_otherwise(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "  CAFE ")
        token = ledger.preview_revision("Food", "cafe")
        self.refused(ledger, RULE_ALREADY_ACTIVE.format(rule=rule), "Food", "cafe",
                     revision=token)

    def test_a_stale_account_is_checked_first(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        assert "adding it will be refused until it is" in ledger.preview_ok("Food", "cafe")
        self.refused(ledger, STALE_ACCOUNT, "No such category", "", from_date="bad",
                     revision="p1-0000000000000000")

    def test_a_stale_account_elsewhere_refuses_only_a_rule_reaching_it(self, ledger):
        ledger.add_account("B", "credit_card")
        bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", CAFE_ROW, account="B")
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ? WHERE account_id = ?",
                     ("0" * 64, ledger.account_id("B")))
        conn.close()
        self.refused(ledger, STALE_ACCOUNT, "Food", "cafe",
                     revision=ledger.preview_revision("Food", "cafe"))
        ledger.add_rule_ok("Food", "cafe", account="A")


class TestPreview:  # RA3
    def test_it_lists_every_change_and_writes_nothing(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", SHOP_ROW)
        before = (ledger.everything(), ledger.path.read_bytes())
        out = ledger.preview_ok("Food", "synthetic")
        assert (ledger.everything(), ledger.path.read_bytes()) == before
        assert out.startswith(
            "Category rule preview: spending whose description contains 'synthetic', in every "
            "account, any spending type, any date, takes Food\n"
            "Matches: 2 spending transactions. A person's categorization comes first on 0. "
            "Unchanged by other rules: 0.\nChanges: 2\n")
        changes = re.findall(r"^  Transaction \S+: A, (\S+), (\S+), (.*): (.*)$", out, re.MULTILINE)
        assert sorted(changes) == [
            ("2026-01-10", "-6.50", "SYNTHETIC CAFE", "uncategorized now, Food by rules after"),
            ("2026-01-12", "-9.00", "SYNTHETIC SHOP", "uncategorized now, Food by rules after"),
        ]

    def test_add_says_what_it_changed(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        code, out, err = ledger.add_rule("Food", "cafe")
        assert (code, err) == (0, "")
        assert re.fullmatch(
            r"Category rule \S+ recorded: spending whose description contains 'cafe', in every "
            r"account, any spending type, any date, takes Food\n  Changed: 1 transactions, as "
            r"previewed\.\n  A person's categorization comes first wherever one reaches\. .*\n",
            out)

    def test_a_person_first_is_counted_not_listed(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        ledger.categorize_ok(transaction, "Travel")
        out = ledger.preview_ok("Food", "cafe")
        assert "A person's categorization comes first on 1." in out
        assert "Changes: 0\n" in out

    def test_a_disagreement_it_would_cause(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        travel = ledger.add_rule_ok("Travel", "cafe")
        out = ledger.preview_ok("Food", "synthetic")
        assert re.search(rf"Travel by rules now, uncategorized, rules disagree: .*{travel}.* after",
                         out)

    def test_an_agreeing_rule_changes_nothing(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        out = ledger.preview_ok("Food", "synthetic")
        assert "Unchanged by other rules: 1." in out and "Changes: 0\n" in out

    def test_a_text_holding_control_characters_is_escaped(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        out = ledger.preview_ok("Food", "caf\x1b[2Je")
        assert "\x1b" not in out and "caf\\x1b[2Je" in out

    def test_the_token_is_the_same_in_another_ledger_with_equal_evidence(self, tmp_path, capsys):
        tokens = []
        for name in ("one", "two"):
            (tmp_path / name).mkdir()
            ledger = RuleLedger(tmp_path / name, capsys)
            bought(ledger, "a.csv", CAFE_ROW)
            tokens.append(ledger.preview_revision("Food", "cafe"))
        assert tokens[0] == tokens[1]


class TestPrecedence:  # RA4
    def test_a_person_s_categorization_comes_first(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]
        categorization = ledger.categorize_ok(transaction, "Travel")
        assert ledger.rule_outcomes() == []
        assert ledger.undo_categorization(categorization)[0] == 0
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_even_when_the_person_s_is_unsettled(self, ledger):
        # Two categorizations that disagree once the separation joining them is undone.
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        ledger.spend(holding(ledger, "a.csv"), "Food")
        ledger.spend(holding(ledger, "b.csv"), "Travel")
        ledger.add_rule_ok("Health", "synthetic")
        assert ledger.undo(separation)[0] == 0
        assert ledger.category_outcomes()[0][1] == "conflict"
        assert ledger.rule_outcomes() == []

    def test_agreeing_rules_apply(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        ledger.add_rule_ok("Food", "synthetic")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_disagreeing_rules_leave_it_uncategorized_naming_both(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        food = ledger.add_rule_ok("Food", "cafe")
        travel = ledger.add_rule_ok("Travel", "synthetic")
        assert ledger.rule_outcomes() == [(("a.csv",), "rule_conflict", None)]
        for rule in (food, travel):
            assert "Disagrees with another rule, so none applies, on: 1" in ledger.rule_show(rule)

    def test_a_subcategory_and_its_parent_disagree(self, ledger):
        assert ledger.run("category", "add", "Coffee", "--parent", "Food")[0] == 0
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "synthetic")
        ledger.add_rule_ok("Coffee", "cafe")
        assert ledger.rule_outcomes() == [(("a.csv",), "rule_conflict", None)]

    def test_unclassified_and_non_spending_are_never_reached(self, ledger):
        ledger.card("a.csv", CAFE_ROW)
        bought(ledger, "b.csv", "01/12/2026,SYNTHETIC CAFE PAY,,4.00", financial_type="income")
        bought(ledger, "c.csv", CAFE_ROW, financial_type="transfer")
        ledger.add_rule_ok("Food", "cafe")
        assert ledger.rule_outcomes() == []

    def test_a_type_change_takes_it_out_of_reach(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        classification = re.search(r"Classification (\S+):",
                                   ledger.run("review", "classifications")[1])[1]
        ledger.classify_ok(transaction, "transfer", supersedes=classification)
        assert ledger.rule_outcomes() == []


class TestNewEvidence:  # RA5
    def test_a_later_import_is_reached(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        bought(ledger, "b.csv", "01/20/2026,SYNTHETIC CAFE,3.00,")
        assert ledger.rule_outcomes() == [(("a.csv",), "applied", "Food"),
                                          (("b.csv",), "applied", "Food")]

    def test_a_repeat_import_changes_nothing(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe")
        before = ledger.everything()
        ledger.load_path(ledger.folder / "a.csv")
        assert ledger.everything() == before

    def test_a_merge_is_evaluated_as_one_transaction(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.add_rule_ok("Food", "synthetic")
        ledger.checking("b.csv", ID_ROW)
        assert ledger.count() == 1
        assert ledger.rule_outcomes() == [(("a.csv", "b.csv"), "applied", "Food")]

    def test_a_confirmation_and_a_separation_never_refuse_for_a_rule(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        ledger.classify_ok(two, "purchase")
        ledger.add_rule_ok("Food", "synthetic")
        (item,) = ledger.items()
        merged = confirm_ok(ledger, item, (one, two))
        assert ledger.rule_outcomes() == [(("a.csv", "b.csv"), "applied", "Food")]
        assert merged

    def test_the_outcome_equals_a_ledger_where_the_rule_came_last(self, tmp_path, capsys):
        found = []
        for name, rule_first in (("first", True), ("last", False)):
            (tmp_path / name).mkdir()
            ledger = RuleLedger(tmp_path / name, capsys)
            if rule_first:
                ledger.add_rule_ok("Food", "cafe")
            bought(ledger, "a.csv", CAFE_ROW)
            bought(ledger, "b.csv", SHOP_ROW)
            if not rule_first:
                ledger.add_rule_ok("Food", "cafe")
            found.append(ledger.rule_outcomes())
        assert found[0] == found[1] == [(("a.csv",), "applied", "Food")]


class TestListAndShow:  # RA5
    def test_rules_lists_each_with_its_reach(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        bought(ledger, "b.csv", "01/11/2026,SYNTHETIC CAFE,1.00,")
        ledger.categorize_ok(transaction, "Travel")
        rule = ledger.add_rule_ok("Food", "cafe")
        code, out, err = ledger.run("category", "rules")
        assert (code, err) == (0, "")
        assert re.fullmatch(
            rf"Category rule {rule}: active, spending whose description contains 'cafe', in "
            r"every account, any spending type, any date, takes Food, \S+\. Categorizes 1, "
            r"disagrees on 0, a person first on 1\nCategory rules: 1\n"
            r"To see where a rule reaches, run category rule show\.\n", out)

    def test_show_lists_the_transactions_by_how_it_reaches_them(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        other = bought(ledger, "b.csv", "01/11/2026,SYNTHETIC CAFE,1.00,")
        ledger.categorize_ok(transaction, "Travel")
        rule = ledger.add_rule_ok("Food", "cafe")
        out = ledger.rule_show(rule)
        assert f"Categorizes: 1\n  Transaction {other}: A, 2026-01-11, -1.00, SYNTHETIC CAFE\n" in out
        assert (f"A person's categorization comes first on: 1\n  Transaction {transaction}: A, "
                "2026-01-10, -6.50, SYNTHETIC CAFE\n") in out

    def test_an_unknown_rule(self, ledger):
        code, out, err = ledger.run("category", "rule", "show", "no-such")
        assert (code, out) == (2, "") and "category rule not found" in err

    def test_an_account_lists_only_rules_that_can_reach_it(self, ledger):
        ledger.add_account("B", "credit_card")
        bought(ledger, "a.csv", CAFE_ROW)
        ledger.add_rule_ok("Food", "cafe", account="A")
        ledger.add_rule_ok("Travel", "cafe", account="B")
        out = ledger.run("category", "rules", "--account", "B")[1]
        assert "Category rules: 1\n" in out and "takes Travel" in out


VERSION_20_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES)
SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("review", "categorizations"), ("review", "classifications")]


def shown_now(ledger):
    words_to_run = [*SHOWN_BEFORE_AND_AFTER,
                    ("review", "transaction", "show", holding(ledger, "a.csv"))]
    return [ledger.run(*words) for words in words_to_run]


@pytest.fixture
def populated(tmp_path, capsys):
    """Card A holding a categorized purchase, set back to 20, with what was shown before."""
    ledger = RuleLedger(tmp_path, capsys)
    ledger.spend(single(ledger))
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    for table in CATEGORY_RULE_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 20")
    conn.close()
    return ledger




class TestMigration:  # RA1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_20_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty", 20)) == 20
        conn.close()
        assert populated.run("migrate")[0] == 0
        conn = connect(populated.path)
        assert schema_version(conn) == 21
        for table in CATEGORY_RULE_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_20_TABLES) == before
        assert markers(populated) == ["A"]
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_20_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("category", "rules")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("category", "rules")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 21)
        newest = load_migrations()[20].path
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_20_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 20
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CATEGORY_RULE_TABLES)
        conn.close()
        assert populated.dump(VERSION_20_TABLES) == before


@pytest.fixture
def history(ledger):
    """Two rules, one with an event of each kind once undone by hand."""
    bought(ledger, "a.csv", CAFE_ROW)
    ledger.add_rule_ok("Food", "cafe")
    ledger.add_rule_ok("Travel", "shop")
    conn = ledger.conn()
    (rule,) = conn.execute("SELECT id FROM category_rule ORDER BY created_at LIMIT 1").fetchone()
    conn.execute("INSERT INTO category_rule_event (rule_id, event) VALUES (?, 'undone')", (rule,))
    conn.close()
    return ledger


class TestAppendOnly:  # RA1
    @pytest.mark.parametrize("statement", [
        "UPDATE category_rule SET category_id = category_id",
        "DELETE FROM category_rule",
        "INSERT INTO category_rule SELECT * FROM category_rule",
        "UPDATE category_rule_event SET event = event",
        "DELETE FROM category_rule_event",
        "INSERT INTO category_rule_event (rule_id, event) SELECT rule_id, event "
        "FROM category_rule_event",
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
        conn.execute("""INSERT INTO category_rule (id, category_id, description_contains,
                                                   normalization_version)
                        VALUES ('new', 1, 'x', 1)""")
        conn.execute("INSERT INTO category_rule_event (rule_id, event) VALUES ('new', 'made')")
        conn.close()

    @pytest.mark.parametrize(("column", "value"), [
        ("description_contains", "' '"), ("normalization_version", "0"),
        ("financial_type", "'income'"), ("from_date", "'2026-02-30'"),
    ])
    def test_a_rule_s_checks(self, history, column, value):
        conn = history.conn()
        values = {"description_contains": "'x'", "normalization_version": "1",
                  "financial_type": "NULL", "from_date": "NULL", column: value}
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                f"""INSERT INTO category_rule (id, category_id, description_contains,
                                               normalization_version, financial_type, from_date)
                    VALUES ('new', 1, {values['description_contains']},
                            {values['normalization_version']}, {values['financial_type']},
                            {values['from_date']})""")
        conn.close()

    def test_a_derived_row_holds_a_category_only_while_applied(self, history):
        conn = history.conn()
        (transaction,) = conn.execute("SELECT id FROM ledger_transaction").fetchone()
        conn.execute("DELETE FROM transaction_rule_category")
        for state, category in (("applied", None), ("rule_conflict", 1), ("conflict", None)):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute("INSERT INTO transaction_rule_category VALUES (?, ?, ?)",
                             (transaction, state, category))
        conn.execute("INSERT INTO transaction_rule_category VALUES (?, 'rule_conflict', NULL)",
                     (transaction,))
        conn.close()


def every_token(ledger, item, transaction, decision, correction, categorization):
    return (ledger.revision(item), ledger.transaction_revision(transaction),
            ledger.decision_revision(decision), ledger.correction_revision(correction),
            ledger.categorization_revision(categorization))


@pytest.fixture
def decided(ledger):
    """A rejected pair, the first a corrected and categorized purchase, the second a purchase, and
    an open item beside them."""
    item, one, two = pair_up(ledger)
    decision = ledger.reject_ok(item, (one, two))
    ledger.classify_ok(one, "purchase")
    ledger.classify_ok(two, "purchase")
    correction = ledger.correct_ok(one, "posting_date", "2026-01-11")
    categorization = ledger.categorize_ok(one, "Food")
    ledger.card("c.csv", "01/10/2026,SYNTHETIC CAFE,6.50,")
    (open_item,) = ledger.items()
    return open_item, two, decision, correction, categorization


class TestTokens:  # RA6
    def test_a_rule_reaching_nothing_changes_no_token(self, ledger, decided):
        before = every_token(ledger, *decided)
        ledger.add_rule_ok("Food", "nothing like it")
        assert every_token(ledger, *decided) == before

    def test_a_rule_reaching_them_changes_each(self, ledger, decided):
        before = every_token(ledger, *decided)
        ledger.add_rule_ok("Travel", "cafe")
        after = every_token(ledger, *decided)
        assert all(changed != unchanged for changed, unchanged in zip(after, before))

    def test_the_item_token_changes_when_its_transaction_is_reached(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        (item,) = ledger.items()
        before = ledger.revision(item)
        ledger.add_rule_ok("Food", "synthetic")
        assert ledger.revision(item) != before

    def test_another_ledger_with_equal_evidence_gives_equal_tokens(self, tmp_path, capsys):
        tokens = []
        for name in ("one", "two"):
            (tmp_path / name).mkdir()
            ledger = RuleLedger(tmp_path / name, capsys)
            transaction = bought(ledger, "a.csv", CAFE_ROW)
            ledger.add_rule_ok("Food", "cafe")
            tokens.append(ledger.transaction_revision(transaction))
        assert tokens[0] == tokens[1]

    def test_the_versions_and_the_preview_token_are_pinned(self, ledger):
        """Computed for this ledger when M10.1 was built, as a regression pin."""
        assert category_rule_evidence.PREVIEW_REVISION_VERSION == 1
        ledger.card("a.csv", CAFE_ROW)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        assert ledger.preview_revision("Food", "cafe") == PINNED_PREVIEW_REVISION


PINNED_PREVIEW_REVISION = "p1-d06ee505532f0efd"



class TestUndo:  # RB1, RB2
    def refused(self, ledger, message, rule, revision):
        before = ledger.everything()
        code, out, err = ledger.undo_rule(rule, revision)
        assert (code, out) == (2, "") and err == f"Error: {message}\n"
        assert ledger.everything() == before

    def test_show_previews_it_and_undo_does_it(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        out = ledger.rule_show(rule)
        assert re.search(r"  Revision: q1-[0-9a-f]{16}\nUndoing this rule now:\nChanges: 1\n"
                         rf"  Transaction {transaction}: A, 2026-01-10, -6\.50, SYNTHETIC CAFE: "
                         r"Food by rules now, uncategorized after\n", out)
        out = ledger.undo_rule_ok(rule)
        assert out.startswith(f"Category rule {rule} undone: changed 1 transactions. It stays on "
                              "record.\n  This re-derives from the evidence held now")
        assert ledger.rule_outcomes() == []
        shown = ledger.rule_show(rule)
        assert "Status: undone" in shown and "Undone: " in shown and "Revision" not in shown
        assert f"Category rule {rule}: undone," in ledger.run("category", "rules")[1]

    def test_it_equals_a_ledger_where_the_rule_was_never_added(self, tmp_path, capsys):
        found = []
        for name, with_undone in (("undone", True), ("never", False)):
            (tmp_path / name).mkdir()
            ledger = RuleLedger(tmp_path / name, capsys)
            bought(ledger, "a.csv", CAFE_ROW)
            bought(ledger, "b.csv", SHOP_ROW)
            ledger.add_rule_ok("Travel", "synthetic")
            if with_undone:
                rule = ledger.add_rule_ok("Food", "cafe")
                assert ledger.rule_outcomes()[0][1] == "rule_conflict"
                ledger.undo_rule_ok(rule)
            found.append((ledger.rule_outcomes(), ledger.run("totals")[1]))
        assert found[0] == found[1]
        assert found[0][0] == [(("a.csv",), "applied", "Travel"), (("b.csv",), "applied", "Travel")]

    def test_a_person_s_categorization_is_unchanged(self, ledger):
        transaction = bought(ledger, "a.csv", CAFE_ROW)
        categorization = ledger.categorize_ok(transaction, "Travel")
        rule = ledger.add_rule_ok("Food", "cafe")
        before = ledger.category_outcomes()
        assert "Changes: 0\n" in ledger.rule_show(rule)
        ledger.undo_rule_ok(rule)
        assert ledger.category_outcomes() == before
        assert ledger.categorization_state(categorization) == "active"

    def test_it_reaches_transactions_imported_since(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        bought(ledger, "b.csv", "01/20/2026,SYNTHETIC CAFE,3.00,")
        assert "Changes: 2\n" in ledger.rule_show(rule)
        assert "changed 2 transactions" in ledger.undo_rule_ok(rule)
        assert ledger.rule_outcomes() == []

    def test_a_stale_token(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        self.refused(ledger, STALE_RULE_REVISION, rule, "q1-0000000000000000")

    def test_a_token_made_before_an_import(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        token = ledger.rule_revision(rule)
        bought(ledger, "b.csv", "01/20/2026,SYNTHETIC CAFE,3.00,")
        self.refused(ledger, STALE_RULE_REVISION, rule, token)

    def test_an_undone_rule(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        token = ledger.rule_revision(rule)
        ledger.undo_rule_ok(rule, revision=token)
        self.refused(ledger, RULE_NOT_ACTIVE, rule, token)

    def test_an_unknown_rule(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        self.refused(ledger, RULE_NOT_FOUND, "no-such", "q1-0000000000000000")

    def test_a_stale_account_is_checked_before_the_token(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        assert "undo will be refused until it is" in ledger.rule_show(rule)
        self.refused(ledger, STALE_ACCOUNT, rule, "q1-0000000000000000")

    def test_adding_it_again_after_undo(self, ledger):
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        ledger.undo_rule_ok(rule)
        again = ledger.add_rule_ok("Food", "cafe")
        assert again != rule and ledger.rule_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_the_undo_token_is_pinned(self, ledger):
        """Computed for this ledger when M10.2 was built, as a regression pin."""
        assert category_rule_evidence.RULE_UNDO_REVISION_VERSION == 1
        bought(ledger, "a.csv", CAFE_ROW)
        rule = ledger.add_rule_ok("Food", "cafe")
        assert ledger.rule_revision(rule) == PINNED_UNDO_REVISION


PINNED_UNDO_REVISION = "q1-2a5a190106cbe279"
