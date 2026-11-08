"""Financial types stated by a person, end to end, using synthetic data only (D-053)."""

import re
from dataclasses import replace

import pytest
from test_confirmations import confirm, confirm_ok
from test_coverage_declarations import CoverageLedger, both_complete
from test_decisions import CAFE, OTHER, SOURCE_TABLES, pair_up
from test_resolutions import CAFE_NO_AMOUNT, blocked_pair
from test_separations import ID_ROW, merged_three, merged_two
from test_supersession import holding

from personal_finance.reconcile.apply import load_constraints, load_evidence, reconcile_account
from personal_finance.reconcile.classifications import (
    ALREADY_CLASSIFIED,
    CLASSIFICATION_NOT_ACTIVE,
    CLASSIFICATION_SUPERSEDED,
    CLASSIFICATION_SUPERSEDED_IN_CHAIN,
    CLASSIFICATION_WRONG_ACCOUNT,
    STALE_CLASSIFICATION_REVISION,
    STALE_TRANSACTION_REVISION,
    SUPERSEDES_NOT_HERE,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
    TYPE_AGAINST_DIRECTION,
    TYPE_UNCHANGED,
    TYPE_UNKNOWN,
    TYPE_UNSETTLED,
)
from personal_finance.reconcile.corrections import (
    AGAINST_CLASSIFIED_DIRECTION,
    STALE_CORRECTION_REVISION,
)
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.decisions import (
    LEAVES_CLASSIFICATION_UNSETTLED,
    STALE_ACCOUNT,
    STALE_DECISION_REVISION,
)
from personal_finance.reconcile.record_resolutions import COMPLETION_BOUND
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports import classification_evidence

CLASSIFICATION_TABLES = ("type_classification", "type_classification_record",
                         "type_classification_event", "transaction_classification")
REFUND = "01/12/2026,SYNTHETIC CAFE,,4.00"


class ClassificationLedger(CoverageLedger):
    def classify(self, transaction, financial_type, revision=None, account="A", supersedes=None,
                 supersedes_revision=None):
        words = ["review", "classify", transaction, "--account", account,
                 "--revision", revision or self.transaction_revision(transaction),
                 "--type", financial_type]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.classification_revision(supersedes)]
        return self.run(*words)

    def classify_ok(self, transaction, financial_type, **options):
        code, out, err = self.classify(transaction, financial_type, **options)
        assert code == 0, err
        return re.search(r"Classification (\S+) recorded", out)[1]

    def classification_show(self, classification):
        code, out, err = self.run("review", "classification", "show", classification)
        assert code == 0, err
        return out

    def classification_revision(self, classification):
        return re.search(r"Revision: (f1-[0-9a-f]{16})",
                         self.classification_show(classification))[1]

    def classification_state(self, classification):
        return re.search(r"Status: (\S+)", self.classification_show(classification))[1]

    def undo_classification(self, classification, revision=None, account="A"):
        return self.run("review", "classification", "undo", classification, "--account", account,
                        "--revision", revision or self.classification_revision(classification))

    def types(self):
        """The 'By financial type' lines of totals, as type, count and amount."""
        section = self.totals().split("By financial type, as you classified them:\n")[1]
        section = section.split("Disclosures:")[0]
        return re.findall(r"^  (\S+): (\d+) transactions, (\S+)$", section, re.MULTILINE)

    def outcomes(self):
        """Each classified transaction as its file names, its state and its type."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (tuple(sorted(names[transaction_id])), state, financial_type)
            for transaction_id, state, financial_type in conn.execute(
                "SELECT transaction_id, state, financial_type FROM transaction_classification"
            )
        )
        conn.close()
        return found

    def movement(self):
        return self.totals().split("By financial type")[0]


@pytest.fixture
def ledger(tmp_path, capsys):
    return ClassificationLedger(tmp_path, capsys)


def single(ledger, row=CAFE):
    """One card row in a.csv, 6.50 out by default."""
    ledger.card("a.csv", row)
    return holding(ledger, "a.csv")


class TestClassify:  # F1, F2, F3
    def test_every_transaction_is_unclassified_until_classified(self, ledger):  # F1
        ledger.card("a.csv", CAFE, OTHER)
        assert ledger.types() == [("unclassified", "2", "-15.50")]
        transaction = ledger.run("transactions")[1].split()[0]
        assert "Financial type: unclassified" in ledger.transaction_show(transaction)

    def test_a_purchase_moves_exactly_its_amount_and_nothing_else(self, ledger):  # F1, F2
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", OTHER)
        movement = ledger.movement()
        tables = (*SOURCE_TABLES, "ledger_transaction", "transaction_source")
        before = ledger.dump(tables)
        code, out, _ = ledger.classify(holding(ledger, "a.csv"), "purchase")
        assert code == 0 and "is a purchase, binding 1 records" in out
        assert ledger.types() == [("purchase", "1", "-6.50"), ("unclassified", "1", "-9.00")]
        assert ledger.movement() == movement
        assert ledger.dump(tables) == before
        assert ledger.outcomes() == [(("a.csv",), "applied", "purchase")]

    def test_a_merged_transaction_binds_every_record(self, ledger):
        transaction, _ = merged_two(ledger)
        code, out, _ = ledger.classify(transaction, "purchase")
        assert code == 0 and "binding 2 records" in out
        assert ledger.types() == [("purchase", "1", "-6.50"), ("unclassified", "0", "0.00")]

    def test_derivation_never_reads_a_classification(self, ledger):  # F3
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        conn = ledger.conn()
        account = ledger.account_id()
        before = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                        load_constraints(conn, account))
        conn.close()
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.classify_ok(holding(ledger, "b.csv"), "fee")
        conn = ledger.conn()
        after = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                       load_constraints(conn, account))
        conn.close()
        assert after == before

    @pytest.mark.parametrize("financial_type", ["refund", "income", "transfer"])
    def test_money_in_takes_types_of_money_in(self, ledger, financial_type):
        ledger.classify_ok(single(ledger, REFUND), financial_type)
        assert ledger.types()[0] == (financial_type, "1", "4.00")

    @pytest.mark.parametrize("financial_type", ["purchase", "fee", "interest", "transfer",
                                                "card_payment", "loan_payment",
                                                "investment_contribution"])
    def test_money_out_takes_types_of_money_out(self, ledger, financial_type):
        ledger.classify_ok(single(ledger), financial_type)
        assert ledger.types()[0] == (financial_type, "1", "-6.50")

    def test_totals_use_the_corrected_amount(self, ledger):
        transaction = single(ledger)
        ledger.classify_ok(transaction, "purchase")
        ledger.correct_ok(transaction, "amount", "-6.00")
        assert ledger.types()[0] == ("purchase", "1", "-6.00")

    def test_transaction_show_lists_classifications_apart(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        out = ledger.transaction_show(transaction)
        section = out.split("  Classifications:\n")[1]
        assert f"Classification {classification}: purchase, binding" in section
        assert "Financial type: the stated type applies" in section


class TestRefusals:  # F4
    def nothing_changes(self, ledger, attempt, message):
        before = ledger.dump()
        code, _, err = attempt()
        assert code == 2
        assert message in err
        assert ledger.dump() == before

    def test_wrong_account(self, ledger):
        transaction = single(ledger)
        ledger.add_account("B")
        self.nothing_changes(
            ledger, lambda: ledger.classify(transaction, "purchase", account="B"),
            TRANSACTION_WRONG_ACCOUNT,
        )

    def test_an_unknown_transaction(self, ledger):
        single(ledger)
        self.nothing_changes(
            ledger, lambda: ledger.classify("nope", "purchase", revision="t7-0"),
            TRANSACTION_NOT_FOUND,
        )

    def test_a_stale_token_and_one_of_the_last_version(self, ledger):
        transaction = single(ledger)
        last_version = "t5-" + ledger.transaction_revision(transaction)[3:]
        for token in ("t7-0000000000000000", last_version):
            self.nothing_changes(
                ledger, lambda: ledger.classify(transaction, "purchase", revision=token),
                STALE_TRANSACTION_REVISION,
            )

    @pytest.mark.parametrize("financial_type", ["unclassified", "groceries", "PURCHASE", ""])
    def test_an_unknown_type(self, ledger, financial_type):
        transaction = single(ledger)
        self.nothing_changes(ledger, lambda: ledger.classify(transaction, financial_type),
                             TYPE_UNKNOWN)

    @pytest.mark.parametrize(("row", "financial_type", "direction", "other"), [
        (CAFE, "refund", "in", "out"),
        (CAFE, "income", "in", "out"),
        (REFUND, "purchase", "out", "in"),
        (REFUND, "card_payment", "out", "in"),
    ])
    def test_a_type_against_the_direction(self, ledger, row, financial_type, direction, other):
        transaction = single(ledger, row)
        message = TYPE_AGAINST_DIRECTION.format(financial_type=financial_type,
                                                direction=direction, other=other)
        self.nothing_changes(ledger, lambda: ledger.classify(transaction, financial_type), message)

    @pytest.mark.parametrize(("account_type", "financial_type"), [
        ("checking", "loan_payment"),
        ("savings", "investment_contribution"),
        ("credit_card", "loan_payment"),
        ("loan", "card_payment"),
        ("investment", "card_payment"),
    ])
    def test_a_payment_received_on_an_account_it_does_not_pay(self, ledger, account_type,
                                                              financial_type):  # X8
        ledger.add_account("P", account_type)
        ledger.card("a.csv", REFUND, account="P")
        transaction = holding(ledger, "a.csv")
        message = TYPE_AGAINST_DIRECTION.format(financial_type=financial_type,
                                                direction="out", other="in")
        self.nothing_changes(
            ledger, lambda: ledger.classify(transaction, financial_type, account="P"), message)

    def test_a_type_it_already_has(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        self.nothing_changes(
            ledger,
            lambda: ledger.classify(transaction, "purchase", supersedes=classification),
            TYPE_UNCHANGED,
        )

    def test_a_classified_transaction_without_supersedes(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        self.nothing_changes(ledger, lambda: ledger.classify(transaction, "fee"),
                             ALREADY_CLASSIFIED.format(classification=classification))

    def test_superseding_one_applying_elsewhere(self, ledger):
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", OTHER)
        elsewhere = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        self.nothing_changes(
            ledger,
            lambda: ledger.classify(holding(ledger, "b.csv"), "fee", supersedes=elsewhere),
            SUPERSEDES_NOT_HERE,
        )

    def test_superseding_or_undoing_an_undone_classification(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        token = ledger.classification_revision(classification)
        assert ledger.undo_classification(classification, token)[0] == 0
        for attempt in (
            lambda: ledger.classify(transaction, "fee", supersedes=classification,
                                    supersedes_revision=token),
            lambda: ledger.undo_classification(classification, token),
        ):
            self.nothing_changes(ledger, attempt, CLASSIFICATION_NOT_ACTIVE)

    def test_a_stale_classification_token(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        for attempt in (
            lambda: ledger.classify(transaction, "fee", supersedes=classification,
                                    supersedes_revision="f1-0000000000000000"),
            lambda: ledger.undo_classification(classification, "f1-0000000000000000"),
        ):
            self.nothing_changes(ledger, attempt, STALE_CLASSIFICATION_REVISION)

    def test_another_account_s_classification(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        token = ledger.classification_revision(classification)
        ledger.add_account("B")
        self.nothing_changes(
            ledger, lambda: ledger.undo_classification(classification, token, account="B"),
            CLASSIFICATION_WRONG_ACCOUNT,
        )

    def test_superseding_an_unsettled_transaction(self, ledger):
        _, purchase, _ = disagreeing_after_undo(ledger)
        transaction = holding(ledger, "a.csv")
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "conflict", None)]
        for attempt in (lambda: ledger.classify(transaction, "fee", supersedes=purchase),
                        lambda: ledger.classify(transaction, "fee")):
            self.nothing_changes(ledger, attempt, TYPE_UNSETTLED.split("{")[0])

    def test_superseding_one_of_two_agreeing_classifications(self, ledger):
        item, one, two = pair_up(ledger)
        first = ledger.classify_ok(one, "purchase")
        ledger.classify_ok(two, "purchase")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        self.nothing_changes(
            ledger, lambda: ledger.classify(holding(ledger, "a.csv"), "fee", supersedes=first),
            TYPE_UNSETTLED.split("{")[0],
        )

    def test_superseding_one_against_its_direction(self, ledger):
        transaction, refund = against_its_direction(ledger)
        assert "its amount now runs against the stated type" in ledger.transaction_show(transaction)
        for attempt in (lambda: ledger.classify(transaction, "purchase", supersedes=refund),
                        lambda: ledger.classify(transaction, "purchase")):
            self.nothing_changes(ledger, attempt, TYPE_UNSETTLED.split("{")[0])

    def test_supersedes_needs_its_revision(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        code, _, err = ledger.run(
            "review", "classify", transaction, "--account", "A",
            "--revision", ledger.transaction_revision(transaction), "--type", "fee",
            "--supersedes", classification,
        )
        assert code == 2 and "must be given together" in err


class TestReceivingAccount:  # X8
    @pytest.mark.parametrize(("account_type", "financial_type"), [
        ("credit_card", "card_payment"),
        ("loan", "loan_payment"),
        ("investment", "investment_contribution"),
        ("retirement", "investment_contribution"),
    ])
    def test_a_payment_is_money_in_or_out_on_the_account_it_pays(self, ledger, account_type,
                                                                 financial_type):
        ledger.add_account("P", account_type)
        ledger.card("in.csv", REFUND, account="P")
        ledger.card("out.csv", OTHER, account="P")
        for name in ("in.csv", "out.csv"):
            code, out, err = ledger.classify(holding(ledger, name), financial_type, account="P")
            assert code == 0, err
        assert ledger.types() == [(financial_type, "2", "-5.00"), ("unclassified", "0", "0.00")]
        assert sorted(state for _, state, _ in ledger.outcomes()) == ["applied", "applied"]

    def test_a_correction_turning_a_card_payment_in_keeps_it_applied(self, ledger):
        ledger.add_account("P", "credit_card")
        ledger.card("a.csv", CAFE, account="P")
        transaction = holding(ledger, "a.csv")
        ledger.classify_ok(transaction, "card_payment", account="P")
        code, _, err = ledger.correct(transaction, "amount", "6.50", account="P")
        assert code == 0, err
        assert ledger.outcomes() == [(("a.csv",), "applied", "card_payment")]

    def test_interest_stays_money_out_on_savings(self, ledger):
        ledger.add_account("P", "savings")
        ledger.card("a.csv", REFUND, account="P")
        code, _, err = ledger.classify(holding(ledger, "a.csv"), "interest", account="P")
        assert code == 2 and "the type interest is money out" in err


def against_its_direction(ledger):
    """A refund of a corrected amount, left against its direction by undoing the correction."""
    transaction = single(ledger)
    correction = ledger.correct_ok(transaction, "amount", "6.50")
    refund = ledger.classify_ok(transaction, "refund")
    assert ledger.undo_correction(correction)[0] == 0
    assert ledger.outcomes() == [(("a.csv",), "against_direction", None)]
    return transaction, refund


def disagreeing_after_undo(ledger):
    """a and b merged, separated, classified differently, and merged again by undoing the
    separation. Returns the separation and the two classifications."""
    transaction, records = merged_two(ledger)
    separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
    purchase = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
    fee = ledger.classify_ok(holding(ledger, "b.csv"), "fee")
    code, out, err = ledger.undo(separation)
    assert code == 0, err
    return separation, purchase, fee


class TestStaleAccount:  # F5
    def test_classify_and_undo_are_refused_and_nothing_is_reconciled(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        token = ledger.classification_revision(classification)
        revision = ledger.transaction_revision(transaction)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        before = ledger.dump()
        for code, _, err in (
            ledger.classify(transaction, "fee", revision=revision, supersedes=classification,
                            supersedes_revision=token),
            ledger.undo_classification(classification, token),
        ):
            assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before
        assert "undo will be refused until it is" in ledger.classification_show(classification)


class TestSurvival:  # F6
    def classified(self, ledger):
        ledger.classify_ok(single(ledger), "purchase")
        return ledger.outcomes()

    def test_a_repeat_import(self, ledger):
        outcomes = self.classified(ledger)
        ledger.load_path(ledger.folder / "a.csv")
        assert ledger.outcomes() == outcomes

    def test_reconcile(self, ledger):
        outcomes = self.classified(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.outcomes() == outcomes

    def test_an_unrelated_file(self, ledger):
        outcomes = self.classified(ledger)
        ledger.card("other.csv", OTHER)
        assert ledger.outcomes() == outcomes
        assert ledger.types() == [("purchase", "1", "-6.50"), ("unclassified", "1", "-9.00")]

    def test_a_rules_change(self, ledger):
        outcomes = self.classified(ledger)
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, ledger.account_id(), replace(DEFAULT_RULES, date_window_days=5))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.outcomes() == outcomes

    def test_a_re_export_that_merges_keeps_it_applied_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.checking("b.csv", ID_ROW)
        assert ledger.count() == 1
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        bound = ledger.classification_show(classification).split("Bound records:\n")[1]
        bound = bound.split("  Revision:")[0]
        assert "a.csv row 1" in bound and "b.csv" not in bound


class TestSeveral:  # F7
    def test_agreeing_classifications_apply_once(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        ledger.classify_ok(two, "purchase")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        assert ledger.types() == [("purchase", "1", "-6.50"), ("unclassified", "0", "0.00")]

    def test_disagreeing_ones_leave_it_unclassified_and_disclosed_apart(self, ledger):
        disagreeing_after_undo(ledger)
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "conflict", None)]
        assert ledger.types() == [("unclassified", "1", "-6.50")]
        totals = ledger.totals()
        assert "left unclassified because classifications disagree: 1" in totals
        assert "possible-duplicate" not in totals and "keeping a source value" not in totals
        listed = ledger.run("review", "classifications")[1]
        assert re.search(r"^Transaction \S+: classifications disagree", listed, re.MULTILINE)

    def test_undoing_one_settles_it(self, ledger):
        _, purchase, fee = disagreeing_after_undo(ledger)
        assert ledger.undo_classification(fee)[0] == 0
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]


def classified_by_id_then_split(ledger):
    """a and b merged by a reliable ID, classified, then c, which makes the IDs conflict."""
    ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
    ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
    (transaction,) = ledger.merges()
    classification = ledger.classify_ok(transaction, "purchase")
    ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
    return classification


class TestSplits:  # F8
    def test_an_automatic_split_leaves_every_part_unclassified(self, ledger):
        classification = classified_by_id_then_split(ledger)
        assert ledger.count() == 3
        assert ledger.outcomes() == [(("a.csv",), "basis_changed", None),
                                     (("b.csv",), "basis_changed", None)]
        assert ledger.types() == [("unclassified", "3", "-15.00")]
        assert "binds records now in several transactions: 2" in ledger.totals()
        out = ledger.classification_show(classification)
        assert out.count("unclassified, basis changed now, unclassified after") == 2

    def test_undoing_it_leaves_them_plainly_unclassified(self, ledger):
        classification = classified_by_id_then_split(ledger)
        code, out, _ = ledger.undo_classification(classification)
        assert code == 0 and "now unclassified" not in out
        assert ledger.outcomes() == []


class TestDirection:
    def test_a_correction_against_the_type_is_refused(self, ledger):
        transaction = single(ledger)
        ledger.classify_ok(transaction, "purchase")
        before = ledger.dump()
        code, _, err = ledger.correct(transaction, "amount", "6.50")
        assert code == 2 and AGAINST_CLASSIFIED_DIRECTION in err
        assert ledger.dump() == before
        ledger.correct_ok(transaction, "amount", "-6.00")

    def test_undoing_a_correction_can_leave_it_against_its_direction(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "6.50")
        classification = ledger.classify_ok(transaction, "refund")
        code, out, _ = ledger.undo_correction(correction)
        assert code == 0
        assert "now unclassified, because classifications disagree, lost their basis or no " \
               "longer fit the direction: 1" in out
        assert ledger.outcomes() == [(("a.csv",), "against_direction", None)]
        assert "unclassified because their amount runs against the stated type: 1" in \
            ledger.totals()
        assert "against its direction now, unclassified after" in ledger.classification_show(
            classification)
        assert ledger.undo_classification(classification)[0] == 0
        ledger.classify_ok(transaction, "purchase")

    def test_a_zero_amount_takes_any_type(self, ledger):
        transaction = single(ledger)
        ledger.correct_ok(transaction, "amount", "0.00")
        ledger.classify_ok(transaction, "refund")
        assert ledger.types()[0] == ("refund", "1", "0.00")


class TestDecisionCommands:  # F9
    def test_confirming_disagreeing_classifications_refuses(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(one, "purchase")
        ledger.classify_ok(two, "fee")
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and LEAVES_CLASSIFICATION_UNSETTLED in err
        assert ledger.dump() == before

    def test_separating_a_classification_s_records_refuses(self, ledger):
        transaction, records = merged_three(ledger)
        ledger.classify_ok(transaction, "purchase")
        before = ledger.dump()
        code, _, err = ledger.separate(transaction, [records["a.csv"]],
                                       [records["b.csv"], records["c.csv"]])
        assert code == 2 and LEAVES_CLASSIFICATION_UNSETTLED in err
        assert ledger.dump() == before

    def test_separating_records_a_classification_does_not_bind_is_allowed(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert ledger.outcomes() == [(("a.csv",), "applied", "purchase")]

    def test_a_classification_made_since_makes_the_undo_token_stale(self, ledger):
        item, one, two = pair_up(ledger)
        decision = confirm_ok(ledger, item, (one, two))
        old = ledger.decision_revision(decision)
        shown = ledger.run("review", "decision", "show", decision)[1]
        assert "Changes which classifications apply" not in shown
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        before = ledger.dump()
        code, _, err = ledger.undo(decision, old)
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.dump() == before

        shown = ledger.run("review", "decision", "show", decision)[1]
        assert "Changes which classifications apply" in shown
        code, out, _ = ledger.undo(decision)
        assert code == 0 and "no longer fit the direction: 2" in out
        assert ledger.outcomes() == [(("a.csv",), "basis_changed", None),
                                     (("b.csv",), "basis_changed", None)]

    def test_a_rejection_is_unaffected(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        (item,) = ledger.items()
        ledger.reject_ok(item, (one, two))
        assert ledger.outcomes() == [(("a.csv",), "applied", "purchase")]

    def test_withdrawing_coverage_reports_the_split(self, ledger):
        both_complete(ledger)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        code, out, err = ledger.declare("a.csv", "unknown")
        assert code == 0, err
        assert "no longer fit the direction: 2" in out
        assert ledger.outcomes() == [(("a.csv",), "basis_changed", None),
                                     (("b.csv",), "basis_changed", None)]


class TestCorrectionTokens:
    def correction_left_against(self, tmp_path, capsys, name, financial_type):
        """A correction to 7.00 in, superseded by one to 7.00 out, a classification fitting that,
        and the superseding correction undone, which leaves the type against its direction."""
        folder = tmp_path / name
        folder.mkdir()
        ledger = ClassificationLedger(folder, capsys)
        transaction = single(ledger)
        first = ledger.correct_ok(transaction, "amount", "7.00")
        second = ledger.correct_ok(transaction, "amount", "-7.00", supersedes=first)
        ledger.classify_ok(transaction, financial_type)
        assert ledger.undo_correction(second)[0] == 0
        assert ledger.outcomes() == [(("a.csv",), "against_direction", None)]
        return ledger.correction_revision(first)

    def test_what_its_undo_would_apply_is_covered_where_nothing_applies_now(self, tmp_path, capsys):
        """Both are against their direction now, and undoing the correction applies either type."""
        assert self.correction_left_against(tmp_path, capsys, "purchase", "purchase") != (
            self.correction_left_against(tmp_path, capsys, "fee", "fee"))

    def test_a_classification_its_undo_would_turn_makes_the_correction_token_stale(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "6.50")
        old = ledger.correction_revision(correction)
        ledger.classify_ok(transaction, "refund")
        assert ledger.correction_revision(correction) != old
        before = ledger.dump()
        code, _, err = ledger.undo_correction(correction, old)
        assert code == 2 and STALE_CORRECTION_REVISION in err
        assert ledger.dump() == before

    def test_classifying_leaves_another_field_s_correction_token_unchanged(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "posting_date", "2026-01-11")
        token = ledger.correction_revision(correction)
        ledger.classify_ok(transaction, "purchase")
        assert ledger.correction_revision(correction) == token

    def test_an_amount_correction_s_token_is_unchanged_by_classifying_elsewhere(self, ledger):
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", OTHER)
        correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        token = ledger.correction_revision(correction)
        ledger.classify_ok(holding(ledger, "b.csv"), "purchase")
        assert ledger.correction_revision(correction) == token


def chain_of_three(ledger):
    transaction = single(ledger)
    first = ledger.classify_ok(transaction, "purchase")
    second = ledger.classify_ok(transaction, "fee", supersedes=first)
    third = ledger.classify_ok(transaction, "transfer", supersedes=second)
    return first, second, third


class TestChains:  # F10
    def test_only_the_newest_applies(self, ledger):
        classifications = chain_of_three(ledger)
        assert [ledger.classification_state(each) for each in classifications] == [
            "superseded", "superseded", "active"]
        assert ledger.types()[0] == ("transfer", "1", "-6.50")

    def test_undo_steps_back_one_link_at_a_time(self, ledger):
        first, second, third = chain_of_three(ledger)
        code, out, _ = ledger.undo_classification(third)
        assert code == 0 and f"Classification {second}, which it superseded, applies again." in out
        assert ledger.types()[0] == ("fee", "1", "-6.50")
        assert ledger.undo_classification(second)[0] == 0
        assert ledger.types()[0] == ("purchase", "1", "-6.50")
        code, out, _ = ledger.undo_classification(first)
        assert code == 0 and "which it superseded" not in out
        assert ledger.types() == [("unclassified", "1", "-6.50")]

    def test_a_superseded_classification_names_the_newest(self, ledger):
        first, second, third = chain_of_three(ledger)
        before = ledger.dump()
        code, _, err = ledger.undo_classification(first, "f1-0000000000000000")
        assert code == 2
        assert CLASSIFICATION_SUPERSEDED_IN_CHAIN.format(newer=second, newest=third) in err
        code, _, err = ledger.undo_classification(second, "f1-0000000000000000")
        assert code == 2 and CLASSIFICATION_SUPERSEDED.format(newer=third) in err
        code, _, err = ledger.classify(holding(ledger, "a.csv"), "interest", supersedes=first,
                                       supersedes_revision="f1-0")
        assert code == 2 and f"newest classification of the chain, {third}" in err
        assert ledger.dump() == before
        shown = ledger.classification_show(first)
        assert f"Superseded by classification {second}." in shown
        assert f"Newest of its chain: classification {third}" in shown

    def test_restoring_one_is_never_refused(self, ledger):
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        first = ledger.classify_ok(holding(ledger, "a.csv"), "fee")
        second = ledger.classify_ok(holding(ledger, "a.csv"), "purchase", supersedes=first)
        ledger.classify_ok(holding(ledger, "b.csv"), "purchase")
        assert ledger.undo(separation)[0] == 0
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        code, out, _ = ledger.undo_classification(second)
        assert code == 0 and "no longer fit the direction: 1" in out
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "conflict", None)]


class TestUndo:
    def built(self, tmp_path, capsys, name, files, classified):
        folder = tmp_path / name
        folder.mkdir()
        ledger = ClassificationLedger(folder, capsys)
        ledger.card("a.csv", CAFE)
        if classified:
            classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        for file_name, row in files:
            ledger.card(file_name, row)
        if classified:
            assert ledger.undo_classification(classification)[0] == 0
        return ledger

    @pytest.mark.parametrize("files", [(), (("x.csv", OTHER), ("y.csv", CAFE))])
    def test_it_equals_a_ledger_built_without_it(self, tmp_path, capsys, files):
        undone = self.built(tmp_path, capsys, "undone", files, classified=True)
        never = self.built(tmp_path, capsys, "never", files, classified=False)
        assert undone.view() == never.view()
        assert undone.outcomes() == never.outcomes() == []
        assert undone.types() == never.types()
        assert len(undone.dump(CLASSIFICATION_TABLES)["type_classification_event"]) == 2


class TestCompletions:
    def test_undoing_a_completion_waits_for_its_classification(self, ledger):
        ledger.card("a.csv", CAFE_NO_AMOUNT)
        (item,) = ledger.unresolved()
        resolution = ledger.complete_ok(item, amount="-6.50")
        classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        before = ledger.dump()
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2
        assert COMPLETION_BOUND.format(entries=f"classification {classification}") in err
        assert ledger.dump() == before
        assert f"Refused while classification {classification} binds the record" in \
            ledger.resolution_show(resolution)
        assert ledger.undo_classification(classification)[0] == 0
        assert ledger.undo_resolution(resolution)[0] == 0


class TestResolutions:
    def test_a_dismissal_joining_disagreeing_classifications_says_so(self, ledger):
        item = blocked_pair(ledger)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.classify_ok(holding(ledger, "b.csv"), "fee")
        code, out, err = ledger.dismiss(item)
        assert code == 0, err
        assert "no longer fit the direction: 1" in out
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "conflict", None)]

    def test_undoing_a_dismissal_that_splits_a_classified_merge_says_so(self, ledger):
        resolution = ledger.dismiss_ok(blocked_pair(ledger))
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        code, out, err = ledger.undo_resolution(resolution)
        assert code == 0, err
        assert "no longer fit the direction: 2" in out
        assert ledger.outcomes() == [(("a.csv",), "basis_changed", None),
                                     (("b.csv",), "basis_changed", None)]


class TestTokens:  # F11
    def test_the_version_is_pinned(self):
        assert classification_evidence.CLASSIFICATION_REVISION_VERSION == 1

    def test_the_classification_token_is_pinned(self, tmp_path, capsys):
        """Computed for this ledger when M3.1 was built, as a regression pin."""
        ledger = ClassificationLedger(tmp_path, capsys)
        path = tmp_path / "a.csv"
        path.write_text("Date,Description,Debit,Credit\n" + CAFE + "\n")
        ledger.load_path(path)
        classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        assert ledger.classification_revision(classification) == PINNED_CLASSIFICATION_REVISION

    def test_a_classification_changes_the_tokens_of_its_transaction_and_items(self, ledger):
        item, one, two = pair_up(ledger)
        item_before = ledger.revision(item)
        one_before, two_before = ledger.transaction_revision(one), ledger.transaction_revision(two)
        ledger.classify_ok(one, "purchase")
        (item,) = ledger.items()
        assert ledger.revision(item) != item_before
        assert ledger.transaction_revision(one) != one_before
        assert ledger.transaction_revision(two) == two_before

    def test_last_version_tokens_of_the_same_digest_are_refused(self, ledger):
        item, one, two = pair_up(ledger)
        code, _, _ = ledger.reject(item, (one, two), revision="r7-" + ledger.revision(item)[3:])
        assert code == 2

    def test_an_unrelated_file_leaves_the_classification_token_unchanged(self, ledger):
        classification = ledger.classify_ok(single(ledger), "purchase")
        token = ledger.classification_revision(classification)
        ledger.card("other.csv", OTHER)
        assert ledger.classification_revision(classification) == token

    def test_a_merging_re_export_changes_it(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        token = ledger.classification_revision(classification)
        ledger.checking("b.csv", ID_ROW)
        assert ledger.classification_revision(classification) != token

    def test_another_classification_reaching_it_changes_it(self, ledger):
        _, purchase, fee = disagreeing_after_undo(ledger)
        token = ledger.classification_revision(purchase)
        assert ledger.undo_classification(fee)[0] == 0
        assert ledger.classification_revision(purchase) != token

    def test_undoing_an_agreeing_classification_changes_what_undo_would_leave(self, ledger):
        """Both apply the same type, so only the outcome after this one's undo differs."""
        item, one, two = pair_up(ledger)
        first = ledger.classify_ok(one, "purchase")
        second = ledger.classify_ok(two, "purchase")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        token = ledger.classification_revision(first)
        assert "classified now, classified after" in ledger.classification_show(first)
        assert ledger.undo_classification(second)[0] == 0
        assert ledger.outcomes() == [(("a.csv", "b.csv"), "applied", "purchase")]
        assert ledger.classification_revision(first) != token
        assert "classified now, unclassified after" in ledger.classification_show(first)
        before = ledger.dump()
        code, _, err = ledger.undo_classification(first, token)
        assert code == 2 and STALE_CLASSIFICATION_REVISION in err
        assert ledger.dump() == before

    def test_a_correction_turning_its_direction_changes_it(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "6.50")
        classification = ledger.classify_ok(transaction, "refund")
        token = ledger.classification_revision(classification)
        assert ledger.undo_correction(correction)[0] == 0
        assert ledger.classification_revision(classification) != token

    def test_a_correction_keeping_its_direction_leaves_it_unchanged(self, ledger):
        transaction = single(ledger)
        classification = ledger.classify_ok(transaction, "purchase")
        token = ledger.classification_revision(classification)
        ledger.correct_ok(transaction, "amount", "-6.00")
        assert ledger.classification_revision(classification) == token


# Set when M3.1 was built, after its immaterial inputs were removed (D-053).
PINNED_CLASSIFICATION_REVISION = "f1-d981b70d43d9af68"


class TestPrivacy:
    SENTINEL_ROW = "01/10/2026,SENTINELMERCHANT,6.51,"

    def test_routine_classification_commands_show_no_amounts_or_descriptions(self, ledger):
        ledger.card("a.csv", self.SENTINEL_ROW)
        transaction = holding(ledger, "a.csv")
        outputs = []
        code, out, err = ledger.classify(transaction, "purchase")
        outputs += [out, err]
        classification = re.search(r"Classification (\S+) recorded", out)[1]
        for words in (("review", "classifications"),
                      ("review", "classification", "show", classification)):
            code, out, err = ledger.run(*words)
            assert code == 0
            outputs += [out, err]
        for code, out, err in (ledger.classify(transaction, "refund", supersedes=classification),
                               ledger.undo_classification(classification),
                               ledger.classify(transaction, "fee", revision="t7-0")):
            outputs += [out, err]
        text = "".join(outputs)
        for sentinel in ("6.51", "SENTINEL"):
            assert sentinel not in text
