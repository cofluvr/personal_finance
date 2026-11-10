"""ID lists beyond SQLite's 32,766-parameter limit (D-057, M4.1: L1 to L3).

Each query here once passed one SQL parameter per ID and failed with "too many SQL variables" past
32,766 IDs. The ledgers are built directly, as the benchmarks build theirs.
"""

import pytest

from personal_finance.db.id_lists import ids_as_json_array
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import FileResult, import_files
from personal_finance.reconcile.classification_effects import write_classification_effects
from personal_finance.reconcile.transfer_effects import (
    _FACTS,
    _facts_of,
    transaction_facts,
    write_transfer_effects,
)
from personal_finance.reports.import_summary import (
    consolidated_records,
    final_transactions,
    summarize_run,
)
from personal_finance.reports.totals import account_movement

PAST_THE_LIMIT = 32_767
HEADER = "Date,Description,Debit,Credit\n"
CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
FINGERPRINT = "0" * 64


def unknown_ids(count):
    return [f"unknown-{number:06}" for number in range(count)]


def import_rows(conn, folder, account, file_name, rows):
    """Import one synthetic card file of (day, description, cents) rows into account."""
    source = folder / file_name
    source.write_text(HEADER + "".join(
        f"01/{day:02}/2026,{description},"
        + ("{0:.2f},".format(-cents / 100) if cents < 0 else ",{0:.2f}".format(cents / 100))
        + "\n"
        for day, description, cents in rows
    ))
    import_files(conn, [source], account_id=account, layout=SYNTHETIC_CARD_V1)


def add_account(conn, account, account_type="checking"):
    conn.execute("INSERT INTO account (id, display_name, account_type) VALUES (?, ?, ?)",
                 (account, account, account_type))


def links(conn, account):
    """Each (transaction, record, amount) of one account, ordered by amount."""
    return conn.execute(
        """SELECT link.transaction_id, link.source_record_id, entry.amount_cents
           FROM transaction_source link
           JOIN ledger_transaction entry ON entry.id = link.transaction_id
           WHERE link.account_id = ? ORDER BY entry.amount_cents""",
        (account,),
    ).fetchall()


@pytest.fixture
def small_ledger(conn, tmp_path):
    """One checking account with two documents, one row of which appears in both by its
    reliable ID, so that it merges."""
    add_account(conn, "out")
    for file_name, rows in (
            ("first.csv", [("c1", "2026-01-03", "SYNTHETIC CAFE", "-4.50"),
                           ("c2", "2026-01-04", "SYNTHETIC GROCER", "-12.00")]),
            ("second.csv", [("c2", "2026-01-04", "SYNTHETIC GROCER", "-12.00"),
                            ("c3", "2026-01-09", "SYNTHETIC REFUND", "3.00")])):
        source = tmp_path / file_name
        source.write_text(CHECKING_HEADER + "".join(
            f"{external_id},{day},{day},{description},{amount},POSTED\n"
            for external_id, day, description, amount in rows))
        import_files(conn, [source], account_id="out", layout=SYNTHETIC_CHECKING_V1)
    return conn


def document_ids(conn):
    return [row[0] for row in conn.execute("SELECT id FROM source_document ORDER BY file_name")]


def test_ids_as_json_array_refuses_an_id_that_is_not_a_string():
    assert ids_as_json_array(["a", "b"]) == '["a", "b"]'
    with pytest.raises(TypeError):
        ids_as_json_array(["a", 1])


def test_transaction_facts_past_the_limit_returns_only_live_transactions(small_ledger):
    live = [transaction_id for transaction_id, _, _ in links(small_ledger, "out")]
    facts = transaction_facts(small_ledger, unknown_ids(PAST_THE_LIMIT) + live)
    assert sorted(facts) == sorted(set(live))
    assert sorted(facts[transaction_id].amount_cents for transaction_id in facts) == [-1200, -450, 300]


def test_import_summary_counts_past_the_limit(small_ledger):
    documents = document_ids(small_ledger) + unknown_ids(PAST_THE_LIMIT)
    assert final_transactions(small_ledger, documents) == 3
    assert consolidated_records(small_ledger, documents) == 2


def test_run_summary_of_more_files_than_the_limit(small_ledger):
    """L3: a run of 32,767 imported files, built directly as file results."""
    real = document_ids(small_ledger)
    results = [
        FileResult(file_name=f"file-{number}.csv", outcome="imported",
                   source_document_id=document_id, rows_read=0, valid_records=0,
                   unresolved_records=0, net_transactions=0, memberships_changed=0)
        for number, document_id in enumerate(real + unknown_ids(PAST_THE_LIMIT - len(real)))
    ]
    summary = summarize_run(small_ledger, results)
    assert summary.files_imported == PAST_THE_LIMIT
    assert (summary.final_transactions, summary.consolidated_records) == (3, 2)


def test_totals_with_more_active_separations_than_the_limit(conn, tmp_path):
    """L1 and L3: 32,767 active separations, each pairing a transaction of its own with one shared
    transaction, so that leaving out any of them changes the count, and one undone separation of
    another transaction that totals must leave out."""
    add_account(conn, "out")
    import_rows(conn, tmp_path, "out", "out.csv", [
        (1 + number % 28, f"SYNTHETIC SHOP {number}", -(1 + number))
        for number in range(PAST_THE_LIMIT + 2)])
    (shared_transaction, shared_record, _), *own, (undone_transaction, undone_record, _) = links(
        conn, "out")
    pairs = [(transaction_id, record_id) for transaction_id, record_id, _ in own]
    pairs.append((undone_transaction, undone_record))
    conn.execute("BEGIN")
    for number, (transaction_id, record_id) in enumerate(pairs):
        decision_id = f"s{number:06}"
        conn.execute(
            """INSERT INTO decision (id, account_id, target_id, target_revision, target_kind)
               VALUES (?, 'out', ?, 't1-0', 'transaction')""",
            (decision_id, shared_transaction))
        conn.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                   left_transaction_id, right_transaction_id, left_record_id, right_record_id)
               VALUES (?, 'different_event', 1, ?, ?, ?, ?)""",
            (decision_id, shared_transaction, transaction_id, shared_record, record_id))
        conn.execute(
            "INSERT INTO decision_event (decision_id, event, rules_fingerprint) VALUES (?, 'made', ?)",
            (decision_id, FINGERPRINT))
    conn.execute(
        "INSERT INTO decision_event (decision_id, event, rules_fingerprint) VALUES (?, 'undone', ?)",
        (f"s{PAST_THE_LIMIT:06}", FINGERPRINT))
    conn.execute("COMMIT")

    assert len(own) == PAST_THE_LIMIT
    assert account_movement(conn).transactions_separated == PAST_THE_LIMIT + 1
    assert account_movement(conn, "out").transactions_separated == PAST_THE_LIMIT + 1


def test_writing_transfer_effects_for_more_bound_transactions_than_the_limit(conn, tmp_path):
    """L3: 32,767 applied one-sided transfers, each binding one transaction, all read by one write.
    They stand in for matches, whose sides SQLite inserts in time quadratic in an account's
    sides, through the `transfer_match_side_two_accounts` trigger."""
    add_account(conn, "out")
    add_account(conn, "in", "savings")
    import_rows(conn, tmp_path, "out", "out.csv", [
        (1 + number % 28, f"SYNTHETIC MOVE {number}", -100 * (1 + number))
        for number in range(PAST_THE_LIMIT)])
    outflows = links(conn, "out")
    conn.execute("BEGIN")
    for number, (transaction_id, record_id, _) in enumerate(outflows):
        classification_id, statement_id = f"f{number:06}", f"o{number:06}"
        conn.execute(
            """INSERT INTO type_classification (id, account_id, financial_type,
                                                target_transaction_id, target_revision)
               VALUES (?, 'out', 'transfer', ?, 't8-0')""",
            (classification_id, transaction_id))
        conn.execute("INSERT INTO type_classification_record VALUES (?, ?)",
                     (classification_id, record_id))
        conn.execute("INSERT INTO type_classification_event (classification_id, event) "
                     "VALUES (?, 'made')", (classification_id,))
        conn.execute(
            """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                               target_transaction_id, target_revision)
               VALUES (?, 'out', 'in', ?, 't8-0')""",
            (statement_id, transaction_id))
        conn.execute("INSERT INTO one_sided_transfer_record VALUES (?, ?)",
                     (statement_id, record_id))
        conn.execute("INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
                     "VALUES (?, 'made')", (statement_id,))
    write_classification_effects(conn, "out")
    write_transfer_effects(conn)
    conn.execute("COMMIT")

    states = dict(conn.execute(
        "SELECT state, COUNT(*) FROM one_sided_transfer_effect GROUP BY state").fetchall())
    assert states == {"applied": PAST_THE_LIMIT}


def reference_facts(conn, transaction_ids):
    """The query as it was before D-057: one parameter per ID."""
    wanted = sorted(set(transaction_ids))
    marks = ", ".join("?" for _ in wanted)
    return {facts.transaction_id: facts for facts in map(
        _facts_of, conn.execute(_FACTS + f" WHERE entry.id IN ({marks})", wanted))}


def reference_import_counts(conn, documents):
    """Both import summary queries as they were before D-057."""
    marks = ",".join("?" * len(documents))
    final = conn.execute(
        f"""SELECT COUNT(DISTINCT transaction_id) FROM transaction_source
            WHERE source_document_id IN ({marks})""", documents).fetchone()[0]
    consolidated = conn.execute(
        f"""SELECT COUNT(*) FROM transaction_source link
            WHERE link.source_document_id IN ({marks})
              AND EXISTS (SELECT 1 FROM transaction_source other
                          WHERE other.transaction_id = link.transaction_id
                            AND other.source_document_id <> link.source_document_id)""",
        documents).fetchone()[0]
    return final, consolidated


def test_results_match_the_earlier_queries_below_the_limit(small_ledger):
    """L2: every subset of the ledger's IDs, with repeats and unknown IDs, gives what the
    one-parameter-per-ID queries gave."""
    transactions = sorted({transaction_id for transaction_id, _, _ in links(small_ledger, "out")})
    documents = document_ids(small_ledger)
    for mask in range(1 << len(transactions)):
        chosen = [transaction for bit, transaction in enumerate(transactions) if mask >> bit & 1]
        named = chosen + chosen[:1] + ["unknown"]
        assert transaction_facts(small_ledger, named) == reference_facts(small_ledger, named)
    for mask in range(1 << len(documents)):
        chosen = [document for bit, document in enumerate(documents) if mask >> bit & 1]
        named = chosen + chosen[:1] + ["unknown"]
        assert (final_transactions(small_ledger, named),
                consolidated_records(small_ledger, named)) == reference_import_counts(
                    small_ledger, named)
    assert (final_transactions(small_ledger, []), consolidated_records(small_ledger, [])) == (
        reference_import_counts(small_ledger, []))
