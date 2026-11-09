"""Reading a PDF's text (D-060 point 1, M7.1: D1, D2 and D4).

Every PDF here is written by tests/synthetic_pdf.py, so its lines are known. Whether pypdf reads a
real statement the same way is shown only by a PDF layout's own check, from M7.2.
"""

import io
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pypdf
import pytest
from pypdf.filters import JBIG2Decode

from personal_finance import cli
from personal_finance.cli import main
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.pdf_reader import (
    EXTRACTOR_VERSION,
    read_pdf_lines,
    without_outside_programs,
)
from synthetic_pdf import pdf_bytes

PROJECT_FOLDER = Path(__file__).resolve().parents[2]
PAGES = [
    ["Account Summary", "Beginning Balance on 01/01   1,000.00"],
    ["01/05  SYNTHETIC CAFE (MAIN)        -4.50", "Ending Balance on 01/31   995.50"],
]
JBIG2_IMAGE = (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 1 "
               b"/ColorSpace /DeviceGray /Filter /JBIG2Decode /Length 4 >>\nstream\nabcd\nendstream")


def failure_code(content: bytes) -> str:
    with pytest.raises(ImportFailure) as raised:
        read_pdf_lines(content)
    return raised.value.code


def encrypted(content: bytes) -> bytes:
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(content)))
    writer.encrypt("", algorithm="RC4-128")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def refuse_programs(monkeypatch):
    """Fails any attempt to run a program, and records it."""
    attempts = []

    def run(*arguments, **options):
        attempts.append(arguments)
        raise AssertionError("a program was run")

    monkeypatch.setattr(subprocess, "run", run)
    return attempts


class TestLines:
    def test_each_pages_lines_come_back_in_order(self):
        assert read_pdf_lines(pdf_bytes(PAGES)) == PAGES

    def test_spaces_within_a_line_stay_and_blank_lines_go(self):
        pages = [["Date   Description        Amount   ", "   ", "01/05  CAFE   -4.50"]]
        assert read_pdf_lines(pdf_bytes(pages)) == [
            ["Date   Description        Amount", "01/05  CAFE   -4.50"]]

    def test_columns_placed_apart_stay_apart_in_layout_mode(self):
        """Plain mode would join them with one space, losing which column a figure is in."""
        pages = [[((50, "Date"), (300, "Withdrawals"), (450, "Deposits")), "Next line"]]
        [[columns, next_line]] = read_pdf_lines(pdf_bytes(pages))
        assert re.fullmatch(r"Date {10,}Withdrawals {5,}Deposits", columns)
        assert next_line == "Next line"

    def test_the_reader_drops_trailing_spaces_and_blank_lines_whatever_pypdf_returns(
            self, monkeypatch):
        monkeypatch.setattr(pypdf.PageObject, "extract_text",
                            lambda page, **options: "  Indented   \n \t \n\nLast  \n")
        assert read_pdf_lines(pdf_bytes(PAGES)) == [["  Indented", "Last"]] * 2

    def test_a_blank_page_keeps_its_place(self):
        assert read_pdf_lines(pdf_bytes([["First"], [], ["Third"]])) == [["First"], [], ["Third"]]


class TestFailures:
    def test_an_encrypted_pdf_is_refused_even_with_an_empty_password(self):
        assert pypdf.PdfReader(io.BytesIO(encrypted(pdf_bytes(PAGES)))).is_encrypted
        assert failure_code(encrypted(pdf_bytes(PAGES))) == "encrypted_pdf"

    @pytest.mark.parametrize("pages", [[[]], [[], []], [["   "]]], ids=["one", "two", "spaces"])
    def test_a_pdf_with_no_text_has_no_text_layer(self, pages):
        assert failure_code(pdf_bytes(pages)) == "no_text_layer"

    @pytest.mark.parametrize("content", [
        b"", b"Date,Amount\n01/05/2026,-4.50\n", pdf_bytes(PAGES)[:200],
        pdf_bytes(PAGES)[: len(pdf_bytes(PAGES)) // 2],
    ], ids=["empty", "csv", "header only", "truncated"])
    def test_bytes_that_are_not_a_whole_pdf_are_unreadable(self, content):
        assert failure_code(content) == "unreadable_pdf"

    def test_a_readable_pdf_is_the_control(self):
        assert read_pdf_lines(pdf_bytes(PAGES))

    def test_pf_prints_the_failure_alone(self, tmp_path):
        """pypdf logs warnings quoting the file, as in `invalid pdf header: b'Date,'`, which
        Python prints to stderr when no handler takes them (D-037). Run outside pytest, whose
        own log capture would hide them."""
        statement = tmp_path / "statement.pdf"
        statement.write_bytes(b"Date,Amount\n01/05/2026,-4.50\n")
        finished = subprocess.run([str(PROJECT_FOLDER / "bin" / "pf"), "pdf", "text", str(statement)],
                                  capture_output=True, text=True)
        assert (finished.returncode, finished.stdout, finished.stderr) == (
            2, "", "Error: the file could not be read as a PDF: unreadable_pdf\n")


class TestNoOutsideProgram:
    """pypdf may run jbig2dec for a JBIG2 image. The reader never lets it (D-060 point 1)."""

    def test_the_decoder_runs_the_program_without_the_reader_as_the_control(self, refuse_programs):
        with pypdf.apply_configuration(jbig2dec_binary="/usr/bin/false"):
            with pytest.raises(AssertionError, match="a program was run"):
                JBIG2Decode.decode(b"abcd")
        assert len(refuse_programs) == 1

    def test_under_the_reader_the_decoder_refuses_and_runs_nothing(self, refuse_programs):
        with pypdf.apply_configuration(jbig2dec_binary="/usr/bin/false"):
            with without_outside_programs(), pytest.raises(pypdf.errors.DependencyError):
                JBIG2Decode.decode(b"abcd")
        assert refuse_programs == []

    def test_a_pdf_holding_a_jbig2_image_is_read_without_running_anything(self, refuse_programs):
        content = pdf_bytes([["Text beside an image"]], extra_objects=[JBIG2_IMAGE],
                            page_resources=b"/XObject << /Im1 6 0 R >>")
        with pypdf.apply_configuration(jbig2dec_binary="/usr/bin/false"):
            assert read_pdf_lines(content) == [["Text beside an image"]]
        assert refuse_programs == []


class TestPinnedVersion:
    def test_the_extractor_version_names_the_installed_and_pinned_release(self):
        pinned = re.search(r"^pypdf==(\S+)", (PROJECT_FOLDER / "requirements.txt").read_text(),
                           re.MULTILINE)[1]
        declared = tomllib.loads((PROJECT_FOLDER / "pyproject.toml").read_text())
        assert pypdf.__version__ == pinned
        assert EXTRACTOR_VERSION == f"pypdf-{pinned}"
        assert declared["project"]["dependencies"] == [f"pypdf=={pinned}"]

    def test_the_pin_carries_a_hash(self):
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", (PROJECT_FOLDER / "requirements.txt").read_text())


class TestPdfTextCommand:
    def test_it_prints_each_page_and_line(self, tmp_path, capsys):
        statement = tmp_path / "statement.pdf"
        statement.write_bytes(pdf_bytes(PAGES))
        assert main(["pdf", "text", str(statement)]) == 0
        assert capsys.readouterr().out == (
            "Page 1\n  Account Summary\n  Beginning Balance on 01/01   1,000.00\n"
            "Page 2\n  01/05  SYNTHETIC CAFE (MAIN)        -4.50\n"
            "  Ending Balance on 01/31   995.50\n")

    def test_a_line_cannot_imitate_other_output(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(cli, "read_pdf_lines", lambda content: [["A\x1b[2J\nPage 9"]])
        statement = tmp_path / "statement.pdf"
        statement.write_bytes(b"%PDF")
        assert main(["pdf", "text", str(statement)]) == 0
        assert capsys.readouterr().out == "Page 1\n  A\\x1b[2J\\nPage 9\n"

    def test_it_opens_no_ledger_and_writes_nothing(self, tmp_path, capsys, monkeypatch):
        statement = tmp_path / "statement.pdf"
        statement.write_bytes(pdf_bytes(PAGES))
        monkeypatch.setattr(cli, "open_ledger", lambda *args, **kwargs: pytest.fail("opened"))
        monkeypatch.setattr(cli.sqlite3, "connect", lambda *args, **kwargs: pytest.fail("opened"))
        monkeypatch.chdir(tmp_path)
        before = sorted(os.walk(tmp_path))
        assert main(["pdf", "text", str(statement)]) == 0
        assert sorted(os.walk(tmp_path)) == before

    @pytest.mark.parametrize("content, code", [
        (encrypted(pdf_bytes(PAGES)), "encrypted_pdf"),
        (pdf_bytes([[]]), "no_text_layer"),
        (b"Date,Amount\n", "unreadable_pdf"),
    ], ids=["encrypted", "no text", "not a pdf"])
    def test_a_failure_prints_its_code_alone(self, tmp_path, capsys, content, code):
        statement = tmp_path / "statement.pdf"
        statement.write_bytes(content)
        assert main(["pdf", "text", str(statement)]) == 2
        assert capsys.readouterr() == ("", f"Error: the file could not be read as a PDF: {code}\n")

    def test_a_missing_file_is_unreadable(self, tmp_path, capsys):
        assert main(["pdf", "text", str(tmp_path / "missing.pdf")]) == 2
        assert capsys.readouterr().err == "Error: the file could not be read: unreadable_file\n"
