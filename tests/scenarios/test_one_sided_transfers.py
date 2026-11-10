"""One-sided transfers, stated by a person, end to end, using synthetic data only (D-055)."""

import re
from dataclasses import replace

import pytest
from test_confirmations import confirm
from test_decisions import CHECKING_HEADER, FIRST_HALF, SECOND_HALF, SOURCE_TABLES, declared
from test_resolutions import CAFE_NO_AMOUNT
from test_separations import ID_ROW, merged_three, merged_two
from test_supersession import holding
from test_transfers import IN_ROW, OUT_ROW, TransferLedger

from personal_finance.reconcile.apply import load_constraints, load_evidence, reconcile_account
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.decisions import LEAVES_TRANSFER_UNSETTLED, STALE_ACCOUNT
from personal_finance.reconcile.record_resolutions import COMPLETION_BOUND
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfers import (
    ONE_SIDED_ALREADY_MATCHED,
    ONE_SIDED_ALREADY_STATED,
    ONE_SIDED_COUNTERPART_COVERED,
    ONE_SIDED_COUNTERPART_IN_VIEW,
    ONE_SIDED_NO_TRANSFER_TYPE,
    ONE_SIDED_NOT_ACTIVE,
    ONE_SIDED_SAME_ACCOUNT,
    ONE_SIDED_TYPE_DOES_NOT_FIT,
    ONE_SIDED_WRONG_ACCOUNT,
    PAIR_HOLDS_ONE_SIDED,
    STALE_ONE_SIDED_REVISION,
    STALE_TRANSACTION_REVISION,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reports import transfer_evidence

# An unrelated row of the counterpart, never a candidate for OUT_ROW, in either layout.
UNRELATED_ROW = "01/20/2026,SYNTHETIC GROCER,9.00,"
UNRELATED_CHECKING_ROW = "S-9,2026-01-20,2026-01-20,SYNTHETIC GROCER,-9.00,POSTED"
ONE_SIDED_TABLES = ("one_sided_transfer", "one_sided_transfer_record", "one_sided_transfer_event",
                    "one_sided_transfer_effect")


class OneSidedLedger(TransferLedger):
    def one_sided(self, transaction, counterpart_account="S", account="A", revision=None):
        return self.run(
            "review", "transfer", "one-sided", transaction, "--account", account,
            "--revision", revision or self.transaction_revision(transaction),
            "--counterpart-account", counterpart_account,
        )

    def one_sided_ok(self, transaction, counterpart_account="S", **options):
        code, out, err = self.one_sided(transaction, counterpart_account, **options)
        assert code == 0, err
        return re.search(r"One-sided transfer (\S+) recorded", out)[1]

    def one_sided_revision(self, statement):
        return re.search(r"Revision: (o1-[0-9a-f]{16})", self.transfer_show(statement))[1]

    def undo_one_sided(self, statement, account="A", revision=None):
        return self.run("review", "transfer", "undo", statement, "--account", account,
                        "--revision", revision or self.one_sided_revision(statement))

    def one_sided_states(self):
        """Each active one-sided transfer as its state and the files of its transaction."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (state, tuple(sorted(names.get(transaction_id, ()))))
            for state, transaction_id in conn.execute(
                "SELECT state, transaction_id FROM one_sided_transfer_effect")
        )
        conn.close()
        return found

    def make_stale(self, account):
        conn = self.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ? WHERE account_id = ?",
                     ("0" * 64, self.account_id(account)))
        conn.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    """A checking account A, a savings account S and a card never imported."""
    found = OneSidedLedger(tmp_path, capsys)
    found.add_account("S", "savings")
    found.add_account("Card", "credit_card")
    return found


def outflow(ledger, row=OUT_ROW, financial_type="transfer"):
    ledger.card("out.csv", row)
    transaction = holding(ledger, "out.csv")
    if financial_type:
        ledger.classify_ok(transaction, financial_type)
    return transaction


def stated(ledger, counterpart_account="S", **options):
    transaction = outflow(ledger, **options)
    return ledger.one_sided_ok(transaction, counterpart_account), transaction


class TestStating:  # O1, O2
    def test_it_applies_to_an_account_with_no_documents(self, ledger):
        transaction = outflow(ledger)
        code, out, err = ledger.one_sided(transaction)
        assert code == 0, err
        assert f"transaction {transaction} with S, binding 1 records" in out
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]

    def test_a_card_payment_names_the_card(self, ledger):
        stated(ledger, "Card", financial_type="card_payment")
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]

    def test_it_changes_no_movement_type_or_source(self, ledger):  # O2
        transaction = outflow(ledger)
        before = ledger.before_transfers()
        tables = (*SOURCE_TABLES, "ledger_transaction", "transaction_source",
                  "transaction_classification", "transaction_correction")
        dumped = ledger.dump(tables)
        ledger.one_sided_ok(transaction)
        assert ledger.before_transfers() == before
        assert ledger.dump(tables) == dumped

    def test_derivation_never_reads_it(self, ledger):  # O2
        transaction = outflow(ledger)

        def derived():
            conn = ledger.conn()
            account = ledger.account_id("A")
            found = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                           load_constraints(conn, account))
            conn.close()
            return found

        before = derived()
        ledger.one_sided_ok(transaction)
        assert derived() == before

    def test_transaction_show_and_the_list(self, ledger):
        statement, transaction = stated(ledger)
        out = ledger.transaction_show(transaction)
        assert f"One-sided transfer {statement}, counterpart: S" in out
        assert "Transfer: it moves money to or from the counterpart" in out
        listed = ledger.run("review", "transfers")[1]
        assert f"One-sided transfer {statement}: active, applied, A with S, " in listed
        assert "One-sided transfers: 1" in listed
        assert "50.00" not in listed and "SYNTHETIC" not in listed
        assert f"One-sided transfer {statement}" in ledger.run("review", "transfers",
                                                                "--account", "S")[1]
        assert "One-sided transfers: 0" in ledger.run("review", "transfers", "--account", "Card")[1]

    def test_show(self, ledger):
        statement, transaction = stated(ledger)
        out = ledger.transfer_show(statement)
        assert re.search(rf"Status: active\n.*\n  Account: A .*\n  Counterpart: S .*\n"
                         rf"  From transaction: {transaction}\n  out.csv row 1, now in "
                         rf"{transaction}\n", out)
        assert "Undoing this one-sided transfer now" in out


class TestRefusals:  # O3
    def nothing_changes(self, ledger, attempt, message):
        before = ledger.dump()
        code, _, err = attempt()
        assert code == 2
        assert message in err, err
        assert ledger.dump() == before

    def test_the_same_account(self, ledger):
        transaction = outflow(ledger)
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, "A"),
                             ONE_SIDED_SAME_ACCOUNT)

    def test_an_unknown_account(self, ledger):
        transaction = outflow(ledger)
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, "Nowhere"),
                             "account not found")

    def test_an_unknown_transaction_or_one_of_another_account(self, ledger):
        transaction = outflow(ledger)
        self.nothing_changes(ledger, lambda: ledger.one_sided("nope", revision="t8-0"),
                             TRANSACTION_NOT_FOUND.format(transaction="nope"))
        ledger.add_account("T", "savings")
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, account="T"),
                             TRANSACTION_WRONG_ACCOUNT.format(transaction=transaction))

    def test_a_stale_token(self, ledger):
        transaction = outflow(ledger, financial_type=None)
        token = ledger.transaction_revision(transaction)
        ledger.classify_ok(transaction, "transfer")
        for stale in (token, "t8-0000000000000000",
                      "t7-" + ledger.transaction_revision(transaction).split("-")[1]):
            self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, revision=stale),
                                 STALE_TRANSACTION_REVISION.format(transaction=transaction))

    @pytest.mark.parametrize("account", ["A", "S"])
    def test_a_stale_account_on_either_side_is_not_reconciled(self, ledger, account):
        transaction = outflow(ledger)
        ledger.card("s.csv", UNRELATED_ROW, account="S")
        ledger.make_stale(account)
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction), STALE_ACCOUNT)

    def test_no_transfer_kind(self, ledger):
        for financial_type in (None, "purchase"):
            transaction = outflow(ledger, financial_type=financial_type)
            self.nothing_changes(ledger, lambda: ledger.one_sided(transaction),
                                 ONE_SIDED_NO_TRANSFER_TYPE)

    @pytest.mark.parametrize(("financial_type", "counterpart"), [
        ("card_payment", "S"), ("loan_payment", "Card"), ("investment_contribution", "Card"),
    ])
    def test_a_type_that_does_not_fit_the_counterpart(self, ledger, financial_type, counterpart):
        transaction = outflow(ledger, financial_type=financial_type)
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, counterpart),
                             ONE_SIDED_TYPE_DOES_NOT_FIT)

    def test_a_transaction_already_matched_or_stated(self, ledger):
        statement, transaction = stated(ledger)
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, "Card"),
                             ONE_SIDED_ALREADY_STATED)
        assert ledger.undo_one_sided(statement)[0] == 0
        ledger.card("in.csv", IN_ROW, account="S")
        ledger.match_ok(transaction, holding(ledger, "in.csv"))
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction, "Card"),
                             ONE_SIDED_ALREADY_MATCHED)

    def test_a_candidate_with_the_counterpart(self, ledger):
        transaction = outflow(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction),
                             ONE_SIDED_COUNTERPART_IN_VIEW)

    def test_a_candidate_in_a_third_account_does_not_refuse(self, ledger):
        transaction = outflow(ledger)
        ledger.add_account("T", "savings")
        ledger.card("in.csv", IN_ROW, account="T")
        assert ledger.candidates() == [(transaction, holding(ledger, "in.csv"))]
        ledger.one_sided_ok(transaction)
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]
        assert ledger.candidates() == [(transaction, holding(ledger, "in.csv"))]

    def test_counterpart_coverage_spanning_the_window(self, ledger):
        transaction = outflow(ledger)
        ledger.card("s.csv", UNRELATED_ROW, account="S",
                    extra=declared("2026-01-05", "2026-01-15"))
        self.nothing_changes(ledger, lambda: ledger.one_sided(transaction),
                             ONE_SIDED_COUNTERPART_COVERED)


class TestCoverageWindow:  # O6
    """OUT_ROW is dated 01/10, so its window is 01/05 to 01/15."""

    @pytest.mark.parametrize("basis", ["posting", "transaction"])
    @pytest.mark.parametrize(("start", "end", "spans"), [
        ("2026-01-05", "2026-01-15", True),
        ("2026-01-01", "2026-01-31", True),
        ("2026-01-06", "2026-01-15", False),
        ("2026-01-05", "2026-01-14", False),
    ])
    def test_spanning_is_exact_at_the_edges(self, ledger, basis, start, end, spans):
        transaction = outflow(ledger)
        # The card layout offers posting coverage only, and the checking layout both.
        ledger.load_path(ledger.write("s.csv", CHECKING_HEADER, [UNRELATED_CHECKING_ROW]),
                         account="S", layout="synthetic_checking_v1")
        ledger.declare_ok("s.csv", account="S", start=start, end=end, basis=basis)
        code, _, err = ledger.one_sided(transaction)
        if spans:
            assert code == 2 and ONE_SIDED_COUNTERPART_COVERED in err
        else:
            assert code == 0, err
            assert ledger.one_sided_states() == [("applied", ("out.csv",))]

    @pytest.mark.parametrize(("generated_on", "spans"), [("2026-01-16", True),
                                                          ("2026-01-15", False)])
    def test_metadata_coverage_ends_where_it_supports_matching(self, ledger, generated_on,
                                                               spans):
        """A claim to 01/15 generated on 01/15 cannot vouch for that day (D-027)."""
        transaction = outflow(ledger)
        preamble = (f"# generated-on: {generated_on}\n# coverage-kind: complete\n"
                    "# coverage-start: 2026-01-01\n# coverage-end: 2026-01-15\n"
                    "# coverage-basis: posting\n")
        ledger.load_path(ledger.write("s.csv", preamble + CHECKING_HEADER,
                                      ["S-9,2026-01-02,2026-01-02,SYNTHETIC GROCER,-9.00,POSTED"]),
                         account="S", layout="synthetic_checking_v1")
        code, _, err = ledger.one_sided(transaction)
        if spans:
            assert code == 2 and ONE_SIDED_COUNTERPART_COVERED in err
        else:
            assert code == 0, err

    def test_two_documents_together_can_span_it(self, ledger):
        transaction = outflow(ledger)
        ledger.card("s1.csv", "01/02/2026,SYNTHETIC GROCER,9.00,", account="S",
                    extra=declared("2026-01-01", "2026-01-09"))
        ledger.card("s2.csv", UNRELATED_ROW, account="S",
                    extra=declared("2026-01-10", "2026-01-31"))
        code, _, err = ledger.one_sided(transaction)
        assert code == 2 and ONE_SIDED_COUNTERPART_COVERED in err

    def test_spans_on_two_bases_do_not_join(self, ledger):
        transaction = outflow(ledger)
        for name, row in (("s1.csv", "S-8,2026-01-02,2026-01-02,SYNTHETIC GROCER,-9.00,POSTED"),
                          ("s2.csv", UNRELATED_CHECKING_ROW)):
            ledger.load_path(ledger.write(name, CHECKING_HEADER, [row]), account="S",
                             layout="synthetic_checking_v1")
        ledger.declare_ok("s1.csv", account="S", start="2026-01-01", end="2026-01-09",
                          basis="posting")
        ledger.declare_ok("s2.csv", account="S", start="2026-01-10", end="2026-01-31",
                          basis="transaction")
        ledger.one_sided_ok(transaction)


class TestSurvival:  # O4
    def test_a_repeat_import_reconcile_an_unrelated_file_and_a_rules_change(self, ledger):
        stated(ledger)
        ledger.load_path(ledger.folder / "out.csv")
        assert ledger.run("reconcile")[0] == 0
        ledger.card("other.csv", "02/20/2026,SYNTHETIC GROCER,9.00,")
        ledger.card("s.csv", "03/20/2026,SYNTHETIC GROCER,8.00,", account="S")
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, ledger.account_id("A"), replace(DEFAULT_RULES, date_window_days=5))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]

    def test_a_re_export_joining_it_keeps_it_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        transaction = holding(ledger, "a.csv")
        ledger.classify_ok(transaction, "transfer")
        statement = ledger.one_sided_ok(transaction)
        token = ledger.one_sided_revision(statement)
        ledger.checking("b.csv", ID_ROW)
        assert ledger.one_sided_states() == [("applied", ("a.csv", "b.csv"))]
        assert "b.csv" not in ledger.transfer_show(statement)
        assert ledger.one_sided_revision(statement) != token


class TestOutcomes:  # O5, O7
    def test_an_automatic_split_changes_its_basis(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (transaction,) = ledger.merges()
        ledger.classify_ok(transaction, "transfer")
        statement = ledger.one_sided_ok(transaction)
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        assert ledger.one_sided_states() == [("basis_changed", ())]
        assert "its bound records are now in several transactions" in \
            ledger.transfer_show(statement)

    def test_a_match_reaching_its_transaction_is_a_conflict_for_both(self, ledger):
        merged, records = merged_two(ledger)
        separation = ledger.separate_ok(merged, [records["a.csv"]], [records["b.csv"]])
        ledger.classify_ok(holding(ledger, "a.csv"), "transfer")
        ledger.one_sided_ok(holding(ledger, "a.csv"), "Card")
        ledger.card("in.csv", "01/11/2026,SYNTHETIC MOVE IN,,6.50", account="S")
        ledger.classify_ok(holding(ledger, "in.csv"), "transfer", account="S")
        ledger.match_ok(holding(ledger, "b.csv"), holding(ledger, "in.csv"))
        code, out, _ = ledger.undo(separation)
        assert code == 0 and "or is covered: 2." in out
        assert ledger.one_sided_states() == [("conflict", ())]
        assert ledger.matches() == [("conflict", (), ())]

    def test_two_one_sided_transfers_reaching_one_transaction_conflict(self, ledger):
        merged, records = merged_two(ledger)
        separation = ledger.separate_ok(merged, [records["a.csv"]], [records["b.csv"]])
        for name in ("a.csv", "b.csv"):
            ledger.classify_ok(holding(ledger, name), "transfer")
            ledger.one_sided_ok(holding(ledger, name))
        assert ledger.undo(separation)[0] == 0
        assert ledger.one_sided_states() == [("conflict", ()), ("conflict", ())]

    def test_undoing_its_type_makes_the_type_differ(self, ledger):
        transaction = outflow(ledger, financial_type="purchase")
        purchase = ledger.run("review", "classifications")[1].split()[1].rstrip(":")
        transfer = ledger.classify_ok(transaction, "transfer", supersedes=purchase)
        ledger.one_sided_ok(transaction)
        code, out, _ = ledger.undo_classification(transfer)
        assert code == 0 and "Transfer matches or one-sided transfers that no longer apply" in out
        assert ledger.one_sided_states() == [("type_differs", ())]

    def test_unclassified_again_the_type_differs(self, ledger):
        transaction = outflow(ledger)
        (classification,) = re.findall(r"^Classification (\S+):",
                                       ledger.run("review", "classifications")[1], re.MULTILINE)
        ledger.one_sided_ok(transaction)
        assert ledger.undo_classification(classification)[0] == 0
        assert ledger.one_sided_states() == [("type_differs", ())]

    def test_the_counterpart_arriving_is_found_and_can_then_be_matched(self, ledger):  # O8
        statement, transaction = stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        inflow = holding(ledger, "in.csv")
        assert ledger.one_sided_states() == [("counterpart_found", ())]
        assert "a transaction of the counterpart may now be its other side" in \
            ledger.transfer_show(statement)
        assert ledger.candidates() == [(transaction, inflow)]
        before = ledger.dump()
        code, _, err = ledger.match(transaction, inflow)
        assert code == 2 and PAIR_HOLDS_ONE_SIDED in err
        assert ledger.dump() == before
        assert ledger.undo_one_sided(statement)[0] == 0
        ledger.match_ok(transaction, inflow)
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_the_counterpart_on_the_inflow_side_also_refuses_a_match(self, ledger):  # O8
        statement, transaction = stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        code, _, err = ledger.match(holding(ledger, "in.csv"), transaction, account="S",
                                    counterpart_account="A")
        assert code == 2 and PAIR_HOLDS_ONE_SIDED in err

    def test_coverage_declared_later_covers_it(self, ledger):
        statement, _ = stated(ledger)
        ledger.card("s.csv", UNRELATED_ROW, account="S")
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]
        code, out, err = ledger.declare("s.csv", account="S", start="2026-01-01",
                                        end="2026-01-31", basis="posting")
        assert code == 0, err
        assert "or is covered: 1." in out
        assert ledger.one_sided_states() == [("counterpart_covered", ())]
        assert "the counterpart's complete coverage now spans its dates" in \
            ledger.transfer_show(statement)

    def test_a_correction_that_unsettles_nothing_is_allowed(self, ledger):
        _, transaction = stated(ledger)
        # A transfer fits either direction, and no counterpart transaction is in view.
        ledger.correct_ok(transaction, "amount", "50.00")
        ledger.correct_ok(transaction, "description", "SYNTHETIC MOVE")
        assert ledger.one_sided_states() == [("applied", ("out.csv",))]

    def test_a_correction_that_brings_the_counterpart_into_view_refuses(self, ledger):  # O7
        _, transaction = stated(ledger)
        ledger.card("in.csv", "01/12/2026,SYNTHETIC MOVE IN,,49.00", account="S")
        before = ledger.dump()
        code, _, err = ledger.correct(transaction, "amount", "-49.00")
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before

    def test_classifying_it_against_the_counterpart_refuses(self, ledger):  # O7
        transaction = outflow(ledger)
        (classification,) = re.findall(r"^Classification (\S+):",
                                       ledger.run("review", "classifications")[1], re.MULTILINE)
        ledger.one_sided_ok(transaction)
        before = ledger.dump()
        code, _, err = ledger.classify(transaction, "card_payment", supersedes=classification)
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before

    def test_confirming_two_stated_transactions_as_one_refuses(self, ledger):  # O7
        ledger.card("a.csv", OUT_ROW, extra=FIRST_HALF)
        ledger.card("b.csv", OUT_ROW, extra=SECOND_HALF)
        (item,) = ledger.items()
        one, two = ledger.transactions(item)
        for transaction in (one, two):
            ledger.classify_ok(transaction, "transfer")
            ledger.one_sided_ok(transaction)
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before

    def test_separating_it_refuses(self, ledger):  # O7
        transaction, records = merged_three(ledger)
        ledger.classify_ok(transaction, "transfer")
        ledger.one_sided_ok(transaction)
        before = ledger.dump()
        code, _, err = ledger.separate(transaction, [records["a.csv"]],
                                       [records["b.csv"], records["c.csv"]])
        # Its type is on the same transaction, so the classification's refusal comes first.
        assert code == 2 and "would leave a classified transaction unclassified" in err
        assert ledger.dump() == before

    def test_undoing_a_completion_waits_for_it(self, ledger):  # O7
        ledger.card("out.csv", CAFE_NO_AMOUNT)
        (unresolved,) = ledger.unresolved()
        resolution = ledger.complete_ok(unresolved, amount="-50.00")
        transaction = holding(ledger, "out.csv")
        ledger.classify_ok(transaction, "transfer")
        (classification,) = re.findall(r"^Classification (\S+):",
                                       ledger.run("review", "classifications")[1], re.MULTILINE)
        statement = ledger.one_sided_ok(transaction)
        assert ledger.undo_classification(classification)[0] == 0
        before = ledger.dump()
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2
        assert COMPLETION_BOUND.format(entries=f"one-sided transfer {statement}") in err
        assert ledger.dump() == before
        assert f"Refused while one-sided transfer {statement} binds the record" in \
            ledger.resolution_show(resolution)


class TestUndo:  # O9
    @pytest.mark.parametrize("account", ["A", "S"])
    def test_undo_keeps_it_on_record_from_either_account(self, ledger, account):
        statement, _ = stated(ledger)
        code, out, err = ledger.undo_one_sided(statement, account=account)
        assert code == 0, err
        assert "counts as an unpaired transfer kind again" in out
        assert ledger.one_sided_states() == []
        out = ledger.transfer_show(statement)
        assert "Status: undone" in out and "Revision:" not in out
        assert ledger.dump(ONE_SIDED_TABLES)["one_sided_transfer_record"]

    def test_refusals(self, ledger):
        statement, _ = stated(ledger)
        token = ledger.one_sided_revision(statement)
        before = ledger.dump()
        for (code, _, err), message in (
            (ledger.undo_one_sided(statement, account="Card", revision=token),
             ONE_SIDED_WRONG_ACCOUNT),
            (ledger.undo_one_sided(statement, revision="o1-0000000000000000"),
             STALE_ONE_SIDED_REVISION),
            # A match's prefix on the same digest is not this token.
            (ledger.undo_one_sided(statement, revision="m1-" + token[3:]),
             STALE_ONE_SIDED_REVISION),
        ):
            assert code == 2 and message in err, err
        assert ledger.dump() == before
        assert ledger.undo_one_sided(statement)[0] == 0
        code, _, err = ledger.undo_one_sided(statement, revision=token)
        assert code == 2 and ONE_SIDED_NOT_ACTIVE in err

    def test_an_unknown_id(self, ledger):
        stated(ledger)
        before = ledger.dump()
        for code, _, err in (ledger.run("review", "transfer", "show", "nope"),
                             ledger.undo_match("nope", revision="m1-0"),
                             ledger.undo_one_sided("nope", revision="o1-0")):
            assert code == 2 and "transfer match or one-sided transfer not found" in err
        assert ledger.dump() == before

    @pytest.mark.parametrize("account", ["A", "S"])
    def test_a_stale_account_on_either_side_refuses(self, ledger, account):
        statement, _ = stated(ledger)
        ledger.card("s.csv", UNRELATED_ROW, account="S")
        token = ledger.one_sided_revision(statement)
        ledger.make_stale(account)
        before = ledger.dump()
        code, _, err = ledger.undo_one_sided(statement, revision=token)
        assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before
        assert "undo will be refused until it is" in ledger.transfer_show(statement)

    def test_undo_settles_without_refusing(self, ledger):
        statement, _ = stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        assert ledger.one_sided_states() == [("counterpart_found", ())]
        assert ledger.undo_one_sided(statement)[0] == 0

    def test_undoing_a_match_can_bring_the_counterpart_into_view(self, ledger):
        statement, transaction = stated(ledger)
        ledger.add_account("T", "savings")
        ledger.card("in.csv", IN_ROW, account="S")
        ledger.card("t.csv", "01/11/2026,SYNTHETIC MOVE OUT,50.00,", account="T")
        inflow = holding(ledger, "in.csv")
        ledger.classify_ok(holding(ledger, "t.csv"), "transfer", account="T")
        # The counterpart's arrival unsettled it, so undo it, match the arrival elsewhere, and
        # state it again: undoing that other match brings the counterpart back into view.
        assert ledger.undo_one_sided(statement)[0] == 0
        match = ledger.match_ok(holding(ledger, "t.csv"), inflow, account="T",
                                counterpart_account="S")
        ledger.one_sided_ok(transaction)
        code, out, _ = ledger.undo_match(match, account="T")
        assert code == 0 and "or is covered: 1." in out
        assert ledger.one_sided_states() == [("counterpart_found", ())]


class TestTokens:  # O11
    def test_the_version_is_pinned(self, ledger):
        assert transfer_evidence.ONE_SIDED_REVISION_VERSION == 1
        statement, _ = stated(ledger)
        assert re.fullmatch(r"o1-[0-9a-f]{16}", ledger.one_sided_revision(statement))

    def test_stating_it_changes_the_transaction_token(self, ledger):
        transaction = outflow(ledger)
        token = ledger.transaction_revision(transaction)
        ledger.one_sided_ok(transaction)
        assert ledger.transaction_revision(transaction) != token

    def test_another_counterpart_is_another_token(self, ledger):
        ledger.add_account("T", "savings")
        statement, transaction = stated(ledger)
        token = ledger.transaction_revision(transaction)
        assert ledger.undo_one_sided(statement)[0] == 0
        ledger.one_sided_ok(transaction, "T")
        assert ledger.transaction_revision(transaction) != token

    def test_an_unrelated_file_leaves_it_unchanged(self, ledger):
        statement, _ = stated(ledger)
        token = ledger.one_sided_revision(statement)
        ledger.card("other.csv", "02/20/2026,SYNTHETIC GROCER,9.00,")
        ledger.card("s.csv", "02/21/2026,SYNTHETIC GROCER,8.00,", account="S")
        assert ledger.one_sided_revision(statement) == token

    def test_its_outcome_changes_it(self, ledger):
        statement, _ = stated(ledger)
        token = ledger.one_sided_revision(statement)
        ledger.card("in.csv", IN_ROW, account="S")
        assert ledger.one_sided_revision(statement) != token

    def test_equal_in_two_ledgers(self, tmp_path, capsys):
        tokens = []
        for number in range(2):
            folder = tmp_path / str(number)
            folder.mkdir()
            ledger = OneSidedLedger(folder, capsys)
            ledger.add_account("S", "savings")
            statement, transaction = stated(ledger)
            tokens.append((ledger.one_sided_revision(statement),
                           ledger.transaction_revision(transaction)))
        assert tokens[0] == tokens[1]


class TestTotals:  # O10
    def test_counts_amounts_and_coverage_warnings(self, ledger):
        stated(ledger)
        ledger.card("in.csv", "02/12/2026,SYNTHETIC MOVE IN,,20.00")
        ledger.classify_ok(holding(ledger, "in.csv"), "transfer")
        ledger.add_account("T", "savings")
        ledger.card("t.csv", UNRELATED_ROW, account="T")
        ledger.one_sided_ok(holding(ledger, "in.csv"), "T")
        ledger.card("more.csv", "03/10/2026,SYNTHETIC MOVE OUT,7.00,")
        ledger.classify_ok(holding(ledger, "more.csv"), "transfer")
        ledger.one_sided_ok(holding(ledger, "more.csv"))
        assert ledger.transfers_section() == (
            "  Matched: 0 pairs, moving 0.00\n"
            "  In a candidate pair, not matched: 0 transactions\n"
            "  One-sided, the other side not in the ledger: 3 transactions, 57.00 out and 20.00 in\n"
            "  Of a transfer kind with no match, candidate or one-sided transfer: 0 transactions\n"
        )
        assert "3 one-sided transfers rest on another account whose side is not in the ledger: 2 " \
               "where that account has no documents, 1 where its documents do not cover every " \
               "day within 5 days." in ledger.totals()
        assert "spending on that card is understated" not in ledger.totals()

    def test_for_one_account_those_held_there_or_naming_it(self, ledger):
        stated(ledger)
        ledger.add_account("T", "savings")
        for account in ("A", "S"):
            assert "  One-sided, the other side not in the ledger: 1 transactions, 50.00 out " \
                   "and 0.00 in\n" in ledger.transfers_section(account)
        assert "  One-sided, the other side not in the ledger: 0 transactions" in \
            ledger.transfers_section("T")

    def test_a_card_payment_to_a_card_with_no_history_warns(self, ledger):
        stated(ledger, "Card", financial_type="card_payment")
        assert "1 card payments, 50.00, go to a card whose purchases for those dates are not in " \
               "the ledger, so spending on that card is understated." in ledger.totals()
        assert "spending on that card is understated" in ledger.run("totals", "--account",
                                                                    "Card")[1]

    def test_a_card_payment_received_on_the_card_does_not_warn(self, ledger):
        ledger.card("card.csv", "01/12/2026,SYNTHETIC PAYMENT,,50.00", account="Card")
        transaction = holding(ledger, "card.csv")
        ledger.classify_ok(transaction, "card_payment", account="Card")
        ledger.one_sided_ok(transaction, account="Card")
        assert "spending on that card is understated" not in ledger.totals()

    def test_unpaired_transfer_kinds_leave_it_out(self, ledger):
        transaction = outflow(ledger)
        assert "candidate or one-sided transfer: 1 transactions" in ledger.transfers_section()
        ledger.one_sided_ok(transaction)
        assert "candidate or one-sided transfer: 0 transactions" in ledger.transfers_section()

    def test_unsettled_states_are_disclosed_and_not_counted(self, ledger):
        stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        assert "1 one-sided transfers no longer apply, because a transaction of the counterpart " \
               "may be the other side." in ledger.totals()
        assert "  One-sided, the other side not in the ledger: 0 transactions" in \
            ledger.transfers_section()
        assert "rest on another account" not in ledger.totals()
