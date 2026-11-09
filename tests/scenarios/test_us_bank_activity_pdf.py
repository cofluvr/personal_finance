"""U.S. Bank's Recent Activity List for a credit card, printed to PDF (M7.2, D-060 as amended).

The printouts are written here, laid out as the owner's: a header on every page, `Posted`, then
each entry's line followed by its account line, which can fall after a page break. Every value is
invented. Whether pypdf reads the real printout the same way is D-059 point F's check.
"""

import io

import pypdf
import pytest

from personal_finance.cli import main
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import LAYOUTS, US_BANK_CARD_ACTIVITY_PDF_V1 as LAYOUT
from personal_finance.ingest.pdf_reader import EXTRACTOR_VERSION
from personal_finance.ingest.pipeline import import_files
from personal_finance.reports.totals import account_movement
from synthetic_pdf import pdf_bytes

LAST4 = "9135"
HEADER = ((20, "11/5/26, 7:12 PM"), (330, "Recent Activity List | U.S. Bank"))
POSTED = ((40, "Posted"),)


def entry(day, description, amount):
    return ((40, day), (140, description), (480, amount))


def account_line(last4=LAST4):
    return ((480, f"Credit Card ...{last4}"),)


# The page break falls between the fourth entry and its account line, as in the owner's printout.
PAGES = [
    [HEADER, POSTED,
     entry("11/04/2026", "Internet Payment Thank You", "-$125.40"), account_line(),
     entry("10/30/2026", "SYNTHETIC GROCER 01", "$3.19"), account_line(),
     entry("10/30/2026", "SYNTHETIC GROCER 01", "$3.19"), account_line(),
     entry("10/27/2026", "SYNTHETIC HARDWARE", "$1,204.55")],
    [HEADER, account_line(),
     entry("10/20/2026", "Rewards Redeemed for Statement Credit", "-$12.00"), account_line(),
     entry("10/02/2026", "SYNTHETIC GROCER 01", "-$48.25"), account_line()],
]
EXPECTED = [
    ("2026-11-04", 12540, "Internet Payment Thank You"),
    ("2026-10-30", -319, "SYNTHETIC GROCER 01"),
    ("2026-10-30", -319, "SYNTHETIC GROCER 01"),
    ("2026-10-27", -120455, "SYNTHETIC HARDWARE"),
    ("2026-10-20", 1200, "Rewards Redeemed for Statement Credit"),
    ("2026-10-02", 4825, "SYNTHETIC GROCER 01"),
]


@pytest.fixture
def account(conn):
    return add_account(conn, "card", "credit_card", LAST4)


def add_account(conn, account_id, account_type, last4):
    conn.execute(
        """INSERT INTO account (id, display_name, account_type, last4) VALUES (?, ?, ?, ?)""",
        (account_id, account_id, account_type, last4),
    )
    return account_id


def import_pdf(conn, tmp_path, pages, name="activity.pdf", account_id="card", declared=None,
               content=None):
    path = tmp_path / name
    path.write_bytes(content if content is not None else pdf_bytes(pages))
    (result,) = import_files(conn, [path], account_id=account_id, layout=LAYOUT,
                             declared_coverage=declared)
    return result


def parsed_rows(conn):
    return conn.execute(
        """SELECT record.raw_json, parse.reason_code, parse.posting_date, parse.amount_cents,
                  parse.description, parse.settlement_status, parse.external_id
           FROM source_record record JOIN record_parse parse ON parse.source_record_id = record.id
           ORDER BY record.record_index"""
    ).fetchall()


def stored_documents(conn):
    return conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0]


def with_line(page, position, line):
    pages = [list(lines) for lines in PAGES]
    pages[page].insert(position, line)
    return pages


class TestRows:  # D5
    def test_every_entry_parses_as_expected(self, conn, account, tmp_path):
        result = import_pdf(conn, tmp_path, PAGES)
        assert (result.outcome, result.valid_records, result.unresolved_records) == (
            "imported", 6, 0)
        rows = parsed_rows(conn)
        assert [(posting, cents, description) for _, _, posting, cents, description, _, _ in rows
                ] == EXPECTED
        assert {(reason, status, external_id) for _, reason, _, _, _, status, external_id in rows
                } == {(None, "posted", None)}

    def test_a_charge_is_money_out_and_a_payment_or_credit_money_in(self):
        assert min(cents for _, cents, _ in EXPECTED) < 0 < max(cents for _, cents, _ in EXPECTED)

    def test_a_row_keeps_its_page_and_both_lines(self, conn, account, tmp_path):
        import_pdf(conn, tmp_path, PAGES)
        raw = [row[0] for row in parsed_rows(conn)]
        assert raw[3].startswith('["1","') and "SYNTHETIC HARDWARE" in raw[3]
        assert raw[3].endswith(f'Credit Card ...{LAST4}"]')
        assert raw[4].startswith('["2","')

    def test_the_document_is_stored_as_a_pdf_with_the_extractor_in_its_parser_version(
            self, conn, account, tmp_path):  # D4
        import_pdf(conn, tmp_path, PAGES)
        assert conn.execute("SELECT format, layout_id FROM source_document").fetchall() == [
            ("pdf", "us_bank_card_activity_pdf_v1")]
        assert conn.execute(
            """SELECT parser_version, external_id_namespace, external_id_guarantee
               FROM document_interpretation"""
        ).fetchall() == [(f"1+{EXTRACTOR_VERSION}", None, "none")]
        assert EXTRACTOR_VERSION == f"pypdf-{pypdf.__version__}"


class TestUnresolvedRows:  # D6
    @pytest.mark.parametrize("line", [((40, "Pending"),), ((40, "Page 1 of 2"),),
                                      ((40, "13/45/2026   NOT AN ENTRY")
                                        ,)], ids=["heading", "footer", "almost an entry"])
    def test_an_unknown_line_is_an_unresolved_row_keeping_its_text(self, conn, account,
                                                                   tmp_path, line):
        result = import_pdf(conn, tmp_path, with_line(0, 4, line))
        assert (result.valid_records, result.unresolved_records) == (6, 1)
        unresolved = [row for row in parsed_rows(conn) if row[1]]
        assert [row[1] for row in unresolved] == ["unrecognized_line"]
        assert line[0][1] in unresolved[0][0]

    def test_an_entry_without_its_account_line_is_unresolved(self, conn, account, tmp_path):
        pages = [list(lines) for lines in PAGES]
        del pages[0][3]
        result = import_pdf(conn, tmp_path, pages)
        assert (result.valid_records, result.unresolved_records) == (5, 1)
        assert [row[1] for row in parsed_rows(conn) if row[1]] == ["missing_account_line"]

    def test_a_last_entry_without_its_account_line_is_unresolved_not_lost(self, conn, account,
                                                                            tmp_path):
        pages = [list(lines) for lines in PAGES]
        pages[1].append(entry("10/01/2026", "SYNTHETIC GROCER 01", "$2.00"))
        result = import_pdf(conn, tmp_path, pages)
        assert (result.valid_records, result.unresolved_records) == (6, 1)
        assert [row[1] for row in parsed_rows(conn) if row[1]] == ["missing_account_line"]

    def test_an_account_line_with_no_entry_is_unresolved(self, conn, account, tmp_path):
        result = import_pdf(conn, tmp_path, with_line(0, 2, account_line()))
        assert [row[1] for row in parsed_rows(conn) if row[1]] == ["unrecognized_line"]
        assert result.valid_records == 6

    def test_an_impossible_date_is_invalid(self, conn, account, tmp_path):
        pages = with_line(1, 4, account_line())
        pages[1].insert(4, entry("02/30/2026", "SYNTHETIC SHOP", "$1.00"))
        result = import_pdf(conn, tmp_path, pages)
        assert [row[1] for row in parsed_rows(conn) if row[1]] == ["invalid_date"]
        assert result.unresolved_records == 1


class TestStructure:  # D7
    @pytest.mark.parametrize("pages", [
        [PAGES[0][1:], PAGES[1]],
        [PAGES[0], PAGES[1][1:]],
        [[PAGES[0][0], *PAGES[0][2:]], PAGES[1]],
        [[((20, "11/5/26, 7:12 PM"), (330, "Recent Activity | Another Bank")), *PAGES[0][1:]]],
    ], ids=["no header on page 1", "no header on page 2", "no Posted", "another header"])
    def test_a_missing_header_or_heading_fails_the_file_importing_nothing(
            self, conn, account, tmp_path, pages):
        assert import_pdf(conn, tmp_path, pages).failure_code == "statement_structure_mismatch"
        assert stored_documents(conn) == 0


class TestFailedPdfs:  # D2, the import half
    def encrypted(self):
        writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf_bytes(PAGES))))
        writer.encrypt("", algorithm="RC4-128")
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_each_fails_with_its_code_and_the_next_file_still_imports(self, conn, account,
                                                                      tmp_path):
        files = {"encrypted.pdf": self.encrypted(), "blank.pdf": pdf_bytes([[]]),
                 "export.csv": b"Date,Description,Amount\n", "good.pdf": pdf_bytes(PAGES)}
        for name, content in files.items():
            (tmp_path / name).write_bytes(content)
        results = import_files(conn, [tmp_path / name for name in files], account_id="card",
                               layout=LAYOUT)
        assert [(result.outcome, result.failure_code) for result in results] == [
            ("failed", "encrypted_pdf"), ("failed", "no_text_layer"),
            ("failed", "unreadable_pdf"), ("imported", None)]
        assert stored_documents(conn) == 1


class TestCoverage:  # D8, as amended: the printout states no period
    def test_without_a_declaration_coverage_is_unknown(self, conn, account, tmp_path):
        assert import_pdf(conn, tmp_path, PAGES).coverage.kind == "unknown"

    def test_a_posting_basis_declaration_is_accepted(self, conn, account, tmp_path):
        declared = declare_complete("2026-10-01", "2026-11-04", "posting")
        result = import_pdf(conn, tmp_path, PAGES, declared=declared)
        assert (result.coverage.kind, result.coverage.evidence) == ("complete", "user_declared")

    def test_a_transaction_basis_declaration_fails(self, conn, account, tmp_path):
        declared = declare_complete("2026-10-01", "2026-11-04", "transaction")
        result = import_pdf(conn, tmp_path, PAGES, declared=declared)
        assert result.failure_code == "coverage_basis_unavailable"
        assert stored_documents(conn) == 0


class TestIdentityAndRepeats:  # D12
    def test_identical_entries_stay_separate_and_trace_to_their_rows(self, conn, account,
                                                                     tmp_path):
        import_pdf(conn, tmp_path, PAGES)
        assert account_movement(conn, "card").transactions == 6
        assert [index for (index,) in conn.execute(
            """SELECT record.record_index FROM transaction_source source
               JOIN source_record record ON record.id = source.source_record_id
               ORDER BY record.record_index""")] == [1, 2, 3, 4, 5, 6]
        occurrences = [occurrence for (occurrence,) in conn.execute(
            "SELECT occurrence FROM source_record ORDER BY record_index")]
        assert occurrences == [1, 1, 2, 1, 1, 1]

    def test_reimporting_changes_nothing(self, conn, account, tmp_path):
        import_pdf(conn, tmp_path, PAGES)
        before = account_movement(conn, "card")
        assert import_pdf(conn, tmp_path, PAGES).outcome == "already_imported"
        assert account_movement(conn, "card") == before
        assert stored_documents(conn) == 1


class TestAccount:  # D13, and D-061's check
    def test_another_account_type_fails_the_file(self, conn, tmp_path):
        add_account(conn, "checking", "checking", LAST4)
        result = import_pdf(conn, tmp_path, PAGES, account_id="checking")
        assert result.failure_code == "account_type_mismatch"
        assert stored_documents(conn) == 0

    def test_another_cards_printout_fails_the_file(self, conn, tmp_path):
        add_account(conn, "other", "credit_card", "0001")
        assert import_pdf(conn, tmp_path, PAGES, account_id="other").failure_code == \
            "account_number_mismatch"
        assert stored_documents(conn) == 0

    def test_one_entry_naming_another_card_fails_the_whole_file(self, conn, account, tmp_path):
        pages = [list(lines) for lines in PAGES]
        pages[1][-1] = account_line("0001")
        assert import_pdf(conn, tmp_path, pages).failure_code == "account_number_mismatch"

    def test_an_account_line_naming_no_digits_fails_the_file(self, conn, account, tmp_path):
        pages = [list(lines) for lines in PAGES]
        pages[1][-1] = ((480, "Credit Card ...XXXX"),)
        assert import_pdf(conn, tmp_path, pages).failure_code == "account_number_mismatch"

    def test_a_card_with_no_last_four_digits_is_refused(self, conn, tmp_path):
        add_account(conn, "unnumbered", "credit_card", None)
        assert import_pdf(conn, tmp_path, PAGES, account_id="unnumbered").failure_code == \
            "account_number_unknown"


class TestCommand:
    def test_pf_import_offers_the_layout(self, tmp_path, capsys):
        db = str(tmp_path / "ledger.db")
        statement = tmp_path / "activity.pdf"
        statement.write_bytes(pdf_bytes(PAGES))
        assert LAYOUTS[LAYOUT.layout_id] is LAYOUT
        assert main(["init", "--db", db]) == 0
        assert main(["account", "add", "--db", db, "--name", "Card", "--type", "credit_card",
                     "--last4", LAST4]) == 0
        assert main(["import", "--db", db, "--account", "Card", "--layout", LAYOUT.layout_id,
                     "--declare-complete-coverage", "--coverage-start", "2026-10-01",
                     "--coverage-end", "2026-11-04", "--coverage-basis", "posting",
                     str(statement)]) == 0
        assert "Source rows read: 6 (6 valid, 0 unresolved)" in capsys.readouterr().out
