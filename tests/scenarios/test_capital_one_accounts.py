"""Capital One's checking and savings exports name their account (D-061).

Each row's Account Number is the account's last four digits, so a file imports only into the
account it was exported from. A transfer between the two accounts is matched with M3.2's commands
(D-054). Every value is invented. The savings side's wording follows the owner's export, and the
checking side's is a guess, which matching never reads.
"""

import pytest
from test_transfers import TransferLedger, rows_of

HEADER = ("Account Number,Transaction Description,Transaction Date,Transaction Type,"
          "Transaction Amount,Balance")
SAVINGS_ROWS = (
    "7302,Withdrawal to 360 Checking XXXXXXX4821,01/20/26,Debit,250,750",
    "7302,Monthly Interest Paid,12/31/25,Credit,1.1,1000",
)
CHECKING_ROWS = (
    "4821,Deposit from 360 Performance Savings XXXXXXX7302,01/20/26,Credit,250,1250",
)


@pytest.fixture
def ledger(tmp_path, capsys):
    found = TransferLedger(tmp_path, capsys)
    for name, account_type, last4 in (("Checking", "checking", "4821"),
                                      ("Savings", "savings", "7302")):
        code, _, err = found.run("account", "add", "--name", name, "--type", account_type,
                                 "--last4", last4)
        assert code == 0, err
    return found


def import_export(ledger, name, rows, account):
    path = ledger.folder / name
    path.write_text("\n".join([HEADER, *rows]) + "\n")
    return ledger.run("import", "--account", account, "--layout", "capital_one_bank_v1",
                      str(path))


def stored_documents(ledger):
    conn = ledger.conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0]
    finally:
        conn.close()


class TestAccountNumber:
    def test_each_export_imports_into_its_own_account(self, ledger):
        assert import_export(ledger, "savings.csv", SAVINGS_ROWS, "Savings")[0] == 0
        assert import_export(ledger, "checking.csv", CHECKING_ROWS, "Checking")[0] == 0
        assert stored_documents(ledger) == 2

    def test_the_savings_export_fails_in_checking_importing_nothing(self, ledger):
        code, out, _ = import_export(ledger, "savings.csv", SAVINGS_ROWS, "Checking")
        assert "failed (account_number_mismatch)" in out
        assert code != 0
        assert stored_documents(ledger) == 0

    def test_one_row_naming_another_account_fails_the_whole_file(self, ledger):
        rows = (*CHECKING_ROWS, "7302,Monthly Interest Paid,12/31/25,Credit,1.1,1000")
        code, out, _ = import_export(ledger, "mixed.csv", rows, "Checking")
        assert "failed (account_number_mismatch)" in out
        assert stored_documents(ledger) == 0

    def test_a_blank_account_number_fails_the_file(self, ledger):
        rows = (",Monthly Interest Paid,12/31/25,Credit,1.1,1000",)
        code, out, _ = import_export(ledger, "blank.csv", rows, "Savings")
        assert "failed (account_number_mismatch)" in out

    def test_an_account_with_no_last_four_digits_is_refused(self, ledger):
        assert ledger.run("account", "add", "--name", "Unnumbered", "--type", "savings")[0] == 0
        code, out, _ = import_export(ledger, "savings.csv", SAVINGS_ROWS, "Unnumbered")
        assert "failed (account_number_unknown)" in out
        assert stored_documents(ledger) == 0

    def test_a_row_with_too_few_cells_stays_unresolved_and_is_not_checked(self, ledger):
        rows = (*SAVINGS_ROWS, "0000,Short row")
        code, out, _ = import_export(ledger, "savings.csv", rows, "Savings")
        assert code == 0, out
        assert "(2 valid, 1 unresolved)" in out


class TestTransferBetweenTheAccounts:
    def test_the_savings_withdrawal_and_checking_deposit_match(self, ledger):
        import_export(ledger, "savings.csv", SAVINGS_ROWS, "Savings")
        import_export(ledger, "checking.csv", CHECKING_ROWS, "Checking")
        outflow, _interest = rows_of(ledger, "savings.csv")
        (inflow,) = rows_of(ledger, "checking.csv")
        assert ledger.candidates() == []

        ledger.classify_ok(outflow, "transfer", account="Savings")
        assert ledger.candidates() == [(outflow, inflow)]
        ledger.match_ok(outflow, inflow, account="Savings", counterpart_account="Checking")
        assert ledger.matches() == [("applied", ("savings.csv",), ("checking.csv",))]
        assert "Confirmed transfers" in ledger.totals()
