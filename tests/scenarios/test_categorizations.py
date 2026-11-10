"""Categories stated by a person on spending, end to end, using synthetic data only (CB1 to CB6,
D-063)."""

import re
import sqlite3

import pytest
from test_classifications import ClassificationLedger, single
from test_confirmations import confirm, confirm_ok
from test_decisions import (
    ALL_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_TABLES,
    pair_up,
)
from test_separations import ID_ROW, merged_three, merged_two
from test_resolutions import CAFE_NO_AMOUNT
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.reconcile.categorizations import (
    ALREADY_CATEGORIZED,
    CATEGORIZATION_NOT_ACTIVE,
    CATEGORIZATION_NOT_FOUND,
    CATEGORIZATION_SUPERSEDED,
    CATEGORIZATION_SUPERSEDED_IN_CHAIN,
    CATEGORIZATION_SUPERSEDES_NOT_HERE,
    CATEGORIZATION_WRONG_ACCOUNT,
    CATEGORY_UNCHANGED,
    CATEGORY_UNKNOWN,
    CATEGORY_UNSETTLED,
    NOT_SPENDING_REFUSED,
    STALE_CATEGORIZATION_REVISION,
)
from personal_finance.reconcile.decisions import (
    LEAVES_CATEGORIZATION_UNSETTLED,
    LEAVES_CLASSIFICATION_UNSETTLED,
    STALE_ACCOUNT,
    STALE_DECISION_REVISION,
)
from personal_finance.reconcile.record_resolutions import COMPLETION_BOUND
from personal_finance.reconcile.statements import (
    STALE_TRANSACTION_REVISION,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reports import categorization_evidence, review_evidence
from personal_finance.reports import correction_evidence, decision_evidence

LEDGER_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES)


class CategoryLedger(ClassificationLedger):
    def categorize(self, transaction, category, revision=None, account="A", supersedes=None,
                   supersedes_revision=None):
        words = ["review", "categorize", transaction, "--account", account,
                 "--revision", revision or self.transaction_revision(transaction),
                 "--category", category]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.categorization_revision(supersedes)]
        return self.run(*words)

    def categorize_ok(self, transaction, category, **options):
        code, out, err = self.categorize(transaction, category, **options)
        assert code == 0, err
        return re.search(r"Categorization (\S+) recorded", out)[1]

    def spend(self, transaction, category="Food", financial_type="purchase"):
        """Classify a transaction, then categorize it."""
        self.classify_ok(transaction, financial_type)
        return self.categorize_ok(transaction, category)

    def categorization_show(self, categorization):
        code, out, err = self.run("review", "categorization", "show", categorization)
        assert code == 0, err
        return out

    def categorization_revision(self, categorization):
        return re.search(r"Revision: (g1-[0-9a-f]{16})",
                         self.categorization_show(categorization))[1]

    def categorization_state(self, categorization):
        return re.search(r"Status: (\S+)", self.categorization_show(categorization))[1]

    def undo_categorization(self, categorization, revision=None, account="A"):
        return self.run("review", "categorization", "undo", categorization, "--account", account,
                        "--revision", revision or self.categorization_revision(categorization))

    def category_outcomes(self):
        """Each categorized transaction as its file names, its state and its category's name."""
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
                   FROM transaction_category derived
                   LEFT JOIN category ON category.id = derived.category_id"""
            )
        )
        conn.close()
        return found

    def everything(self):
        return self.dump(LEDGER_TABLES)


@pytest.fixture
def ledger(tmp_path, capsys):
    return CategoryLedger(tmp_path, capsys)


def purchase(ledger, row=None):
    """One card row in a.csv, classified as a purchase."""
    transaction = single(ledger) if row is None else single(ledger, row)
    ledger.classify_ok(transaction, "purchase")
    return transaction


class TestCategorize:  # CB1, CB2
    def test_it_binds_every_record_and_applies(self, ledger):
        transaction = purchase(ledger)
        code, out, err = ledger.categorize(transaction, "Food")
        assert (code, err) == (0, "")
        assert re.fullmatch(
            rf"Categorization \S+ recorded: transaction {transaction} is in Food, binding 1 "
            r"records\.\n  Totals list spending by category\. .*\n", out)
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_a_merged_transaction_binds_every_record(self, ledger):
        transaction, _ = merged_three(ledger)
        ledger.classify_ok(transaction, "purchase")
        categorization = ledger.categorize_ok(transaction, "Food")
        bound = ledger.categorization_show(categorization).split("Bound records:\n")[1]
        assert all(f"{name} row" in bound for name in ("a.csv", "b.csv", "c.csv"))

    @pytest.mark.parametrize("financial_type", ["purchase", "fee", "interest"])
    def test_each_spending_type_money_out_takes_one(self, ledger, financial_type):
        ledger.spend(single(ledger), financial_type=financial_type)

    def test_a_refund_takes_one(self, ledger):
        ledger.spend(single(ledger, "01/12/2026,SYNTHETIC CAFE,,4.00"), financial_type="refund")

    def test_a_subcategory_takes_one(self, ledger):
        assert ledger.run("category", "add", "Groceries", "--parent", "Food")[0] == 0
        ledger.spend(single(ledger), "Groceries")
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Groceries")]


class TestRefusals:  # CB1
    def refused(self, ledger, message, *arguments, **options):
        before = ledger.everything()
        code, out, err = ledger.categorize(*arguments, **options)
        assert (code, out) == (2, "") and err == f"Error: {message}\n"
        assert ledger.everything() == before

    def test_an_unclassified_transaction(self, ledger):
        self.refused(ledger, NOT_SPENDING_REFUSED, single(ledger), "Food")

    @pytest.mark.parametrize("financial_type", ["income", "transfer"])
    def test_a_type_that_is_not_spending(self, ledger, financial_type):
        row = "01/12/2026,SYNTHETIC PAY,,4.00" if financial_type == "income" else None
        transaction = single(ledger) if row is None else single(ledger, row)
        ledger.classify_ok(transaction, financial_type)
        self.refused(ledger, NOT_SPENDING_REFUSED, transaction, "Food")

    @pytest.mark.parametrize("category", ["Nothing like it", "food", "uncategorized", ""])
    def test_an_unknown_category(self, ledger, category):
        self.refused(ledger, CATEGORY_UNKNOWN, purchase(ledger), category)

    def test_another_account_s_transaction(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.card("b.csv", "01/09/2026,SYNTHETIC SHOP,9.00,", account="B")
        transaction = holding(ledger, "b.csv")
        ledger.classify_ok(transaction, "purchase", account="B")
        purchase(ledger)
        self.refused(ledger, TRANSACTION_WRONG_ACCOUNT, transaction, "Food",
                     revision=ledger.transaction_revision(transaction))

    def test_an_unknown_transaction(self, ledger):
        purchase(ledger)
        self.refused(ledger, TRANSACTION_NOT_FOUND, "no-such-transaction", "Food",
                     revision="t8-0000000000000000")

    def test_a_stale_token_and_one_of_the_last_version(self, ledger):
        transaction = purchase(ledger)
        current = ledger.transaction_revision(transaction)
        self.refused(ledger, STALE_TRANSACTION_REVISION, transaction, "Food",
                     revision="t8-0000000000000000")
        self.refused(ledger, STALE_TRANSACTION_REVISION, transaction, "Food",
                     revision="t7-" + current.split("-")[1])

    def test_a_category_it_already_has(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        self.refused(ledger, CATEGORY_UNCHANGED, transaction, "Food", supersedes=categorization)

    def test_a_categorized_transaction_without_supersedes(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        self.refused(ledger, ALREADY_CATEGORIZED.format(categorization=categorization),
                     transaction, "Travel")

    def test_superseding_one_applying_elsewhere(self, ledger):
        transaction = purchase(ledger)
        ledger.card("b.csv", "01/20/2026,SYNTHETIC SHOP,9.00,")
        other = holding(ledger, "b.csv")
        ledger.classify_ok(other, "purchase")
        elsewhere = ledger.categorize_ok(other, "Food")
        self.refused(ledger, CATEGORIZATION_SUPERSEDES_NOT_HERE, transaction, "Travel",
                     supersedes=elsewhere)

    def test_superseding_an_undone_one(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        token = ledger.categorization_revision(categorization)
        assert ledger.undo_categorization(categorization, token)[0] == 0
        self.refused(ledger, CATEGORIZATION_NOT_ACTIVE, transaction, "Travel",
                     supersedes=categorization, supersedes_revision=token)

    def test_a_stale_categorization_token(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        self.refused(ledger, STALE_CATEGORIZATION_REVISION, transaction, "Travel",
                     supersedes=categorization, supersedes_revision="g1-0000000000000000")

    def test_an_unknown_categorization(self, ledger):
        transaction = purchase(ledger)
        self.refused(ledger, CATEGORIZATION_NOT_FOUND, transaction, "Travel",
                     supersedes="no-such", supersedes_revision="g1-0000000000000000")

    def test_another_account_s_categorization(self, ledger):
        ledger.add_account("B", "credit_card")
        ledger.card("b.csv", "01/09/2026,SYNTHETIC SHOP,9.00,", account="B")
        other = holding(ledger, "b.csv")
        ledger.classify_ok(other, "purchase", account="B")
        theirs = ledger.categorize_ok(other, "Food", account="B")
        before = ledger.everything()
        code, _, err = ledger.undo_categorization(theirs, account="A")
        assert code == 2 and CATEGORIZATION_WRONG_ACCOUNT in err
        assert ledger.everything() == before

    def test_the_account_is_checked_first(self, ledger):
        transaction = purchase(ledger)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        self.refused(ledger, STALE_ACCOUNT, transaction, "No such category",
                     revision="t8-0000000000000000")


class TestStaleAccount:  # CB1
    def test_categorize_and_undo_are_refused_and_nothing_is_reconciled(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        token = ledger.categorization_revision(categorization)
        revision = ledger.transaction_revision(transaction)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        before = ledger.everything()
        for code, _, err in (
            ledger.categorize(transaction, "Travel", revision=revision,
                              supersedes=categorization, supersedes_revision=token),
            ledger.undo_categorization(categorization, token),
        ):
            assert code == 2 and STALE_ACCOUNT in err
        assert ledger.everything() == before
        assert "undo will be refused until it is" in ledger.categorization_show(categorization)


class TestSurvival:  # CB2
    def categorized(self, ledger):
        ledger.spend(single(ledger))
        return ledger.category_outcomes()

    def test_a_repeat_import(self, ledger):
        outcomes = self.categorized(ledger)
        ledger.load_path(ledger.folder / "a.csv")
        assert ledger.category_outcomes() == outcomes

    def test_reconcile(self, ledger):
        outcomes = self.categorized(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.category_outcomes() == outcomes

    def test_an_unrelated_file(self, ledger):
        outcomes = self.categorized(ledger)
        ledger.card("other.csv", "01/20/2026,SYNTHETIC SHOP,9.00,")
        assert ledger.category_outcomes() == outcomes

    def test_a_re_export_that_merges_keeps_it_applied_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        categorization = ledger.spend(holding(ledger, "a.csv"))
        ledger.checking("b.csv", ID_ROW)
        assert ledger.count() == 1
        assert ledger.category_outcomes() == [(("a.csv", "b.csv"), "applied", "Food")]
        bound = ledger.categorization_show(categorization).split("Bound records:\n")[1]
        bound = bound.split("  Revision:")[0]
        assert "a.csv row 1" in bound and "b.csv" not in bound


def disagreeing_after_undo(ledger):
    """a and b merged, separated, each a purchase but in two categories, and merged again by
    undoing the separation."""
    transaction, records = merged_two(ledger)
    separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
    food = ledger.spend(holding(ledger, "a.csv"), "Food")
    travel = ledger.spend(holding(ledger, "b.csv"), "Travel")
    code, _, err = ledger.undo(separation)
    assert code == 0, err
    return food, travel


class TestSeveral:  # CB2
    def test_agreeing_categorizations_apply_once(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.spend(one)
        ledger.spend(two)
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.category_outcomes() == [(("a.csv", "b.csv"), "applied", "Food")]

    def test_disagreeing_ones_leave_it_uncategorized_and_disclosed(self, ledger):
        disagreeing_after_undo(ledger)
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        assert ledger.category_outcomes() == [(("a.csv", "b.csv"), "conflict", None)]
        listed = ledger.run("review", "categorizations")[1]
        assert re.search(r"^Transaction \S+: categorizations disagree", listed, re.MULTILINE)
        transaction = holding(ledger, "a.csv")
        assert "Category: categorizations disagree" in ledger.transaction_show(transaction)

    def test_a_disagreement_refuses_categorizing_until_settled(self, ledger):
        food, travel = disagreeing_after_undo(ledger)
        transaction = holding(ledger, "a.csv")
        before = ledger.everything()
        code, _, err = ledger.categorize(transaction, "Other")
        assert code == 2 and err == "Error: " + CATEGORY_UNSETTLED.format(
            categorizations=", ".join(sorted((food, travel)))) + "\n"
        assert ledger.everything() == before
        code, out, _ = ledger.undo_categorization(travel)
        assert code == 0 and "now uncategorized" not in out
        assert ledger.category_outcomes() == [(("a.csv", "b.csv"), "applied", "Food")]

    def test_an_automatic_split_leaves_every_part_uncategorized(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (transaction,) = ledger.merges()
        categorization = ledger.spend(transaction)
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        assert ledger.category_outcomes() == [(("a.csv",), "basis_changed", None),
                                              (("b.csv",), "basis_changed", None)]
        out = ledger.categorization_show(categorization)
        assert out.count("uncategorized, basis changed now, uncategorized after") == 2


class TestNotSpending:  # CB2
    def test_a_type_that_leaves_spending(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        categorization = ledger.categorize_ok(transaction, "Food")
        ledger.classify_ok(transaction, "transfer", supersedes=classification)
        assert ledger.category_outcomes() == [(("a.csv",), "not_spending", None)]
        assert ledger.categorization_state(categorization) == "active"
        assert "Category: it is no longer spending" in ledger.transaction_show(transaction)
        listed = ledger.run("review", "categorizations")[1]
        assert re.search(r"^Transaction \S+: it is no longer spending", listed, re.MULTILINE)

    def test_categorizing_again_refuses_until_it_is_undone(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        categorization = ledger.categorize_ok(transaction, "Food")
        ledger.classify_ok(transaction, "transfer", supersedes=classification)
        before = ledger.everything()
        code, _, err = ledger.categorize(transaction, "Travel")
        assert (code, err) == (2, "Error: " + CATEGORY_UNSETTLED.format(
            categorizations=categorization) + "\n")
        assert ledger.everything() == before

    def test_undoing_its_type_and_restoring_it(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        ledger.categorize_ok(transaction, "Food")
        token = ledger.classification_revision(classification)
        assert ledger.undo_classification(classification, token)[0] == 0
        assert ledger.category_outcomes() == [(("a.csv",), "not_spending", None)]
        ledger.classify_ok(transaction, "fee")
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Food")]


class TestDecisionCommands:  # CB3
    def test_confirming_disagreeing_categorizations_refuses(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.spend(one, "Food")
        ledger.spend(two, "Travel")
        (item,) = ledger.items()
        before = ledger.everything()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and LEAVES_CATEGORIZATION_UNSETTLED in err
        assert ledger.everything() == before

    def test_separating_a_categorization_s_records_refuses(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        ledger.categorize_ok(transaction, "Food")
        records = ledger.records(transaction)
        before = ledger.everything()
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and LEAVES_CATEGORIZATION_UNSETTLED in err
        assert LEAVES_CLASSIFICATION_UNSETTLED not in err
        assert ledger.everything() == before

    def test_separating_records_a_categorization_does_not_bind_is_allowed(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.spend(holding(ledger, "a.csv"))
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Food")]

    def test_a_categorization_made_since_makes_the_undo_token_stale(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        ledger.classify_ok(two, "purchase")
        (item,) = ledger.items()
        decision = confirm_ok(ledger, item, (one, two))
        old = ledger.decision_revision(decision)
        ledger.categorize_ok(holding(ledger, "a.csv"), "Food")
        before = ledger.everything()
        code, _, err = ledger.undo(decision, old)
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.everything() == before
        assert ledger.undo(decision)[0] == 0
        assert ledger.category_outcomes() == [(("a.csv",), "basis_changed", None),
                                              (("b.csv",), "basis_changed", None)]


def chain_of_three(ledger):
    transaction = purchase(ledger)
    first = ledger.categorize_ok(transaction, "Food")
    second = ledger.categorize_ok(transaction, "Travel", supersedes=first)
    third = ledger.categorize_ok(transaction, "Other", supersedes=second)
    return transaction, first, second, third


class TestChains:  # CB3
    def test_only_the_newest_applies(self, ledger):
        _, first, second, third = chain_of_three(ledger)
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Other")]
        assert [ledger.categorization_state(c) for c in (first, second, third)] == [
            "superseded", "superseded", "active"]

    def test_undo_steps_back_one_link_at_a_time(self, ledger):
        _, first, second, third = chain_of_three(ledger)
        code, out, _ = ledger.undo_categorization(third)
        assert code == 0 and f"Categorization {second}, which it superseded, applies again" in out
        assert ledger.category_outcomes() == [(("a.csv",), "applied", "Travel")]
        assert ledger.undo_categorization(second)[0] == 0
        assert ledger.undo_categorization(first)[0] == 0
        assert ledger.category_outcomes() == []

    def test_a_superseded_one_names_the_newest_and_refuses(self, ledger):
        transaction, first, second, third = chain_of_three(ledger)
        out = ledger.categorization_show(first)
        assert f"Newest of its chain: categorization {third}" in out
        assert "Revision:" not in out
        before = ledger.everything()
        for code, _, err in (
            ledger.undo_categorization(first, "g1-0000000000000000"),
            ledger.categorize(transaction, "Health", supersedes=first,
                              supersedes_revision="g1-0000000000000000"),
        ):
            assert code == 2 and err == "Error: " + CATEGORIZATION_SUPERSEDED_IN_CHAIN.format(
                newer=second, newest=third) + "\n"
        code, _, err = ledger.undo_categorization(second, "g1-0000000000000000")
        assert code == 2 and CATEGORIZATION_SUPERSEDED.format(newer=third) in err
        assert ledger.everything() == before


class TestUndo:  # CB3
    def test_it_equals_a_ledger_built_without_it(self, tmp_path, capsys):
        (tmp_path / "with").mkdir()
        built = CategoryLedger(tmp_path / "with", capsys)
        transaction = purchase(built)
        categorization = built.categorize_ok(transaction, "Food")
        assert built.undo_categorization(categorization)[0] == 0
        (tmp_path / "without").mkdir()
        plain = CategoryLedger(tmp_path / "without", capsys)
        purchase(plain)
        assert built.totals() == plain.totals()
        assert built.category_outcomes() == plain.category_outcomes() == []
        assert built.transaction_revision(transaction) == plain.transaction_revision(
            holding(plain, "a.csv"))


class TestCompletions:  # CB3
    def test_undoing_a_completion_waits_for_its_categorization(self, ledger):
        ledger.card("u.csv", CAFE_NO_AMOUNT)
        (item,) = ledger.unresolved()
        resolution = ledger.complete_ok(item, amount="-6.50")
        transaction = holding(ledger, "u.csv")
        classification = ledger.classify_ok(transaction, "purchase")
        categorization = ledger.categorize_ok(transaction, "Food")
        assert ledger.undo_classification(classification)[0] == 0
        before = ledger.everything()
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2
        assert COMPLETION_BOUND.format(entries=f"categorization {categorization}") in err
        assert ledger.everything() == before
        assert f"Refused while categorization {categorization} binds the record" in \
            ledger.resolution_show(resolution)
        assert ledger.undo_categorization(categorization)[0] == 0
        assert ledger.undo_resolution(resolution)[0] == 0


class TestShown:  # CB4
    def test_an_item_and_a_transaction_show_categorizations_apart(self, ledger):
        item, one, two = pair_up(ledger)
        categorization = ledger.spend(one)
        out = ledger.show(item)
        assert f"  Categorizations:\n    Categorization {categorization}: Food, binding " in out
        assert "    Category: the stated category applies" in out
        assert out.count("Categorizations:") == 1
        assert f"Categorization {categorization}: Food" in ledger.transaction_show(one)
        assert "Categorizations:" not in ledger.transaction_show(two)

    def test_the_lists_and_show(self, ledger):
        transaction = purchase(ledger)
        categorization = ledger.categorize_ok(transaction, "Food")
        code, out, _ = ledger.run("review", "categorizations", "--account", "A")
        assert code == 0
        assert re.match(rf"Categorization {categorization}: active, Food, 1 records, A, \S+\n"
                        r"Categorizations: 1\nTo see what", out)
        shown = ledger.categorization_show(categorization)
        assert "  Category: Food\n  Status: active\n" in shown
        assert f"  Transaction {transaction}: categorized now, uncategorized after" in shown

    def test_names_are_escaped_everywhere(self, ledger):
        odd = "Odd\x1b[2J\nname‮"
        assert ledger.run("category", "add", odd)[0] == 0
        transaction = purchase(ledger)
        code, out, _ = ledger.categorize(transaction, odd)
        assert code == 0 and "is in Odd\\x1b[2J\\nname\\u202e, binding" in out
        categorization = re.search(r"Categorization (\S+) recorded", out)[1]
        escaped = "Odd\\x1b[2J\\nname\\u202e"
        for shown in (ledger.run("review", "categorizations")[1],
                      ledger.categorization_show(categorization),
                      ledger.transaction_show(transaction)):
            assert escaped in shown and odd not in shown and "\x1b" not in shown

    def test_routine_commands_show_no_amounts_or_descriptions(self, ledger):
        transaction = purchase(ledger)
        ledger.categorize_ok(transaction, "Food")
        for words in (("review", "categorizations"), ("category", "list")):
            out = ledger.run(*words)[1]
            assert "6.50" not in out and "CAFE" not in out


class TestTokens:  # CB5
    def test_the_versions_are_pinned(self):
        assert review_evidence.REVISION_VERSION == 10
        assert review_evidence.TRANSACTION_REVISION_VERSION == 8
        assert decision_evidence.DECISION_REVISION_VERSION == 7
        assert correction_evidence.CORRECTION_REVISION_VERSION == 3
        assert categorization_evidence.CATEGORIZATION_REVISION_VERSION == 1

    def test_categorizing_changes_its_tokens_and_undoing_restores_them(self, ledger):
        item, one, _ = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        (item,) = ledger.items()
        before = (ledger.transaction_revision(one), ledger.revision(item))
        categorization = ledger.categorize_ok(one, "Food")
        assert (ledger.transaction_revision(one), ledger.revision(item)) != before
        assert ledger.undo_categorization(categorization)[0] == 0
        assert (ledger.transaction_revision(one), ledger.revision(item)) == before

    def test_the_categorization_token_is_pinned(self, tmp_path, capsys):
        tokens = []
        for name in ("one", "two"):
            (tmp_path / name).mkdir()
            built = CategoryLedger(tmp_path / name, capsys)
            tokens.append(built.categorization_revision(built.spend(single(built))))
        assert tokens[0] == tokens[1]
        assert re.fullmatch(r"g1-[0-9a-f]{16}", tokens[0])

    def test_another_categorization_reaching_it_changes_it(self, ledger):
        _, records = merged_two(ledger)
        separation = ledger.separate_ok(holding(ledger, "a.csv"), [records["a.csv"]],
                                        [records["b.csv"]])
        food = ledger.spend(holding(ledger, "a.csv"))
        token = ledger.categorization_revision(food)
        ledger.spend(holding(ledger, "b.csv"), "Food")
        assert ledger.undo(separation)[0] == 0
        assert ledger.categorization_revision(food) != token

    def test_an_amount_correction_s_token_covers_its_categorization(self, ledger):
        transaction = purchase(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        token = ledger.correction_revision(correction)
        ledger.categorize_ok(transaction, "Food")
        assert ledger.correction_revision(correction) != token

    def test_a_description_correction_s_token_does_not(self, ledger):
        transaction = purchase(ledger)
        correction = ledger.correct_ok(transaction, "description", "SYNTHETIC OTHER")
        token = ledger.correction_revision(correction)
        ledger.categorize_ok(transaction, "Food")
        assert ledger.correction_revision(correction) == token


@pytest.fixture
def populated(tmp_path, capsys):
    """Card A holding a purchase, classified, with a category added, then set back to 19."""
    ledger = CategoryLedger(tmp_path, capsys)
    purchase(ledger)
    assert ledger.run("category", "add", "Groceries", "--parent", "Food")[0] == 0
    conn = connect(ledger.path)
    for table in CATEGORIZATION_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 19")
    conn.close()
    return ledger


VERSION_19_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES)


class TestMigration:  # CB6
    def test_it_adds_empty_tables_and_makes_no_account_stale(self, populated, tmp_path):
        before = populated.dump(VERSION_19_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty", 20)) == 20
        for table in CATEGORIZATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_19_TABLES) == before
        assert markers(populated) == ["A"]

    def test_categorizing_works_after_it(self, populated):
        assert populated.run("migrate")[0] == 0
        populated.categorize_ok(holding(populated, "a.csv"), "Groceries")
        assert populated.category_outcomes() == [(("a.csv",), "applied", "Groceries")]

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 20)
        twentieth = load_migrations()[19].path
        (folder / twentieth.name).write_text(twentieth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_19_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 19
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CATEGORIZATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_19_TABLES) == before


@pytest.fixture
def history(ledger):
    """A chain of three categorizations, the newest undone."""
    _, _, _, third = chain_of_three(ledger)
    assert ledger.undo_categorization(third)[0] == 0
    return ledger


class TestAppendOnly:  # CB6
    @pytest.mark.parametrize("statement", [
        "UPDATE category_assignment SET category_id = category_id",
        "DELETE FROM category_assignment",
        "INSERT INTO category_assignment SELECT * FROM category_assignment",
        "UPDATE category_assignment_record SET source_record_id = source_record_id",
        "DELETE FROM category_assignment_record",
        "INSERT INTO category_assignment_record SELECT * FROM category_assignment_record",
        "UPDATE category_assignment_event SET event = event",
        "DELETE FROM category_assignment_event",
        "INSERT INTO category_assignment_event (assignment_id, event) "
        "SELECT assignment_id, event FROM category_assignment_event",
    ])
    def test_history_refuses_change(self, history, statement):
        before = history.everything()
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.everything() == before

    def test_a_categorization_supersedes_only_its_own_account(self, history):
        history.add_account("B", "credit_card")
        conn = history.conn()
        (existing,) = conn.execute(
            "SELECT id FROM category_assignment ORDER BY created_at LIMIT 1").fetchone()
        insert = """INSERT INTO category_assignment (id, account_id, category_id,
                        target_transaction_id, target_revision, supersedes_assignment_id)
                    VALUES (?, ?, 1, 'x', 'y', ?)"""
        with pytest.raises(sqlite3.IntegrityError, match="one of its own account"):
            conn.execute(insert, ("new", history.account_id("B"), existing))
        conn.execute(insert, ("new", history.account_id("A"), existing))
        conn.close()

    def test_a_derived_row_holds_a_category_only_while_applied(self, history):
        conn = history.conn()
        (transaction,) = conn.execute("SELECT id FROM ledger_transaction").fetchone()
        conn.execute("DELETE FROM transaction_category")
        for state, category in (("applied", None), ("conflict", 1), ("not_spending", 1),
                                ("uncategorized", None)):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute("INSERT INTO transaction_category VALUES (?, ?, ?)",
                             (transaction, state, category))
        conn.execute("INSERT INTO transaction_category VALUES (?, 'not_spending', NULL)",
                     (transaction,))
        conn.close()
