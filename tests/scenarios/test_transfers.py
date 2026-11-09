"""Transfers between two accounts, matched by a person, end to end, using synthetic data only (D-054)."""

import re
from dataclasses import replace

import pytest
from test_classifications import ClassificationLedger
from test_confirmations import confirm
from test_decisions import FIRST_HALF, SECOND_HALF, SOURCE_TABLES
from test_resolutions import CAFE_NO_AMOUNT
from test_separations import ID_ROW, merged_three, merged_two
from test_supersession import holding

from personal_finance.reconcile.apply import load_constraints, load_evidence, reconcile_account
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.decisions import LEAVES_TRANSFER_UNSETTLED, STALE_ACCOUNT
from personal_finance.reconcile.record_resolutions import COMPLETION_BOUND
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfer_effects import (
    PAIR_ALREADY_MATCHED,
    PAIR_AMOUNTS_DO_NOT_OFFSET,
    PAIR_DATES_TOO_FAR,
    PAIR_NO_TRANSFER_TYPE,
    PAIR_SAME_ACCOUNT,
    PAIR_TYPE_DOES_NOT_FIT,
)
from personal_finance.reconcile.transfers import (
    MATCH_NOT_ACTIVE,
    MATCH_WRONG_ACCOUNT,
    REFUSAL_BY_REASON,
    STALE_MATCH_REVISION,
    STALE_TRANSACTION_REVISION,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reports import transfer_evidence

OUT_ROW = "01/10/2026,SYNTHETIC MOVE OUT,50.00,"
IN_ROW = "01/12/2026,SYNTHETIC MOVE IN,,50.00"
TRANSFER_TABLES = ("transfer_match", "transfer_match_side", "transfer_match_record",
                   "transfer_match_event", "transfer_match_effect")


class TransferLedger(ClassificationLedger):
    def candidates(self, account=None):
        words = ["review", "transfers"] + (["--account", account] if account else [])
        out = self.run(*words)[1]
        return re.findall(r"^Candidate: transaction (\S+) .* to transaction (\S+) ", out,
                          re.MULTILINE)

    def match(self, transaction, counterpart, account="A", counterpart_account="S",
              revision=None, counterpart_revision=None):
        return self.run(
            "review", "transfer", "match", transaction, "--account", account,
            "--revision", revision or self.transaction_revision(transaction),
            "--counterpart", counterpart, "--counterpart-account", counterpart_account,
            "--counterpart-revision", counterpart_revision or self.transaction_revision(counterpart),
        )

    def match_ok(self, transaction, counterpart, **options):
        code, out, err = self.match(transaction, counterpart, **options)
        assert code == 0, err
        return re.search(r"Match (\S+) recorded", out)[1]

    def transfer_show(self, match):
        code, out, err = self.run("review", "transfer", "show", match)
        assert code == 0, err
        return out

    def match_revision(self, match):
        return re.search(r"Revision: (m1-[0-9a-f]{16})", self.transfer_show(match))[1]

    def undo_match(self, match, account="A", revision=None):
        return self.run("review", "transfer", "undo", match, "--account", account,
                        "--revision", revision or self.match_revision(match))

    def matches(self):
        """Each active match as its state and the file names of each side's transaction."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (state, tuple(sorted(names.get(outflow, ()))), tuple(sorted(names.get(inflow, ()))))
            for state, outflow, inflow in conn.execute(
                """SELECT state, outflow_transaction_id, inflow_transaction_id
                   FROM transfer_match_effect"""
            )
        )
        conn.close()
        return found

    def transfers_section(self, account=None):
        words = ["totals"] + (["--account", account] if account else [])
        out = self.run(*words)[1]
        return out.split("Transfers between your accounts, as you matched them:\n")[1].split(
            "Income and spending, as you classified and matched them:")[0]

    def income_section(self, account=None):
        words = ["totals"] + (["--account", account] if account else [])
        out = self.run(*words)[1]
        return out.split("Income and spending, as you classified and matched them:\n")[1].split(
            "Disclosures:")[0]

    def before_transfers(self):
        """Totals up to the transfer section: account movement and financial types."""
        return self.totals().split("Transfers between your accounts")[0]


@pytest.fixture
def ledger(tmp_path, capsys):
    found = TransferLedger(tmp_path, capsys)
    found.add_account("S", "savings")
    return found


def sides(ledger, out_row=OUT_ROW, in_row=IN_ROW, out_type="transfer", in_account="S"):
    """An outflow in A, classified, and an inflow in another account, unclassified."""
    ledger.card("out.csv", out_row)
    ledger.card("in.csv", in_row, account=in_account)
    outflow, inflow = holding(ledger, "out.csv"), holding(ledger, "in.csv")
    if out_type:
        ledger.classify_ok(outflow, out_type)
    return outflow, inflow


def rows_of(ledger, name):
    """The transactions holding each row of a file, in row order."""
    conn = ledger.conn()
    found = [row[0] for row in conn.execute(
        """SELECT link.transaction_id FROM transaction_source link
           JOIN source_document document ON document.id = link.source_document_id
           JOIN source_record record ON record.id = link.source_record_id
           WHERE document.file_name = ? ORDER BY record.record_index""",
        (name,),
    )]
    conn.close()
    return found


def matched(ledger, **options):
    outflow, inflow = sides(ledger, **options)
    return ledger.match_ok(outflow, inflow), outflow, inflow


class TestCandidates:  # X1
    def test_a_transfer_with_the_opposite_amount_in_another_account_is_one(self, ledger):
        outflow, inflow = sides(ledger)
        assert ledger.candidates() == [(outflow, inflow)]
        assert ledger.candidates("S") == [(outflow, inflow)]

    def test_the_type_may_be_on_either_side(self, ledger):
        outflow, inflow = sides(ledger, out_type=None)
        ledger.classify_ok(inflow, "transfer", account="S")
        assert ledger.candidates() == [(outflow, inflow)]

    def test_equal_amounts_alone_are_not_one(self, ledger):
        sides(ledger, out_type=None)
        assert ledger.candidates() == []

    @pytest.mark.parametrize("in_row", [
        "01/12/2026,SYNTHETIC MOVE IN,,50.01",
        "01/12/2026,SYNTHETIC MOVE IN,50.00,",
        "01/16/2026,SYNTHETIC MOVE IN,,50.00",
        "01/04/2026,SYNTHETIC MOVE IN,,50.00",
    ])
    def test_another_amount_or_a_date_outside_the_window_is_not_one(self, ledger, in_row):
        sides(ledger, in_row=in_row)
        assert ledger.candidates() == []

    @pytest.mark.parametrize("in_row", ["01/15/2026,SYNTHETIC MOVE IN,,50.00",
                                        "01/05/2026,SYNTHETIC MOVE IN,,50.00"])
    def test_five_days_apart_is_one(self, ledger, in_row):
        outflow, inflow = sides(ledger, in_row=in_row)
        assert ledger.candidates() == [(outflow, inflow)]

    def test_the_same_account_is_not_one(self, ledger):
        ledger.card("out.csv", OUT_ROW)
        ledger.card("in.csv", IN_ROW)
        ledger.classify_ok(holding(ledger, "out.csv"), "transfer")
        assert ledger.candidates() == []

    @pytest.mark.parametrize(("out_type", "in_account_type", "found"), [
        ("card_payment", "savings", False),
        ("card_payment", "credit_card", True),
        ("loan_payment", "credit_card", False),
        ("loan_payment", "loan", True),
        ("investment_contribution", "retirement", True),
        ("investment_contribution", "loan", False),
    ])
    def test_a_payment_needs_the_account_it_pays(self, ledger, out_type, in_account_type, found):
        ledger.add_account("P", in_account_type)
        outflow, inflow = sides(ledger, out_type=out_type, in_account="P")
        assert ledger.candidates() == ([(outflow, inflow)] if found else [])

    def test_a_type_that_is_not_a_transfer_kind_on_the_other_side(self, ledger):
        outflow, inflow = sides(ledger)
        ledger.classify_ok(inflow, "refund", account="S")
        assert ledger.candidates() == []

    def test_a_card_payment_received_on_the_card_fits(self, ledger):  # X8
        ledger.add_account("P", "credit_card")
        outflow, inflow = sides(ledger, out_type="card_payment", in_account="P")
        ledger.classify_ok(inflow, "card_payment", account="P")
        assert ledger.candidates() == [(outflow, inflow)]
        ledger.match_ok(outflow, inflow, counterpart_account="P")
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_a_matched_transaction_is_not_one(self, ledger):
        matched(ledger)
        ledger.card("again.csv", "01/11/2026,SYNTHETIC MOVE IN AGAIN,,50.00", account="S")
        assert ledger.candidates() == []

    def test_the_list_shows_no_amounts_or_descriptions(self, ledger):
        sides(ledger)
        out = ledger.run("review", "transfers")[1]
        assert "50.00" not in out and "SYNTHETIC" not in out
        assert "(A, transfer) to transaction" in out and "(S, unclassified)" in out


class TestMatch:  # X1, X2
    def test_matching_changes_no_movement_type_or_source(self, ledger):
        outflow, inflow = sides(ledger)
        before = ledger.before_transfers()
        tables = (*SOURCE_TABLES, "ledger_transaction", "transaction_source",
                  "transaction_classification", "transaction_correction")
        dumped = ledger.dump(tables)
        code, out, err = ledger.match(outflow, inflow)
        assert code == 0, err
        assert f"transaction {outflow} to transaction {inflow}, binding 1 and 1 records" in out
        assert ledger.before_transfers() == before
        assert ledger.dump(tables) == dumped
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_derivation_never_reads_a_match(self, ledger):  # X2
        outflow, inflow = sides(ledger)
        conn = ledger.conn()
        before = [derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                         load_constraints(conn, account))
                  for account in (ledger.account_id("A"), ledger.account_id("S"))]
        conn.close()
        ledger.match_ok(outflow, inflow)
        conn = ledger.conn()
        after = [derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                        load_constraints(conn, account))
                 for account in (ledger.account_id("A"), ledger.account_id("S"))]
        conn.close()
        assert after == before

    def test_either_side_can_be_named_first(self, ledger):
        outflow, inflow = sides(ledger)
        ledger.match_ok(inflow, outflow, account="S", counterpart_account="A")
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_both_sides_show_it_and_change_their_tokens(self, ledger):
        outflow, inflow = sides(ledger)
        tokens = (ledger.transaction_revision(outflow), ledger.transaction_revision(inflow))
        match = ledger.match_ok(outflow, inflow)
        assert (ledger.transaction_revision(outflow), ledger.transaction_revision(inflow)) != tokens
        for transaction, side, other in ((outflow, "outflow", inflow), (inflow, "inflow", outflow)):
            out = ledger.transaction_show(transaction)
            assert f"Transfer match {match}, this transaction's side: {side}" in out
            assert f"Other side now: transaction {other}" in out
            assert "Transfer: both sides are one movement of money" in out

    def test_show_lists_both_sides(self, ledger):
        match, outflow, inflow = matched(ledger)
        out = ledger.transfer_show(match)
        assert "Status: active" in out
        assert re.search(rf"Outflow side:\n  Account: A .*\n  From transaction: {outflow}\n"
                         rf"  out.csv row 1, now in {outflow}", out)
        assert re.search(rf"Inflow side:\n  Account: S .*\n  From transaction: {inflow}\n"
                         rf"  in.csv row 1, now in {inflow}", out)


class TestRefusals:  # X3, X4
    def nothing_changes(self, ledger, attempt, message):
        before = ledger.dump()
        code, _, err = attempt()
        assert code == 2
        assert message in err, err
        assert ledger.dump() == before

    def test_an_unknown_transaction_on_either_side(self, ledger):
        outflow, inflow = sides(ledger)
        self.nothing_changes(ledger, lambda: ledger.match("nope", inflow, revision="t7-0"),
                             TRANSACTION_NOT_FOUND.format(transaction="nope"))
        self.nothing_changes(ledger, lambda: ledger.match(outflow, "nope",
                                                          counterpart_revision="t7-0"),
                             TRANSACTION_NOT_FOUND.format(transaction="nope"))

    def test_a_transaction_of_another_account_on_either_side(self, ledger):
        outflow, inflow = sides(ledger)
        ledger.add_account("T", "savings")
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow, account="T"),
                             TRANSACTION_WRONG_ACCOUNT.format(transaction=outflow))
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow, counterpart_account="T"),
                             TRANSACTION_WRONG_ACCOUNT.format(transaction=inflow))

    def test_one_account_named_twice(self, ledger):
        outflow, inflow = sides(ledger)
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow, counterpart_account="A"),
                             REFUSAL_BY_REASON[PAIR_SAME_ACCOUNT])

    def test_a_stale_token_on_either_side(self, ledger):
        outflow, inflow = sides(ledger)
        stale = "t7-0000000000000000"
        last_version = "t5-" + ledger.transaction_revision(outflow)[3:]
        for token in (stale, last_version):
            self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow, revision=token),
                                 STALE_TRANSACTION_REVISION.format(transaction=outflow))
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow,
                                                          counterpart_revision=stale),
                             STALE_TRANSACTION_REVISION.format(transaction=inflow))

    def test_a_token_taken_before_the_type_was_stated(self, ledger):
        outflow, inflow = sides(ledger, out_type=None)
        token = ledger.transaction_revision(outflow)
        ledger.classify_ok(outflow, "transfer")
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow, revision=token),
                             STALE_TRANSACTION_REVISION.format(transaction=outflow))

    @pytest.mark.parametrize("account", ["A", "S"])
    def test_a_stale_account_on_either_side_is_not_reconciled(self, ledger, account):  # X4
        outflow, inflow = sides(ledger)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ? WHERE account_id = ?",
                     ("0" * 64, ledger.account_id(account)))
        conn.close()
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow), STALE_ACCOUNT)

    @pytest.mark.parametrize(("in_row", "out_type", "reason"), [
        ("01/12/2026,SYNTHETIC MOVE IN,,50.01", "transfer", PAIR_AMOUNTS_DO_NOT_OFFSET),
        ("01/12/2026,SYNTHETIC MOVE IN,50.00,", "transfer", PAIR_AMOUNTS_DO_NOT_OFFSET),
        (IN_ROW, None, PAIR_NO_TRANSFER_TYPE),
        (IN_ROW, "card_payment", PAIR_TYPE_DOES_NOT_FIT),
        ("01/16/2026,SYNTHETIC MOVE IN,,50.00", "transfer", PAIR_DATES_TOO_FAR),
    ])
    def test_a_pair_that_is_not_a_candidate(self, ledger, in_row, out_type, reason):
        outflow, inflow = sides(ledger, in_row=in_row, out_type=out_type)
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow),
                             REFUSAL_BY_REASON[reason])

    def test_a_zero_amount(self, ledger):
        outflow, inflow = sides(ledger, out_row="01/10/2026,SYNTHETIC MOVE OUT,0.00,",
                                in_row="01/10/2026,SYNTHETIC MOVE IN,,0.00")
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow),
                             REFUSAL_BY_REASON[PAIR_AMOUNTS_DO_NOT_OFFSET])

    def test_a_side_already_matched(self, ledger):
        _, outflow, inflow = matched(ledger)
        ledger.card("again.csv", "01/11/2026,SYNTHETIC MOVE IN AGAIN,,50.00", account="S")
        again = holding(ledger, "again.csv")
        self.nothing_changes(ledger, lambda: ledger.match(outflow, again),
                             REFUSAL_BY_REASON[PAIR_ALREADY_MATCHED])
        self.nothing_changes(ledger, lambda: ledger.match(outflow, inflow),
                             REFUSAL_BY_REASON[PAIR_ALREADY_MATCHED])


class TestSurvival:  # X5
    def test_a_repeat_import_reconcile_and_an_unrelated_file(self, ledger):
        matched(ledger)
        found = ledger.matches()
        ledger.load_path(ledger.folder / "out.csv")
        ledger.load_path(ledger.folder / "in.csv", account="S")
        assert ledger.run("reconcile")[0] == 0
        ledger.card("other.csv", "02/20/2026,SYNTHETIC GROCER,9.00,", account="S")
        assert ledger.matches() == found == [("applied", ("out.csv",), ("in.csv",))]

    def test_a_rules_change(self, ledger):
        matched(ledger)
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        for account in ("A", "S"):
            reconcile_account(conn, ledger.account_id(account),
                              replace(DEFAULT_RULES, date_window_days=5))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_a_re_export_joining_a_side_keeps_it_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.card("in.csv", "01/12/2026,SYNTHETIC MOVE IN,,5.00", account="S")
        outflow, inflow = holding(ledger, "a.csv"), holding(ledger, "in.csv")
        ledger.classify_ok(outflow, "transfer")
        match = ledger.match_ok(outflow, inflow)
        token = ledger.match_revision(match)
        ledger.checking("b.csv", ID_ROW)
        assert ledger.matches() == [("applied", ("a.csv", "b.csv"), ("in.csv",))]
        outflow_side = ledger.transfer_show(match).split("Outflow side:")[1].split("Inflow side:")[0]
        assert "a.csv row 1" in outflow_side and "b.csv" not in outflow_side
        assert ledger.match_revision(match) != token


def split_after_matching(ledger):
    """a and b merged by a reliable ID and matched, then c, which makes the IDs conflict."""
    ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
    ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
    ledger.card("in.csv", "01/12/2026,SYNTHETIC MOVE IN,,5.00", account="S")
    (outflow,) = ledger.merges()
    ledger.classify_ok(outflow, "transfer")
    match = ledger.match_ok(outflow, holding(ledger, "in.csv"))
    ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
    return match


class TestOutcomes:  # X6, X7
    def test_an_automatic_split_of_a_side_changes_its_basis(self, ledger):
        match = split_after_matching(ledger)
        assert ledger.matches() == [("basis_changed", (), ())]
        assert "1 transfer matches no longer apply, because a side's bound records are now in " \
               "several transactions" in ledger.totals()
        assert "Transfer: a side's bound records are now in several transactions" in \
            ledger.transfer_show(match)
        assert ledger.transfers_section().startswith("  Matched: 0 pairs, moving 0.00\n")

    def test_undoing_a_separation_can_bring_two_matches_into_one_transaction(self, ledger):
        merged, records = merged_two(ledger)
        separation = ledger.separate_ok(merged, [records["a.csv"]], [records["b.csv"]])
        ledger.card("in.csv", "01/10/2026,SYNTHETIC MOVE IN,,6.50",
                    "01/11/2026,SYNTHETIC MOVE IN,,6.50", account="S")
        for name, inflow in zip(("a.csv", "b.csv"), rows_of(ledger, "in.csv")):
            ledger.classify_ok(inflow, "transfer", account="S")
            ledger.match_ok(holding(ledger, name), inflow)
        code, out, _ = ledger.undo(separation)
        assert code == 0
        assert "Transfer matches or one-sided transfers that no longer apply" in out
        assert "is covered: 2." in out
        assert ledger.matches() == [("conflict", (), ()), ("conflict", (), ())]
        assert "2 transfer matches no longer apply, because a transaction holds records of two " \
               "matches" in ledger.totals()

    def test_undoing_a_correction_can_make_the_amounts_differ(self, ledger):
        ledger.card("out.csv", "01/10/2026,SYNTHETIC MOVE OUT,6.50,")
        ledger.card("in.csv", IN_ROW, account="S")
        outflow, inflow = holding(ledger, "out.csv"), holding(ledger, "in.csv")
        correction = ledger.correct_ok(outflow, "amount", "-50.00")
        ledger.classify_ok(outflow, "transfer")
        ledger.match_ok(outflow, inflow)
        code, out, _ = ledger.undo_correction(correction)
        assert code == 0
        assert "Transfer matches or one-sided transfers that no longer apply, because records " \
               "split or reach another, amounts no longer offset, a type no longer fits, or a " \
               "counterpart now shows or is covered: 1" in out
        assert ledger.matches() == [("amounts_differ", (), ())]
        assert "because the amounts no longer offset exactly" in ledger.totals()

    def test_sides_that_swap_direction_no_longer_apply(self, ledger):
        ledger.card("out.csv", "01/10/2026,SYNTHETIC MOVE OUT,,50.00")
        ledger.card("in.csv", "01/12/2026,SYNTHETIC MOVE IN,50.00,", account="S")
        outflow, inflow = holding(ledger, "out.csv"), holding(ledger, "in.csv")
        corrections = [ledger.correct_ok(outflow, "amount", "-50.00"),
                       ledger.correct_ok(inflow, "amount", "50.00", account="S")]
        ledger.classify_ok(outflow, "transfer")
        ledger.match_ok(outflow, inflow)
        assert ledger.undo_correction(corrections[0])[0] == 0
        assert ledger.undo_correction(corrections[1], account="S")[0] == 0
        # The amounts offset again, but money now leaves the side stated as the inflow.
        assert ledger.matches() == [("amounts_differ", (), ())]

    def test_a_correction_that_stops_the_amounts_offsetting_refuses(self, ledger):
        _, outflow, inflow = matched(ledger)
        before = ledger.dump()
        code, _, err = ledger.correct(inflow, "amount", "49.00", account="S")
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before
        ledger.correct_ok(outflow, "description", "SYNTHETIC MOVE")

    def test_undoing_a_classification_can_restore_a_type_that_differs(self, ledger):
        outflow, inflow = sides(ledger, out_type="purchase")
        purchase = ledger.run("review", "classifications")[1].split()[1].rstrip(":")
        transfer = ledger.classify_ok(outflow, "transfer", supersedes=purchase)
        ledger.match_ok(outflow, inflow)
        code, out, _ = ledger.undo_classification(transfer)
        assert code == 0 and "Transfer matches or one-sided transfers that no longer apply" in out
        assert ledger.matches() == [("type_differs", (), ())]

    def test_classifying_a_side_against_the_match_refuses(self, ledger):
        _, outflow, inflow = matched(ledger)
        before = ledger.dump()
        code, _, err = ledger.classify(inflow, "income", account="S")
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before
        ledger.classify_ok(inflow, "transfer", account="S")
        assert ledger.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_confirming_two_matched_transactions_as_one_refuses(self, ledger):  # X7
        ledger.card("a.csv", OUT_ROW, extra=FIRST_HALF)
        ledger.card("b.csv", OUT_ROW, extra=SECOND_HALF)
        ledger.card("in.csv", IN_ROW, "01/11/2026,SYNTHETIC MOVE IN,,50.00", account="S")
        (item,) = ledger.items()
        one, two = ledger.transactions(item)
        for outflow, inflow in zip((one, two), rows_of(ledger, "in.csv")):
            ledger.classify_ok(outflow, "transfer")
            ledger.match_ok(outflow, inflow)
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before

    def test_separating_a_matched_side_refuses(self, ledger):  # X7
        outflow, records = merged_three(ledger)
        ledger.card("in.csv", "01/10/2026,SYNTHETIC MOVE IN,,6.50", account="S")
        # The type is on the other side, so that only the match binds the records separated.
        ledger.classify_ok(holding(ledger, "in.csv"), "transfer", account="S")
        ledger.match_ok(outflow, holding(ledger, "in.csv"))
        before = ledger.dump()
        code, _, err = ledger.separate(outflow, [records["a.csv"]],
                                       [records["b.csv"], records["c.csv"]])
        assert code == 2 and LEAVES_TRANSFER_UNSETTLED in err
        assert ledger.dump() == before

    def test_undoing_a_completion_waits_for_a_match(self, ledger):  # X7
        ledger.card("out.csv", CAFE_NO_AMOUNT)
        (unresolved,) = ledger.unresolved()
        resolution = ledger.complete_ok(unresolved, amount="-50.00")
        ledger.card("in.csv", IN_ROW, account="S")
        outflow = holding(ledger, "out.csv")
        ledger.classify_ok(holding(ledger, "in.csv"), "transfer", account="S")
        match = ledger.match_ok(outflow, holding(ledger, "in.csv"))
        before = ledger.dump()
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2
        assert COMPLETION_BOUND.format(entries=f"transfer match {match}") in err
        assert ledger.dump() == before
        assert f"Refused while transfer match {match} binds the record" in \
            ledger.resolution_show(resolution)


class TestUndo:  # X9
    def test_undo_keeps_it_on_record_and_frees_both_sides(self, ledger):
        match, outflow, inflow = matched(ledger)
        code, out, err = ledger.undo_match(match, account="S")
        assert code == 0, err
        assert "Both transactions are unmatched again" in out
        assert ledger.matches() == []
        assert ledger.candidates() == [(outflow, inflow)]
        out = ledger.transfer_show(match)
        assert "Status: undone" in out and "Revision:" not in out
        assert ledger.dump(TRANSFER_TABLES)["transfer_match_record"]

    def test_refusals(self, ledger):
        match, _, _ = matched(ledger)
        ledger.add_account("T", "savings")
        before = ledger.dump()
        token = ledger.match_revision(match)
        for (code, _, err), message in (
            (ledger.undo_match("nope", revision="m1-0"),
             "transfer match or one-sided transfer not found"),
            (ledger.undo_match(match, account="T", revision=token), MATCH_WRONG_ACCOUNT),
            (ledger.undo_match(match, revision="m1-0000000000000000"), STALE_MATCH_REVISION),
        ):
            assert code == 2 and message in err
        assert ledger.dump() == before
        assert ledger.undo_match(match)[0] == 0
        code, _, err = ledger.undo_match(match, revision=token)
        assert code == 2 and MATCH_NOT_ACTIVE in err

    @pytest.mark.parametrize("account", ["A", "S"])
    def test_a_stale_account_on_either_side_refuses(self, ledger, account):
        match, _, _ = matched(ledger)
        token = ledger.match_revision(match)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ? WHERE account_id = ?",
                     ("0" * 64, ledger.account_id(account)))
        conn.close()
        before = ledger.dump()
        code, _, err = ledger.undo_match(match, revision=token)
        assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before
        assert "undo will be refused until it is" in ledger.transfer_show(match)

    def test_undo_settles_another_match_without_refusing(self, ledger):
        match = split_after_matching(ledger)
        assert ledger.undo_match(match)[0] == 0
        assert ledger.matches() == []


class TestTokens:  # X10
    def test_a_transaction_token_covers_the_other_side(self, ledger):
        match, outflow, first = matched(ledger)
        ledger.card("second.csv", "01/11/2026,SYNTHETIC MOVE IN AGAIN,,50.00", account="S")
        second = holding(ledger, "second.csv")
        token = ledger.transaction_revision(outflow)
        assert ledger.undo_match(match)[0] == 0
        ledger.match_ok(outflow, second)
        # The same records here, matched with other records there.
        assert ledger.transaction_revision(outflow) != token

    def test_the_version_is_pinned(self, ledger):
        assert transfer_evidence.MATCH_REVISION_VERSION == 1
        match, _, _ = matched(ledger)
        assert re.fullmatch(r"m1-[0-9a-f]{16}", ledger.match_revision(match))

    def test_an_unrelated_file_leaves_it_unchanged(self, ledger):
        match, _, _ = matched(ledger)
        token = ledger.match_revision(match)
        ledger.card("other.csv", "02/20/2026,SYNTHETIC GROCER,9.00,")
        ledger.card("other.csv", "02/21/2026,SYNTHETIC GROCER,8.00,", account="S")
        assert ledger.match_revision(match) == token

    def test_equal_in_two_ledgers(self, tmp_path, capsys):
        tokens = []
        for number in range(2):
            folder = tmp_path / str(number)
            folder.mkdir()
            ledger = TransferLedger(folder, capsys)
            ledger.add_account("S", "savings")
            match, outflow, inflow = matched(ledger)
            tokens.append((ledger.match_revision(match), ledger.transaction_revision(outflow),
                           ledger.transaction_revision(inflow)))
        assert tokens[0] == tokens[1]


class TestTotals:  # X13
    def test_matches_candidates_and_unpaired_transfer_kinds(self, ledger):
        match, _, _ = matched(ledger)
        ledger.card("next.csv", "02/10/2026,SYNTHETIC MOVE OUT,20.00,")
        ledger.card("next-in.csv", "02/11/2026,SYNTHETIC MOVE IN,,20.00", account="S")
        ledger.classify_ok(holding(ledger, "next.csv"), "transfer")
        ledger.card("alone.csv", "03/10/2026,SYNTHETIC MOVE OUT,7.00,")
        ledger.classify_ok(holding(ledger, "alone.csv"), "transfer")
        assert ledger.transfers_section() == (
            "  Matched: 1 pairs, moving 50.00\n"
            "  In a candidate pair, not matched: 2 transactions\n"
            "  One-sided, the other side not in the ledger: 0 transactions, 0.00 out and 0.00 in\n"
            "  Of a transfer kind with no match, candidate or one-sided transfer: 1 transactions\n"
        )
        assert ledger.transfers_section("S") == (
            "  Matched: 1 pairs, moving 50.00\n"
            "  In a candidate pair, not matched: 1 transactions\n"
            "  One-sided, the other side not in the ledger: 0 transactions, 0.00 out and 0.00 in\n"
            "  Of a transfer kind with no match, candidate or one-sided transfer: 0 transactions\n"
        )
        assert "2 transactions may be transfers between your accounts and are not matched" in \
            ledger.totals()
        assert ledger.undo_match(match)[0] == 0
        assert ledger.transfers_section().startswith(
            "  Matched: 0 pairs, moving 0.00\n  In a candidate pair, not matched: 4 transactions\n")

    def test_an_account_with_no_match_or_candidate(self, ledger):
        matched(ledger)
        ledger.card("next.csv", "02/10/2026,SYNTHETIC MOVE OUT,20.00,")
        ledger.card("next-in.csv", "02/11/2026,SYNTHETIC MOVE IN,,20.00", account="S")
        ledger.classify_ok(holding(ledger, "next.csv"), "transfer")
        ledger.add_account("T", "savings")
        ledger.card("t.csv", "02/20/2026,SYNTHETIC GROCER,9.00,", account="T")
        assert ledger.candidates("T") == []
        assert ledger.transfers_section("T") == (
            "  Matched: 0 pairs, moving 0.00\n"
            "  In a candidate pair, not matched: 0 transactions\n"
            "  One-sided, the other side not in the ledger: 0 transactions, 0.00 out and 0.00 in\n"
            "  Of a transfer kind with no match, candidate or one-sided transfer: 0 transactions\n"
        )

    def test_an_empty_ledger(self, ledger):
        assert ledger.transfers_section() == (
            "  Matched: 0 pairs, moving 0.00\n"
            "  In a candidate pair, not matched: 0 transactions\n"
            "  One-sided, the other side not in the ledger: 0 transactions, 0.00 out and 0.00 in\n"
            "  Of a transfer kind with no match, candidate or one-sided transfer: 0 transactions\n"
        )
