import pytest

from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1


def checking(**overrides):
    cells = {
        "Transaction ID": "SYN-1",
        "Transaction Date": "2026-01-05",
        "Posted Date": "2026-01-06",
        "Description": "SYNTHETIC GROCER",
        "Amount": "-12.34",
        "Status": "POSTED",
    }
    return SYNTHETIC_CHECKING_V1.parse_row({**cells, **overrides})


def card(**overrides):
    cells = {"Date": "01/05/2026", "Description": "SYNTHETIC CAFE", "Debit": "6.50", "Credit": ""}
    return SYNTHETIC_CARD_V1.parse_row({**cells, **overrides})


class TestChecking:
    def test_a_complete_row(self):
        row = checking()
        assert row.reason_code is None
        assert row.transaction_date == "2026-01-05"
        assert row.posting_date == "2026-01-06"
        assert row.amount_cents == -1234
        assert row.description == "SYNTHETIC GROCER"
        assert row.external_id == "SYN-1"
        assert row.settlement_status == "posted"

    def test_positive_amount_is_an_inflow(self):
        assert checking(Amount="2500.00").amount_cents == 250000

    def test_zero_stays_zero(self):
        row = checking(Amount="0.00")
        assert row.reason_code is None
        assert row.amount_cents == 0

    def test_blank_posting_date_stays_missing(self):
        row = checking(**{"Posted Date": ""})
        assert row.reason_code is None
        assert row.posting_date is None

    def test_blank_transaction_date_is_not_filled_from_posting_date(self):
        row = checking(**{"Transaction Date": ""})
        assert row.reason_code is None
        assert row.transaction_date is None

    def test_blank_description_and_id_stay_missing(self):
        row = checking(Description=" ", **{"Transaction ID": ""})
        assert row.reason_code is None
        assert row.description is None
        assert row.external_id is None

    @pytest.mark.parametrize(
        ("status", "expected"), [("PENDING", "pending"), ("posted", "posted"), ("", "unknown")]
    )
    def test_status(self, status, expected):
        assert checking(Status=status).settlement_status == expected

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"Amount": ""}, "missing_amount"),
            ({"Amount": "abc"}, "invalid_amount"),
            ({"Amount": "-10.005"}, "invalid_amount"),
            ({"Amount": "1" * 5000}, "invalid_amount"),
            ({"Transaction Date": "", "Posted Date": ""}, "missing_date"),
            ({"Transaction Date": "2026-02-30"}, "invalid_date"),
            ({"Posted Date": "01/06/2026"}, "invalid_date"),
            ({"Status": "SETTLED"}, "invalid_status"),
        ],
    )
    def test_unresolved_rows(self, overrides, reason):
        assert checking(**overrides).reason_code == reason

    def test_an_unresolved_row_keeps_what_did_parse(self):
        row = checking(Amount="")
        assert row.amount_cents is None
        assert row.transaction_date == "2026-01-05"


class TestCard:
    def test_a_debit_is_negative(self):
        row = card()
        assert row.reason_code is None
        assert row.amount_cents == -650

    def test_a_credit_is_positive(self):
        assert card(Debit="", Credit="30.00").amount_cents == 3000

    def test_the_date_is_the_posting_date_only(self):
        row = card()
        assert row.posting_date == "2026-01-05"
        assert row.transaction_date is None

    def test_rows_are_posted_by_definition_and_have_no_id(self):
        row = card()
        assert row.settlement_status == "posted"
        assert row.external_id is None

    def test_zero_debit_stays_zero(self):
        row = card(Debit="0.00")
        assert row.reason_code is None
        assert row.amount_cents == 0

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"Debit": ""}, "missing_amount"),
            ({"Credit": "1.00"}, "conflicting_amount"),
            ({"Credit": "0.00"}, "conflicting_amount"),
            ({"Debit": "-6.50"}, "invalid_amount"),
            ({"Debit": "", "Credit": "-6.50"}, "invalid_amount"),
            ({"Debit": "abc"}, "invalid_amount"),
            ({"Date": ""}, "missing_date"),
            ({"Date": "2026-01-05"}, "invalid_date"),
            ({"Date": "13/05/2026"}, "invalid_date"),
        ],
    )
    def test_unresolved_rows(self, overrides, reason):
        assert card(**overrides).reason_code == reason


def test_the_two_layouts_agree_on_the_sign_of_money_out():
    assert checking(Amount="-6.50").amount_cents == card(Debit="6.50").amount_cents


def test_only_the_checking_layout_declares_reliable_ids():
    assert SYNTHETIC_CHECKING_V1.external_ids_reliable is True
    assert SYNTHETIC_CARD_V1.external_ids_reliable is False
