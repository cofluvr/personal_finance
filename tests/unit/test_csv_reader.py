import hashlib
import json

import pytest

from personal_finance.ingest.csv_reader import read_document
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1

CARD_HEADER = "Date,Description,Debit,Credit\n"
CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"


def read_card(text):
    return read_document(text.encode("utf-8"), SYNTHETIC_CARD_V1)


def read_checking(text):
    return read_document(text.encode("utf-8"), SYNTHETIC_CHECKING_V1)


def failure_code(reader, text):
    with pytest.raises(ImportFailure) as caught:
        reader(text)
    return caught.value.code


def test_cells_are_kept_exactly_as_read():
    _, records = read_card(CARD_HEADER + '01/05/2026,"  SYNTHETIC, CAFE é ",6.50,\n')
    assert records[0].cells == ("01/05/2026", "  SYNTHETIC, CAFE é ", "6.50", "")
    assert json.loads(records[0].raw_json) == list(records[0].cells)


def test_records_are_numbered_from_one():
    _, records = read_card(CARD_HEADER + "a,b,c,d\ne,f,g,h\n")
    assert [record.index for record in records] == [1, 2]


def test_identical_rows_get_increasing_occurrence_numbers():
    row = "01/05/2026,SYNTHETIC CAFE,6.50,\n"
    _, records = read_card(CARD_HEADER + row + "x,y,z,w\n" + row)
    assert [record.occurrence for record in records] == [1, 1, 2]
    assert records[0].fingerprint == records[2].fingerprint


def test_fingerprint_is_a_hash_of_the_raw_cells():
    _, records = read_card(CARD_HEADER + "a,b,c,d\n")
    expected = hashlib.sha256(records[0].raw_json.encode("utf-8")).hexdigest()
    assert records[0].fingerprint == expected


def test_a_row_of_empty_cells_is_kept_but_a_blank_line_is_not():
    _, records = read_card(CARD_HEADER + ",,,\n\n")
    assert [record.cells for record in records] == [("", "", "", "")]


def test_rows_with_the_wrong_number_of_cells_are_kept():
    _, records = read_card(CARD_HEADER + "a,b\na,b,c,d,e\n")
    assert [len(record.cells) for record in records] == [2, 5]


def test_windows_line_endings_and_a_byte_order_mark_are_accepted():
    content = "﻿" + CARD_HEADER.replace("\n", "\r\n") + "a,b,c,d\r\n"
    _, records = read_document(content.encode("utf-8"), SYNTHETIC_CARD_V1)
    assert records[0].cells == ("a", "b", "c", "d")


def test_a_header_with_no_rows_is_an_empty_document():
    assert read_card(CARD_HEADER) == ({}, [])


@pytest.mark.parametrize(
    "text",
    ["", "Date,Description,Debit\n", "date,description,debit,credit\n", "Credit,Debit,Description,Date\n"],
)
def test_wrong_headers_fail(text):
    assert failure_code(read_card, text) == "header_mismatch"


def test_a_preamble_is_not_accepted_by_a_layout_without_one():
    assert failure_code(read_card, "# coverage-kind: complete\n" + CARD_HEADER) == "header_mismatch"


def test_invalid_encoding_fails():
    with pytest.raises(ImportFailure) as caught:
        read_document(CARD_HEADER.encode() + b"\xff\xfe\n", SYNTHETIC_CARD_V1)
    assert caught.value.code == "invalid_encoding"


def test_unterminated_quote_fails():
    assert failure_code(read_card, CARD_HEADER + 'a,"b,c,d\n') == "malformed_csv"


def test_an_oversized_field_fails():
    assert failure_code(read_card, CARD_HEADER + "a," + "b" * 200_000 + ",c,d\n") == "malformed_csv"


def test_metadata_is_read_and_a_hash_in_data_is_not():
    text = "# coverage-kind: unknown\n# generated-on: 2026-02-01\n" + CHECKING_HEADER
    text += "#1,2026-01-05,,SYNTHETIC,1.00,POSTED\n"
    metadata, records = read_checking(text)
    assert metadata == {"coverage-kind": "unknown", "generated-on": "2026-02-01"}
    assert records[0].cells[0] == "#1"


@pytest.mark.parametrize(
    "preamble",
    [
        "# coverage-kind\n",
        "# surprise: value\n",
        "# coverage-kind: complete\n# coverage-kind: partial\n",
    ],
)
def test_bad_metadata_lines_fail(preamble):
    assert failure_code(read_checking, preamble + CHECKING_HEADER) == "invalid_coverage_metadata"
