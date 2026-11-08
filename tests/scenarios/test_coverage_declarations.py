"""Declaring a document's coverage after import, end to end, using synthetic data only (D-051)."""

import re
from dataclasses import replace

import pytest
from test_decisions import CAFE, CHECKING_HEADER, OTHER, WHOLE_MONTH
from test_resolutions import ResolutionLedger
from test_supersession import holding

from personal_finance.reconcile.coverage_declarations import (
    BASIS_UNAVAILABLE,
    CHANGES_NOTHING,
    COVERAGE_INVALID,
    DECLARATION_NOT_ACTIVE,
    DECLARATION_NOT_FOUND,
    DECLARATION_SUPERSEDED,
    DECLARATION_WRONG_ACCOUNT,
    DOCUMENT_NOT_FOUND,
    DOCUMENT_WRONG_ACCOUNT,
    KIND_UNSUPPORTED,
    METADATA_STATED,
    STALE_COVERAGE_REVISION,
    STALE_DECLARATION_REVISION,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT
from personal_finance.reports import coverage_evidence

MONTH = {"start": "2026-01-01", "end": "2026-01-20", "basis": "posting"}
METADATA_COMPLETE = ("# coverage-kind: complete\n# coverage-start: 2026-01-01\n"
                     "# coverage-end: 2026-01-31\n# coverage-basis: transaction\n")


class CoverageLedger(ResolutionLedger):
    def document_id(self, name):
        listed = self.run("documents")[1]
        return re.search(rf"^Document (\S+): {re.escape(name)}:", listed, re.MULTILINE)[1]

    def coverage_show(self, name):
        code, out, err = self.run("review", "coverage", "show", self.document_id(name))
        assert code == 0, err
        return out

    def coverage_revision(self, name):
        return re.search(r"Revision: (v1-[0-9a-f]{16})", self.coverage_show(name))[1]

    def declare(self, name, kind="complete", revision=None, account="A", start=None, end=None,
                basis=None):
        words = ["review", "coverage", "declare", self.document_id(name), "--account", account,
                 "--revision", revision or self.coverage_revision(name), "--coverage-kind", kind]
        for option, value in (("--coverage-start", start), ("--coverage-end", end),
                              ("--coverage-basis", basis)):
            if value is not None:
                words += [option, value]
        return self.run(*words)

    def declare_ok(self, name, kind="complete", **interval):
        code, out, err = self.declare(name, kind, **interval)
        assert code == 0, err
        return re.search(r"Declaration (\S+) recorded", out)[1]

    def undo_token(self, name):
        return re.search(r"Revision: (k1-[0-9a-f]{16})", self.coverage_show(name))[1]

    def undo_declaration(self, declaration, revision, account="A"):
        return self.run("review", "coverage", "undo", declaration, "--account", account,
                        "--revision", revision)


@pytest.fixture
def ledger(tmp_path, capsys):
    return CoverageLedger(tmp_path, capsys)


def unknown_beside_complete(ledger):
    """The same purchase in a.csv, of unknown coverage, and b.csv, declared complete at import."""
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)


def both_complete(ledger):
    ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
    ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)


class TestDeclare:  # K1, K2, K3
    def test_declaring_complete_coverage_lets_the_pair_merge(self, ledger):  # K1
        unknown_beside_complete(ledger)
        assert ledger.count() == 2 and ledger.net() == "-13.00"
        claim = ledger.dump(("document_coverage",))
        code, out, err = ledger.declare("a.csv", **MONTH)
        assert code == 0, err
        assert "Transactions: 2 before, 1 now." in out
        assert ledger.count() == 1 and ledger.net() == "-6.50"
        assert "exact_coverage_pair" in ledger.link_rules()
        assert ledger.dump(("document_coverage",)) == claim

    def test_withdrawing_a_claim_made_at_import_splits_its_merges(self, ledger):  # K2
        both_complete(ledger)
        assert ledger.count() == 1
        ledger.declare_ok("a.csv", "unknown")
        assert ledger.count() == 2 and ledger.net() == "-13.00"
        (item,) = ledger.items("cross_document_candidates")
        assert "coverage_unknown" in ledger.show(item)

    def test_metadata_stated_coverage_can_only_be_withdrawn(self, ledger):  # K3
        path = ledger.folder / "m.csv"
        path.write_text(METADATA_COMPLETE + CHECKING_HEADER
                        + "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED\n")
        ledger.load_path(path, layout="synthetic_checking_v1")
        before = ledger.dump()
        code, _, err = ledger.declare("m.csv", start="2026-01-01", end="2026-01-31",
                                      basis="transaction")
        assert code == 2 and METADATA_STATED in err
        assert ledger.dump() == before
        ledger.declare_ok("m.csv", "unknown")
        assert "coverage unknown, declared after import, claimed at import: complete" in (
            ledger.run("documents")[1])


class TestRefusals:  # K4, K5
    def refused(self, ledger, attempt, message):
        before = ledger.dump()
        code, _, err = attempt()
        assert code == 2 and message in err, err
        assert ledger.dump() == before

    def test_wrong_account_and_unknown_document(self, ledger):
        unknown_beside_complete(ledger)
        ledger.add_account("B")
        self.refused(ledger, lambda: ledger.declare("a.csv", account="B", **MONTH),
                     DOCUMENT_WRONG_ACCOUNT)
        self.refused(ledger, lambda: ledger.run(
            "review", "coverage", "declare", "nope", "--account", "A", "--revision", "v1-0",
            "--coverage-kind", "unknown"), DOCUMENT_NOT_FOUND)

    def test_a_stale_token(self, ledger):
        unknown_beside_complete(ledger)
        token = ledger.coverage_revision("a.csv")
        ledger.declare_ok("a.csv", **MONTH)
        self.refused(ledger, lambda: ledger.declare("a.csv", "unknown", revision=token),
                     STALE_COVERAGE_REVISION)

    @pytest.mark.parametrize(("kind", "interval", "message"), [
        ("partial", MONTH, KIND_UNSUPPORTED),
        ("complete", {"start": "2026-01-20", "end": "2026-01-01", "basis": "posting"},
         COVERAGE_INVALID),
        ("complete", {"start": "2026-01-01", "end": "2026-01-20"}, COVERAGE_INVALID),
        ("complete", {"start": "2026-01-01", "end": "2026-02-30", "basis": "posting"},
         COVERAGE_INVALID),
        ("unknown", MONTH, COVERAGE_INVALID),
        ("complete", {**MONTH, "basis": "transaction"}, BASIS_UNAVAILABLE),
        ("unknown", {}, CHANGES_NOTHING),
    ])
    def test_an_invalid_or_empty_declaration(self, ledger, kind, interval, message):
        unknown_beside_complete(ledger)
        self.refused(ledger, lambda: ledger.declare("a.csv", kind, **interval), message)

    def test_the_same_coverage_again_changes_nothing(self, ledger):
        both_complete(ledger)
        self.refused(ledger, lambda: ledger.declare("a.csv", **MONTH), CHANGES_NOTHING)

    def test_a_stale_account_is_refused_and_not_reconciled(self, ledger):  # K5
        unknown_beside_complete(ledger)
        token = ledger.coverage_revision("a.csv")
        declaration = ledger.declare_ok("a.csv", **MONTH)
        undo_token = ledger.undo_token("a.csv")
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        before = ledger.dump()
        for code, _, err in (ledger.declare("a.csv", "unknown", revision=token),
                             ledger.undo_declaration(declaration, undo_token)):
            assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before


class TestChains:  # K6, K7
    def test_only_the_newest_applies_and_undo_steps_back(self, ledger):
        unknown_beside_complete(ledger)
        first = ledger.declare_ok("a.csv", **MONTH)
        assert ledger.count() == 1
        second = ledger.declare_ok("a.csv", "unknown")
        assert ledger.count() == 2
        code, _, err = ledger.undo_declaration(first, "k1-0000000000000000")
        assert code == 2 and DECLARATION_SUPERSEDED.format(newest=second) in err
        code, out, err = ledger.undo_declaration(second, ledger.undo_token("a.csv"))
        assert code == 0, err
        assert f"Declaration {first} applies again." in out
        assert ledger.count() == 1
        code, out, _ = ledger.undo_declaration(first, ledger.undo_token("a.csv"))
        assert code == 0 and "The claim at import applies again." in out
        assert ledger.count() == 2
        history = ledger.run("review", "coverage", "history")[1]
        assert history.count(": undone, ") == 2

    def test_undo_refusals(self, ledger):
        unknown_beside_complete(ledger)
        declaration = ledger.declare_ok("a.csv", **MONTH)
        token = ledger.undo_token("a.csv")
        ledger.add_account("B")
        for result, message in (
            (ledger.undo_declaration("nope", "k1-0"), DECLARATION_NOT_FOUND),
            (ledger.undo_declaration(declaration, token, account="B"), DECLARATION_WRONG_ACCOUNT),
            (ledger.undo_declaration(declaration, "k1-0000000000000000"),
             STALE_DECLARATION_REVISION),
        ):
            assert result[0] == 2 and message in result[2]
        assert ledger.undo_declaration(declaration, token)[0] == 0
        code, _, err = ledger.undo_declaration(declaration, token)
        assert code == 2 and DECLARATION_NOT_ACTIVE in err

    @pytest.mark.parametrize("import_since", [False, True])
    def test_undoing_equals_never_declaring(self, ledger, tmp_path, capsys, import_since):  # K7
        unknown_beside_complete(ledger)
        declaration = ledger.declare_ok("a.csv", **MONTH)
        if import_since:
            ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.undo_declaration(declaration, ledger.undo_token("a.csv"))[0] == 0
        folder = tmp_path / "plain"
        folder.mkdir()
        plain = CoverageLedger(folder, capsys)
        unknown_beside_complete(plain)
        if import_since:
            plain.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.view() == plain.view()


class TestEquivalence:  # K8, K9
    def test_declaring_after_import_gives_the_ledger_declaring_at_import_gives(
            self, ledger, tmp_path, capsys):
        unknown_beside_complete(ledger)
        ledger.card("c.csv", CAFE, OTHER)
        ledger.declare_ok("a.csv", start="2026-01-01", end="2026-01-20", basis="posting")
        folder = tmp_path / "at_import"
        folder.mkdir()
        other = CoverageLedger(folder, capsys)
        other.card("a.csv", CAFE, extra=WHOLE_MONTH)
        other.card("b.csv", CAFE, extra=WHOLE_MONTH)
        other.card("c.csv", CAFE, OTHER)
        view, expected = ledger.view(), other.view()
        # Item tokens cover declared coverage, and totals disclose it, which only the first ledger
        # has (D-051).
        del view["revisions"], expected["revisions"]
        assert view["movement"].documents_with_declared_coverage == 1
        view["movement"] = replace(view["movement"], documents_with_declared_coverage=0)
        assert view == expected

    def test_a_repeat_import_is_compared_with_the_coverage_in_effect(self, ledger):  # K9
        unknown_beside_complete(ledger)
        ledger.declare_ok("a.csv", **MONTH)
        out = ledger.load_path(ledger.folder / "a.csv", *WHOLE_MONTH)
        assert "already imported" in out
        code, out, _ = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                  str(ledger.folder / "a.csv"), "--declare-complete-coverage",
                                  "--coverage-start", "2026-01-02", "--coverage-end", "2026-01-20",
                                  "--coverage-basis", "posting")
        assert code == 1 and "coverage_conflict" in out and "review coverage declare" in out


class TestDecisionsAndCorrections:  # K10
    def test_a_rejection_withholds_the_merge_a_declaration_would_make(self, ledger):
        unknown_beside_complete(ledger)
        (item,) = ledger.items()
        one, two = ledger.transactions(item)
        ledger.reject_ok(item, (one, two))
        ledger.declare_ok("a.csv", **MONTH)
        assert ledger.count() == 2
        assert "Decision conflicts: 1" in ledger.totals()

    def test_disagreeing_corrections_joined_by_a_declaration_are_reported(self, ledger):
        unknown_beside_complete(ledger)
        ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        ledger.correct_ok(holding(ledger, "b.csv"), "amount", "-5.00")
        code, out, err = ledger.declare("a.csv", **MONTH)
        assert code == 0, err
        assert "Corrected fields now using their source value" in out
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "conflict")]


class TestTokens:  # K11
    def test_versions_and_definitions_are_pinned(self, ledger):
        assert coverage_evidence.DOCUMENT_COVERAGE_REVISION_VERSION == 1
        assert coverage_evidence.DECLARATION_REVISION_VERSION == 1
        unknown_beside_complete(ledger)
        assert ledger.coverage_revision("a.csv") == "v1-bb1b708a2ff2dd50"
        ledger.declare_ok("a.csv", **MONTH)
        assert ledger.undo_token("a.csv") == "k1-141e501092a4533f"

    def test_an_unrelated_file_leaves_the_undo_token_unchanged(self, ledger):
        unknown_beside_complete(ledger)
        ledger.declare_ok("a.csv", **MONTH)
        token = ledger.undo_token("a.csv")
        ledger.card("x.csv", OTHER)
        assert ledger.undo_token("a.csv") == token

    def test_a_related_file_changes_it(self, ledger):
        unknown_beside_complete(ledger)
        declaration = ledger.declare_ok("a.csv", **MONTH)
        token = ledger.undo_token("a.csv")
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.undo_token("a.csv") != token
        code, _, err = ledger.undo_declaration(declaration, token)
        assert code == 2 and STALE_DECLARATION_REVISION in err

    def test_a_declaration_changes_item_tokens(self, ledger):
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        before = ledger.revision(item)
        ledger.declare_ok("a.csv", start="2026-02-01", end="2026-02-20", basis="posting")
        (still,) = ledger.items()
        assert ledger.revision(still) != before


class TestDisplays:  # K14, K15
    def test_displays_keep_the_claim_apart_and_show_no_values(self, ledger):
        unknown_beside_complete(ledger)
        code, out, _ = ledger.declare("a.csv", start="2026-02-01", end="2026-02-20", basis="posting")
        assert code == 0
        (item,) = ledger.items()
        shown = ledger.show(item)
        assert "Declared after import, which matching uses: complete 2026-02-01 to 2026-02-20" in shown
        assert "Coverage kind: unknown" in shown
        documents = ledger.run("documents")[1]
        assert "coverage complete 2026-02-01 to 2026-02-20, posting basis, evidence user_declared" in documents
        assert "declared after import, claimed at import: unknown" in documents
        assert "Documents whose coverage you declared after import: 1" in ledger.totals()
        for text in (out, ledger.coverage_show("a.csv"), ledger.run("review", "coverage", "history")[1]):
            assert "6.50" not in text and "SYNTHETIC CAFE" not in text
