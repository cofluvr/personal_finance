"""The text of the report commands, built as lines, for the CLI and the local UI alike (D-062).

`totals`, `report monthly`, `documents`, `transactions`, `review list` and `review show` print
exactly the lines built here, and the UI renders the same lines, so the two cannot disagree. Every
builder is given an open connection and validated options, opens no ledger, prints nothing and
writes nothing. A builder computes everything before returning, so a broken invariant stops a
report rather than truncating it.
"""

import json
from dataclasses import dataclass
from itertools import islice
from typing import NamedTuple

from personal_finance.money import format_cents
from personal_finance.reconcile.apply import stale_accounts
from personal_finance.reconcile.classification_effects import (
    TYPE_AGAINST_DIRECTION,
    UNCLASSIFIED,
)
from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    FIELD_BASIS_CHANGED,
    FIELD_IN_CONFLICT,
)
from personal_finance.reconcile.cross_document import (
    RULE_CANDIDATES,
    deciding_criterion,
    primary_rank,
)
from personal_finance.reconcile.decisions import undecided_direct_pairs
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfer_effects import (
    MATCH_AMOUNTS_DIFFER,
    MATCH_APPLIED,
    MATCH_BASIS_CHANGED,
    MATCH_CONFLICT,
    MATCH_TYPE_DIFFERS,
    ONE_SIDED_COUNTERPART_COVERED,
    ONE_SIDED_COUNTERPART_FOUND,
    TRANSFER_DATE_WINDOW_DAYS,
)
from personal_finance.reports.coverage_evidence import load_document_coverage
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.review_evidence import (
    alike_decided_records,
    load_review_evidence,
    review_revision,
    rows_sharing_a_document,
)
from personal_finance.reports.totals import (
    account_movement,
    income_and_spending,
    one_sided_summary,
    transfer_summary,
)


class ReportLine(NamedTuple):
    text: str
    # The review item this line names, which the UI links to its page.
    linked_review_item_id: str | None = None


class ReportLines(list):
    """A report's lines, in order."""

    def add(self, text: str, linked_review_item_id: str | None = None) -> None:
        self.append(ReportLine(text, linked_review_item_id))


@dataclass(frozen=True)
class ReviewItemReport:
    """One review item's lines, with what deciding it in the terminal needs (D-043)."""

    item_id: str
    kind: str
    account_id: str
    revision: str
    lines: ReportLines


MATCHING_NOTICE = (
    "Files are compared within each account. Rows matched confidently are counted once. "
    "Other duplicates can go undetected, for example where descriptions differ."
)


# A dense group holds quadratically many pairs, so review show lists only the first few.
DIRECT_PAIRS_SHOWN = 50


RULE_EXPLANATIONS = {
    "cross_document_candidates": "Records in different documents look alike, without proof.",
    "cross_document_external_id": "Records share a reliable ID but cannot be merged safely.",
    "identity_decision": "New evidence disagrees with a stored decision.",
    "same_document_repeated_external_id": "One external ID appears on several rows of a document.",
    "same_document_pending_posted": (
        "A pending row and a posted row of one document may be one event."
    ),
}


REASON_EXPLANATIONS = {
    "similar_description": "same amount, dates within the window, similar description",
    "coverage_unknown": "a document's coverage is unknown",
    "coverage_partial": "a document's coverage is partial",
    "different_basis": "the documents state coverage on different date bases",
    "date_outside_coverage": "the date falls outside a coverage claim",
    "pending_not_covered": "a coverage claim says nothing about pending rows",
    "boundary_date": "the date is too close to the end of what coverage supports",
    "single_day_overlap": "the documents overlap by a single day",
    "unresolved_row": "an unresolved row could affect the count",
    "completed_row": (
        "a row completed by hand could affect the count, and its typed values never make a "
        "match confident"
    ),
    "pending_amount_changed": (
        "a pending row and a posted row look alike but for their amount, as when a tip is added. "
        "Confirm them to count the posted amount once"
    ),
    "completed_record_shares_id": (
        "a record completed by hand shares this reliable ID, and is never merged automatically"
    ),
    "external_id_conflict": "records with this ID disagree on a material field",
    "external_id_repeated": "this ID is repeated within a document",
    "automatic_match_withheld": (
        "an automatic match would have joined records a decision keeps apart, so the whole "
        "match was withheld and its records stay separate and counted, which can raise totals"
    ),
    "decision_basis_changed": (
        "a transaction a decision was based on has since been divided by an automatic split, "
        "and the decision still applies to its records"
    ),
}


UNRESOLVED_NOTICE = "This row created no transaction and is not included in totals."


DUPLICATE_NOTICE = (
    "These transactions stay separate and are all counted in full. Totals may be overstated, "
    "and no exact adjustment can be stated."
)


CONFLICT_NOTICE = (
    "The decision stands. These are not possible duplicates. To settle this, confirm which "
    "transactions here are one event and which are different events with review confirm. To "
    "remove a decision, inspect it with review decision show, then use review undo."
)


# What each outcome of a classified transaction means (D-053).
CLASSIFICATION_STATE_EXPLANATIONS = {
    FIELD_APPLIED: "the stated type applies",
    FIELD_IN_CONFLICT: "classifications disagree, so it is unclassified. Undo all but one to settle it",
    FIELD_BASIS_CHANGED: (
        "a classification binds records now in several transactions, so it is unclassified. Undo "
        "it, then classify each transaction"
    ),
    TYPE_AGAINST_DIRECTION: (
        "its amount now runs against the stated type, as after a correction, so it is "
        "unclassified. Undo the classification, or the correction"
    ),
}


# What each outcome of a transfer match means (D-054).
MATCH_STATE_EXPLANATIONS = {
    MATCH_APPLIED: "both sides are one movement of money between your accounts",
    MATCH_BASIS_CHANGED: (
        "a side's bound records are now in several transactions, so it does not apply. Undo it, "
        "then match again"
    ),
    MATCH_CONFLICT: (
        "a transaction holds records of two matches, so neither applies. Undo all but one"
    ),
    MATCH_AMOUNTS_DIFFER: (
        "the amounts no longer offset exactly, as after a correction, so it does not apply. Undo "
        "it, or the correction"
    ),
    MATCH_TYPE_DIFFERS: (
        "a type stated on a side no longer fits a transfer between these accounts, so it does not "
        "apply. Undo it, or the classification"
    ),
}


# What each outcome of a one-sided transfer means (D-055).
ONE_SIDED_STATE_EXPLANATIONS = {
    MATCH_APPLIED: "it moves money to or from the counterpart, whose side is not in the ledger",
    MATCH_BASIS_CHANGED: (
        "its bound records are now in several transactions, so it does not apply. Undo it, then "
        "state it again"
    ),
    MATCH_CONFLICT: (
        "its transaction holds records of another match or one-sided transfer, so neither "
        "applies. Undo all but one"
    ),
    MATCH_TYPE_DIFFERS: (
        "the type stated no longer fits a transfer to the counterpart, so it does not apply. Undo "
        "it, or the classification"
    ),
    ONE_SIDED_COUNTERPART_FOUND: (
        "a transaction of the counterpart may now be its other side, so it does not apply. Undo "
        "it, then match the pair"
    ),
    ONE_SIDED_COUNTERPART_COVERED: (
        "the counterpart's complete coverage now spans its dates, so its other side would be in "
        "the ledger, and it does not apply. Undo it, or check that coverage"
    ),
}


# What each state of a corrected field means for the value used (D-049).
FIELD_STATE_EXPLANATIONS = {
    FIELD_APPLIED: "the corrected value is used",
    FIELD_IN_CONFLICT: (
        "corrections disagree, so the source value is used. Undo all but one to settle it"
    ),
    FIELD_BASIS_CHANGED: (
        "a correction binds records now in several transactions, so the source value is used. "
        "Undo it, then correct each transaction"
    ),
}


def describe_open_groups(movement) -> str:
    return (
        f"Open review groups: {movement.candidate_groups}, covering "
        f"{movement.transactions_in_candidate_groups} distinct affected transactions."
    )


def describe_corrections(movement) -> list[str]:
    """Corrections on their own lines, apart from duplicates and conflicts (D-049)."""
    lines = []
    if movement.transactions_corrected:
        lines.append(
            f"Transactions using a corrected value: {movement.transactions_corrected}. Their "
            "source values are kept, and undoing a correction restores them."
        )
    if movement.transactions_with_correction_conflict:
        lines.append(
            f"Transactions keeping a source value because corrections disagree: "
            f"{movement.transactions_with_correction_conflict}. These are not possible duplicates "
            "or decision conflicts. Run review corrections."
        )
    if movement.transactions_with_correction_basis_changed:
        lines.append(
            f"Transactions keeping a source value because a correction binds records now in "
            f"several transactions: {movement.transactions_with_correction_basis_changed}. Run "
            "review corrections."
        )
    return lines


def describe_classifications(movement) -> list[str]:
    """Transactions a disagreement leaves unclassified, on their own lines (D-053)."""
    lines = []
    for count, reason in (
        (movement.transactions_with_classification_conflict, "classifications disagree"),
        (movement.transactions_with_classification_basis_changed,
         "a classification binds records now in several transactions"),
        (movement.transactions_with_classification_against_direction,
         "their amount runs against the stated type"),
    ):
        if count:
            lines.append(
                f"Transactions left unclassified because {reason}: {count}. These are not "
                "possible duplicates, decision conflicts or corrections. Run review "
                "classifications."
            )
    return lines


def describe_pending(movement) -> list[str]:
    """Pending-to-posted outcomes on their own lines (D-052)."""
    lines = []
    if movement.transactions_posted_at_changed_amount:
        lines.append(
            f"Transactions posted at another amount than their pending row, such as with a tip: "
            f"{movement.transactions_posted_at_changed_amount}. Each is counted once, at the "
            "posted amount."
        )
    if movement.stale_pending_transactions:
        lines.append(
            f"Pending transactions more than 10 days older than the account's latest date: "
            f"{movement.stale_pending_transactions}. They are counted, and none was removed."
        )
    return lines


def describe_declarations(movement) -> list[str]:
    """Coverage declared after import, on its own line (D-051)."""
    if not movement.documents_with_declared_coverage:
        return []
    return [
        f"Documents whose coverage you declared after import: "
        f"{movement.documents_with_declared_coverage}. Matching uses that coverage. Run review "
        "coverage history."
    ]


def describe_resolutions(movement) -> list[str]:
    """Completed and dismissed rows on their own lines, apart from everything else (D-050)."""
    lines = []
    if movement.transactions_completed:
        lines.append(
            f"Transactions holding a row you completed by hand: {movement.transactions_completed}. "
            "They are counted with the values you supplied. Run review resolutions."
        )
    if movement.records_dismissed:
        lines.append(
            f"Rows you dismissed as adding no transaction: {movement.records_dismissed}. They are "
            "not counted and are not unresolved. Run review resolutions."
        )
    return lines


def describe_conflicts(movement) -> list[str]:
    """Conflicts on their own lines, and only while there are some (D-044, D-045)."""
    if not movement.decision_conflicts:
        return []
    lines = [
        f"Decision conflicts: {movement.decision_conflicts}, covering "
        f"{movement.transactions_in_decision_conflicts} distinct affected transactions, all "
        "counted in full. These are not possible duplicates. One transaction can appear in "
        "several of these counts."
    ]
    if movement.transactions_with_withheld_match:
        lines.append(
            f"Transactions in conflicts where an automatic match was withheld: "
            f"{movement.transactions_with_withheld_match}. Their records stay separate, which "
            "can raise the transaction count and account movements."
        )
    if movement.transactions_with_changed_basis:
        lines.append(
            f"Transactions in conflicts where a decision's basis changed: "
            f"{movement.transactions_with_changed_basis}."
        )
    return lines


def describe_coverage_kind(coverage, document) -> str:
    """One coverage as documents prints it. Pending treatment follows its basis (D-026)."""
    line = f"coverage {coverage.kind}"
    if coverage.kind != "unknown":
        line += (f" {coverage.start or '?'} to {coverage.end or '?'}, {coverage.date_basis or 'no'}"
                 f" basis, evidence {coverage.evidence}")
    if coverage.kind == "complete":
        pending = document_pending_included(document, coverage.date_basis)
        line += f", pending {'included' if pending else 'excluded'}"
    return line


def document_pending_included(document, basis) -> bool:
    return dict(document.pending_included_by_basis)[basis]


def add_completed_values(out, supplied, indent) -> None:
    """What a person supplied, apart from what was read (D-050). None means nothing supplied."""
    labels = ("Amount", "Transaction date", "Posting date", "Description")
    out.add(f"{indent}Completed by hand, supplying what the parser could not read:")
    given = [(label, value) for label, value in zip(labels, supplied) if value is not None]
    for label, value in given:
        out.add(f"{indent}  {label}: {format_cents(value) if label == 'Amount' else shown(value)}")
    if not given:
        out.add(f"{indent}  Nothing supplied: every value was read, and the row was accepted as read")


def describe_role(record_id, primary_id, ranks) -> str:
    if primary_id is None:
        return "not recorded"
    if record_id == primary_id:
        return "primary, supplies the displayed values"
    return f"alternative, not selected on: {deciding_criterion(ranks[primary_id], ranks[record_id])}"


def describe_evidence(evidence: str) -> str:
    """Reason codes and dates only, so that no description or amount is printed."""
    details = json.loads(evidence)
    if "reasons" not in details:
        return ""
    reasons = ", ".join(details["reasons"])
    return f", {details['date_start']} to {details['date_end']}, reasons: {reasons}"


def shown(value) -> str:
    """A value as printed, or missing. Escapes keep a cell from imitating other output."""
    if not value:
        return "missing"
    text = str(value)
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode() for char in text
    )


def shown_amount(cents: int | None) -> str:
    return "missing" if cents is None else format_cents(cents)


def add_machine_reasons(out, item) -> None:
    out.add("Machine-generated reasons:")
    out.add(f"  {RULE_EXPLANATIONS.get(item.rule, f'Unresolved row: {item.rule}.')}")
    for reason in item.reasons:
        out.add(f"  {reason}: {REASON_EXPLANATIONS.get(reason, 'no explanation recorded')}")
    if item.date_start:
        out.add(f"  Dates involved: {item.date_start} to {item.date_end}")
    out.add(f"  {notice_for(item)}")


def notice_for(item) -> str:
    if item.unresolved:
        return UNRESOLVED_NOTICE
    return CONFLICT_NOTICE if item.kind == "decision_conflict" else DUPLICATE_NOTICE


DECIDED_HEADINGS = {
    "different_event": ("Already decided, as different events:", "is a different event from"),
    "same_event": ("Already decided, as one event:", "is the same event as"),
}


def add_decided_pairs(out, item) -> None:
    for relation, (heading, verb) in DECIDED_HEADINGS.items():
        pairs = [pair for pair in item.decided if pair.relation == relation]
        if pairs:
            out.add(heading)
        for pair in pairs:
            out.add(f"  Decision {pair.decision_id}:")
            out.add(f"    {describe_side(pair.left)}")
            out.add(f"    {verb} {describe_side(pair.right)}")


def add_alike_records(out, alike) -> None:
    """Evidence that a record repeats a decided one. It binds nothing (D-048)."""
    alike = list(islice(alike, DIRECT_PAIRS_SHOWN + 1))
    if not alike:
        return
    out.add("Alike a decided record, and not bound by any decision:")
    for entry in alike[:DIRECT_PAIRS_SHOWN]:
        out.add(
            f"  {shown(entry.record.file_name)} row {entry.record.row} matches "
            f"{shown(entry.decided.file_name)} row {entry.decided.row} in every parsed value, "
            f"decided by {', '.join(entry.decision_ids)}"
        )
    if len(alike) > DIRECT_PAIRS_SHOWN:
        out.add(f"  Only the first {DIRECT_PAIRS_SHOWN} are listed.")
    out.add("  No decision transfers to a new record. To decide one, confirm a partition here.")


def describe_side(records) -> str:
    return ", ".join(f"{shown(record.file_name)} row {record.row}" for record in records)


def add_direct_pairs(out, pairs) -> None:
    """Only these can be rejected. Sharing an item is not enough (D-045)."""
    listed = list(islice(pairs, DIRECT_PAIRS_SHOWN + 1))
    out.add("Direct candidate pairs, undecided:")
    if not listed:
        out.add("  None.")
    for left, right in map(sorted, listed[:DIRECT_PAIRS_SHOWN]):
        out.add(f"  {left} {right}")
    if len(listed) > DIRECT_PAIRS_SHOWN:
        out.add(f"  Only the first {DIRECT_PAIRS_SHOWN} are listed. Other pairs here may also be direct.")


def add_transaction_evidence(out, entry, shared) -> None:
    out.add("  Current logical transaction values:")
    out.add(f"    Transaction date: {shown(entry.transaction_date)}")
    out.add(f"    Posting date: {shown(entry.posting_date)}")
    out.add(f"    Amount: {shown_amount(entry.amount_cents)}")
    out.add(f"    Status: {entry.settlement_status}")
    out.add(f"    Description: {shown(entry.description)}")
    out.add(f"    External ID: {shown(entry.external_id)}")

    ranks = {
        record.record_id: primary_rank(
            record.parsed.settlement_status, *_effective_rank_values(record),
            record.content_sha256, record.row, completed_by_hand=record.completion is not None,
        )
        for record in entry.records
    }
    primary = next(
        (record for record in entry.records
         if (record.content_sha256, record.row) == entry.primary_source),
        None,
    )
    primary_id = primary.record_id if primary else None
    out.add("  Primary-source selection:")
    if primary is None:
        out.add("    Not recorded. Run reconcile to record it.")
    else:
        out.add(f"    {primary.file_name} row {primary.row} supplies the values above")
    for record in entry.records:
        add_record_evidence(out, record, describe_role(record.record_id, primary_id, ranks), shared)
    add_corrections(out, entry)
    add_classifications(out, entry)
    add_transfers(out, entry)


def _effective_rank_values(record):
    """Dates and description as derivation ranked them (D-050)."""
    parsed, completion = record.parsed, record.completion
    if completion is None:
        return parsed.transaction_date, parsed.posting_date, parsed.description
    return (parsed.transaction_date or completion.transaction_date,
            parsed.posting_date or completion.posting_date,
            parsed.description or completion.description)


def add_corrections(out, entry) -> None:
    """Corrections stay apart from the source values above (D-049)."""
    if not entry.corrections:
        return
    out.add("  Corrections, kept apart from the source values above:")
    for correction in entry.corrections:
        out.add(
            f"    Correction {correction.correction_id}: {correction.field} corrected to "
            f"{shown_corrected_value(correction.field, correction.corrected_value)}, binding "
            f"{describe_side(correction.bound_records)}"
        )
    state_by_field = {correction.field: correction.field_state for correction in entry.corrections}
    for field, state in sorted(state_by_field.items()):
        out.add(f"    {field}: {FIELD_STATE_EXPLANATIONS[state]}")


def add_classifications(out, entry) -> None:
    """Classifications stay apart from the source values, like corrections (D-053)."""
    if not entry.classifications:
        out.add(f"  Financial type: {UNCLASSIFIED}")
        return
    out.add("  Classifications:")
    for classification in entry.classifications:
        out.add(
            f"    Classification {classification.classification_id}: "
            f"{classification.financial_type}, binding {describe_side(classification.bound_records)}"
        )
    state = entry.classifications[0].state
    out.add(f"    Financial type: {CLASSIFICATION_STATE_EXPLANATIONS[state]}")


def add_transfers(out, entry) -> None:
    """Transfer matches binding this transaction's records (D-054)."""
    for transfer in entry.transfers:
        out.add(f"  Transfer match {transfer.match_id}, this transaction's side: {transfer.side}")
        out.add(f"    Binding here: {describe_side(transfer.bound_records)}")
        out.add(f"    Binding on the other side: {describe_side(transfer.counterpart_bound_records)}")
        if transfer.counterpart_transaction_id:
            out.add(f"    Other side now: transaction {transfer.counterpart_transaction_id}")
        out.add(f"    Transfer: {MATCH_STATE_EXPLANATIONS[transfer.state]}")
    for statement in entry.one_sided_transfers:
        out.add(f"  One-sided transfer {statement.one_sided_transfer_id}, counterpart: "
              f"{shown(statement.counterpart_account)}")
        out.add(f"    Binding: {describe_side(statement.bound_records)}")
        out.add(f"    Transfer: {ONE_SIDED_STATE_EXPLANATIONS[statement.state]}")


def shown_corrected_value(field, value) -> str:
    return format_cents(value) if field == "amount" else shown(value)


def add_record_evidence(out, record, role, shared) -> None:
    parsed = record.parsed
    out.add(f"  Source {record.file_name}, row {record.row}")
    out.add(f"    Record: {record.record_id}")
    out.add(f"    Role: {role}")
    out.add(f"    Link rule: {record.link_rule or 'none'}")
    if record.content_sha256 in shared:
        out.add("    Shares its document with another record in this item")
    out.add(f"    Original source cells: {list(record.cells)}")
    out.add("    Parsed source values:")
    out.add(f"      Result: {parsed.status}{f' ({parsed.reason_code})' if parsed.reason_code else ''}")
    out.add(f"      Transaction date: {shown(parsed.transaction_date)}")
    out.add(f"      Posting date: {shown(parsed.posting_date)}")
    out.add(f"      Amount: {shown_amount(parsed.amount_cents)}")
    out.add(f"      Status: {parsed.settlement_status}")
    out.add(f"      Description: {shown(parsed.description)}")
    out.add(f"      External ID: {shown(parsed.external_id)}")
    completion = record.completion
    if completion is not None:
        add_completed_values(out, (completion.amount_cents, completion.transaction_date,
                                completion.posting_date, completion.description), "    ")


def add_document_evidence(out, document) -> None:
    out.add(f"  {document.file_name}")
    out.add(f"    Document SHA-256: {document.content_sha256}")
    out.add(f"    Layout: {document.layout_id}, parser version {document.parser_version}")
    out.add(f"    Coverage kind: {document.coverage_kind}")
    out.add(f"    Claimed interval: {shown(document.coverage_start)} to {shown(document.coverage_end)}")
    out.add(f"    Date basis: {shown(document.date_basis)}")
    out.add(f"    Coverage evidence: {shown(document.coverage_evidence)}")
    out.add(f"    Generated on: {shown(document.generated_on)}")
    if document.declared is not None:
        declared = document.declared
        interval = (f" {declared.coverage_start} to {declared.coverage_end}, "
                    f"{declared.date_basis} basis" if declared.coverage_kind == "complete" else "")
        out.add(f"    Declared after import, which matching uses: {declared.coverage_kind}{interval}")
    if document.effective_end is not None:
        out.add(f"    Last date matching relies on: {document.effective_end}")
        out.add(f"    Pending rows: {'included' if document.pending_covered else 'excluded'}")
    out.add(f"    External ID guarantee: {document.id_guarantee}")


def out_and_in(group) -> str:
    return (f"{group.transactions} transactions, {format_cents(group.out_cents)} out and "
            f"{format_cents(group.in_cents)} in")


def add_income_and_spending(out, groups) -> None:
    """Five groups, each transaction in one, adding to net account movement (D-056)."""
    out.add("Income and spending, as you classified and matched them:")
    add_income_and_spending_groups(out, groups)


def add_income_and_spending_groups(out, groups) -> None:
    income, spending = groups.income, groups.spending
    out.add(f"  Income: {income.transactions} transactions, "
          f"{format_cents(income.in_cents - income.out_cents)}")
    out.add(f"  Spending: {spending.transactions} transactions, "
          f"{format_cents(spending.out_cents - spending.in_cents)}")
    for financial_type, group in groups.spending_by_type:
        out.add(f"    {financial_type}: {group.transactions} transactions, "
              f"{format_cents(group.out_cents - group.in_cents)}")
    out.add(f"  Confirmed transfers: {out_and_in(groups.confirmed_transfers)}")
    for financial_type, group in groups.confirmed_transfers_by_type:
        out.add(f"    {financial_type}: {out_and_in(group)}")
    out.add(f"  Of a transfer kind, not confirmed: {out_and_in(groups.unconfirmed_transfer_kinds)}")
    out.add(f"  Unclassified: {out_and_in(groups.unclassified)}")


def add_month(out, month) -> None:
    out.add(
        f"{month.month}: net account movement {format_cents(month.net_cents)} over "
        f"{month.transactions} transactions, of which pending: {month.pending_transactions}"
    )
    out.add(f"  Dated by transaction date: {month.dated_by_transaction_date}, "
          f"by posting date: {month.dated_by_posting_date}")
    add_income_and_spending_groups(out, month.income_and_spending)
    if month.open_review_items:
        out.add(f"  Open review items: {len(month.open_review_items)}, holding "
              f"{month.transactions_in_open_review_items} transactions here")
    for count, label in (
        (month.transactions_with_unsettled_correction, "an unsettled correction"),
        (month.transactions_with_unsettled_classification, "an unsettled classification"),
        (month.transactions_with_unsettled_match, "a transfer match that no longer applies"),
        (month.transactions_with_unsettled_one_sided_transfer,
         "a one-sided transfer that no longer applies"),
    ):
        if count:
            out.add(f"  With {label}: {count} transactions")
    if month.matched_sides_with_other_side_in_another_month:
        out.add(
            f"  Matched transfers whose other side is in another month: "
            f"{month.matched_sides_with_other_side_in_another_month}, so this month's movement "
            "includes them"
        )


def describe_income_and_spending(groups) -> list[str]:
    """How far income and spending may be understated, from what they leave out (D-011, D-056)."""
    unconfirmed, unclassified = groups.unconfirmed_transfer_kinds, groups.unclassified
    if not (unconfirmed.transactions or unclassified.transactions):
        return []
    return [
        "Income and spending count only what you classified, and leave out transfers you "
        "confirmed. Spending may be understated by up to "
        f"{format_cents(unconfirmed.out_cents + unclassified.out_cents)} and income by up to "
        f"{format_cents(unconfirmed.in_cents + unclassified.in_cents)}, the money out and in of "
        "transactions of a transfer kind not confirmed and of unclassified transactions."
    ]


def describe_transfers(transfers) -> list[str]:
    """Matches that no longer apply, and unmatched candidates, on their own lines (D-011, D-054)."""
    lines = [
        f"{count} transfer matches no longer apply, because {reason}. Their transactions count as "
        "unmatched. Run review transfers."
        for count, reason in (
            (transfers.basis_changed, "a side's bound records are now in several transactions"),
            (transfers.conflicts, "a transaction holds records of two matches"),
            (transfers.amounts_differ, "the amounts no longer offset exactly"),
            (transfers.types_differ, "a type no longer fits a transfer between those accounts"),
        )
        if count
    ]
    if transfers.transactions_in_candidates:
        lines.append(
            f"{transfers.transactions_in_candidates} transactions may be transfers between your "
            "accounts and are not matched. Each still counts as the type stated, or unclassified. "
            "Run review transfers."
        )
    return lines


def describe_one_sided(one_sided) -> list[str]:
    """Coverage warnings for one-sided transfers, and those that no longer apply (D-012, D-055)."""
    lines = []
    if one_sided.applied:
        lines.append(
            f"{one_sided.applied} one-sided transfers rest on another account whose side is not in "
            f"the ledger: {one_sided.counterpart_without_documents} where that account has no "
            f"documents, {one_sided.counterpart_partly_covered} where its documents do not cover "
            "every day within "
            f"{TRANSFER_DATE_WINDOW_DAYS} days. Import its statements, or declare their coverage, "
            "to check them."
        )
    if one_sided.card_payments_without_history:
        lines.append(
            f"{one_sided.card_payments_without_history} card payments, "
            f"{format_cents(one_sided.card_payments_without_history_cents)}, go to a card whose "
            "purchases for those dates are not in the ledger, so spending on that card is "
            "understated."
        )
    if one_sided.loan_payments_without_history:
        lines.append(
            f"{one_sided.loan_payments_without_history} loan payments, "
            f"{format_cents(one_sided.loan_payments_without_history_cents)}, go to a loan whose "
            "interest for those dates is not in the ledger, so spending on interest is "
            "understated."
        )
    lines += [
        f"{count} one-sided transfers no longer apply, because {reason}. Their transactions count "
        "as unpaired. Run review transfers."
        for count, reason in (
            (one_sided.basis_changed, "their bound records are now in several transactions"),
            (one_sided.conflicts, "a transaction holds records of another match or one-sided "
                                  "transfer"),
            (one_sided.types_differ, "a type no longer fits a transfer to the counterpart"),
            (one_sided.counterparts_found, "a transaction of the counterpart may be the other "
                                           "side"),
            (one_sided.counterparts_covered, "the counterpart's complete coverage spans their "
                                             "dates"),
        )
        if count
    ]
    return lines



def account_choices(conn) -> list[tuple[str, str]]:
    """Each account's ID and name, for choosing one."""
    return conn.execute(
        "SELECT id, display_name FROM account ORDER BY display_name, id"
    ).fetchall()


def totals_report_lines(conn, account_id) -> ReportLines:
    movement = account_movement(conn, account_id)
    groups = income_and_spending(conn, account_id)
    transfers = transfer_summary(conn, account_id)
    one_sided = one_sided_summary(conn, account_id)
    stale = stale_accounts(conn, DEFAULT_RULES, account_id)

    out = ReportLines()
    out.add(f"Account inflows: {format_cents(movement.inflow_cents)}")
    out.add(f"Account outflows: {format_cents(movement.outflow_cents)}")
    out.add(f"Net account movement: {format_cents(movement.net_cents)}")
    out.add(f"Transactions: {movement.transactions}, of which pending: "
            f"{movement.pending_transactions}")
    out.add("By financial type, as you classified them:")
    for financial_type, count, cents in movement.financial_types:
        out.add(f"  {financial_type}: {count} transactions, {format_cents(cents)}")
    out.add(
        f"  {UNCLASSIFIED}: {movement.unclassified_transactions} transactions, "
        f"{format_cents(movement.unclassified_cents)}"
    )
    out.add("Transfers between your accounts, as you matched them:")
    out.add(f"  Matched: {transfers.matches} pairs, moving {format_cents(transfers.matched_cents)}")
    out.add(f"  In a candidate pair, not matched: {transfers.transactions_in_candidates} "
            "transactions")
    out.add(
        f"  One-sided, the other side not in the ledger: {one_sided.applied} transactions, "
        f"{format_cents(one_sided.out_cents)} out and {format_cents(one_sided.in_cents)} in"
    )
    out.add(
        f"  Of a transfer kind with no match, candidate or one-sided transfer: "
        f"{transfers.unpaired_transfer_kind} transactions"
    )
    add_income_and_spending(out, groups)
    out.add("Disclosures:")
    out.add("- These are account movements. They include transfers and card payments.")
    out.add(f"- {MATCHING_NOTICE}")
    if stale:
        out.add(
            f"- {len(stale)} accounts have not been reconciled under the current matching "
            "rules, so overlapping files there may be counted twice, or their transactions "
            "may not record a primary source. Run reconcile."
        )
    if movement.unresolved_records:
        out.add(
            f"- {movement.unresolved_records} unresolved records are not included, "
            "and their amounts may be unknown."
        )
    if movement.candidate_groups:
        out.add(
            f"- {movement.candidate_groups} possible-duplicate groups cover "
            f"{movement.transactions_in_candidate_groups} distinct transactions, "
            "all counted in full. "
            "Totals may be overstated, and no exact adjustment can be stated."
        )
    for line in describe_conflicts(movement):
        out.add(f"- {line}")
    if movement.transactions_confirmed:
        out.add(
            f"- {movement.transactions_confirmed} transactions hold records you confirmed as one "
            "event, and each is counted once. Undoing a confirmation can raise totals."
        )
    if movement.transactions_separated:
        out.add(
            f"- {movement.transactions_separated} transactions hold records you separated from an "
            "automatic match, and each is counted. Undoing a separation can lower totals."
        )
    for line in describe_corrections(movement):
        out.add(f"- {line}")
    for line in (*describe_resolutions(movement), *describe_declarations(movement),
                 *describe_pending(movement), *describe_classifications(movement),
                 *describe_transfers(transfers), *describe_one_sided(one_sided),
                 *describe_income_and_spending(groups)):
        out.add(f"- {line}")
    return out


def monthly_report_lines(conn, account_id, first_month, last_month) -> ReportLines:
    report = monthly_report(conn, account_id, first_month, last_month)
    stale = stale_accounts(conn, DEFAULT_RULES, account_id)

    out = ReportLines()
    if not report.months:
        out.add("No transactions, so there are no months to show.")
    for month in report.months:
        add_month(out, month)
        if month.accounts_covered:
            out.add("  Covered for the whole month: "
                    + ", ".join(shown(name) for name in month.accounts_covered))
        if month.accounts_not_covered:
            out.add("  Not covered for the whole month: "
                    + ", ".join(shown(name) for name in month.accounts_not_covered))

    out.add("Disclosures:")
    out.add(
        "- Each transaction is in the month of its effective transaction date, else its "
        "effective posting date. Amounts are account movements, with pending transactions "
        "counted as in totals."
    )
    out.add(
        "- A month is covered for an account only when complete transaction-basis coverage spans "
        "every day of it. A month not covered may be missing transactions."
    )
    if report.transactions_outside_range:
        out.add(
            f"- {report.transactions_outside_range} transactions, "
            f"{format_cents(report.net_cents_outside_range)}, are in months outside this range."
        )
    if report.unresolved_records:
        out.add(
            f"- {report.unresolved_records} unresolved records are no transaction, so no month "
            "counts them, and their amounts may be unknown."
        )
    if stale:
        out.add(
            f"- {len(stale)} accounts have not been reconciled under the current matching "
            "rules, so overlapping files there may be counted twice. Run reconcile."
        )
    return out


def document_list_lines(conn) -> ReportLines:
    rows = conn.execute(
        """SELECT document.id, document.file_name, document.layout_id, account.display_name,
                  coverage_kind, coverage_start, coverage_end, date_basis, evidence,
                  (SELECT COUNT(*) FROM source_record record
                   WHERE record.source_document_id = document.id),
                  CASE date_basis WHEN 'transaction' THEN pending_in_transaction_basis
                                  ELSE pending_in_posting_basis END
           FROM source_document document
           JOIN document_coverage coverage ON coverage.source_document_id = document.id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           JOIN account ON account.id = coverage.account_id
           ORDER BY document.imported_at, document.file_name"""
    ).fetchall()
    out = ReportLines()
    for document_id, name, layout_id, account, kind, start, end, basis, evidence, records, _ in rows:
        line = f"{name}: {records} records, account {account}, layout {layout_id}, "
        document = load_document_coverage(conn, document_id)
        line += describe_coverage_kind(document.effective, document)
        if document.declaration_id:
            line += f", declared after import, claimed at import: {kind}"
        out.add(f"Document {document_id}: {line}")
    if not rows:
        out.add("No documents.")
    return out


def transaction_list_lines(conn) -> ReportLines:
    # Effective values: a corrected value where one applies, else the source value (D-049).
    rows = conn.execute(
        """SELECT entry.id,
                  COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date,
                           fixed_posting_date.corrected_text, entry.posting_date) AS shown_date,
                  COALESCE(fixed_amount.corrected_amount_cents, entry.amount_cents),
                  entry.settlement_status,
                  COALESCE(fixed_description.corrected_text, entry.description),
                  EXISTS (SELECT 1 FROM transaction_correction fix
                          WHERE fix.transaction_id = entry.id AND fix.state = 'applied'),
                  EXISTS (SELECT 1 FROM record_resolution completion
                          WHERE completion.source_record_id = entry.primary_source_record_id
                            AND completion.kind = 'completed'
                            AND NOT EXISTS (SELECT 1 FROM record_resolution_event undone
                                            WHERE undone.resolution_id = completion.id
                                              AND undone.event = 'undone'))
           FROM ledger_transaction entry
           LEFT JOIN transaction_correction fixed_amount
               ON fixed_amount.transaction_id = entry.id AND fixed_amount.field = 'amount'
              AND fixed_amount.state = 'applied'
           LEFT JOIN transaction_correction fixed_transaction_date
               ON fixed_transaction_date.transaction_id = entry.id
              AND fixed_transaction_date.field = 'transaction_date'
              AND fixed_transaction_date.state = 'applied'
           LEFT JOIN transaction_correction fixed_posting_date
               ON fixed_posting_date.transaction_id = entry.id
              AND fixed_posting_date.field = 'posting_date'
              AND fixed_posting_date.state = 'applied'
           LEFT JOIN transaction_correction fixed_description
               ON fixed_description.transaction_id = entry.id
              AND fixed_description.field = 'description'
              AND fixed_description.state = 'applied'
           ORDER BY shown_date, entry.id"""
    ).fetchall()
    out = ReportLines()
    for transaction_id, when, cents, status, description, corrected, completed in rows:
        marker = "  (corrected)" if corrected else ""
        marker += "  (completed by hand)" if completed else ""
        out.add(
            f"{transaction_id}  {when}  {format_cents(cents):>12}  {status:<8}  "
            f"{shown(description) if description else ''}{marker}"
        )
    if not rows:
        out.add("No transactions.")
    return out


def review_queue_lines(conn) -> ReportLines:
    rows = conn.execute(
        """SELECT issue.id, issue.kind, issue.rule, issue.evidence_json,
                  COUNT(subject.transaction_id), MIN(document.file_name),
                  MIN(record.record_index)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           LEFT JOIN source_record record ON record.id = subject.source_record_id
           LEFT JOIN source_document document ON document.id = record.source_document_id
           WHERE issue.status = 'open'
           GROUP BY issue.id
           ORDER BY issue.kind, MIN(document.file_name), MIN(record.record_index), issue.rule"""
    ).fetchall()
    out = ReportLines()
    for issue, kind, rule, evidence, members, file_name, index in rows:
        if kind == "unresolved_record":
            out.add(f"Item {issue}: {kind}: {rule}, {file_name} row {index}", issue)
            continue
        out.add(f"Item {issue}: {kind}: {rule}, {members} transactions"
                f"{describe_evidence(evidence)}", issue)
        subjects = conn.execute(
            """SELECT transaction_id FROM review_issue_subject
               WHERE review_issue_id = ? ORDER BY transaction_id""",
            (issue,),
        ).fetchall()
        for (transaction_id,) in subjects:
            out.add(f"  Transaction {transaction_id}")
    out.add(f"Open review items: {len(rows)}")
    conflicts = sum(row[1] == "decision_conflict" for row in rows)
    if conflicts:
        out.add(f"Of which decision conflicts, which are not possible duplicates: {conflicts}")
    if rows:
        out.add("To see an item's evidence, including amounts and descriptions, run review show.")
    return out


def review_item_report(conn, item_id) -> ReviewItemReport | None:
    """One item's evidence as review show prints it, or None when there is no such item."""
    item = load_review_evidence(conn, item_id)
    if item is None:
        return None
    revision = review_revision(item)

    out = ReportLines()
    out.add(f"Review item {item.issue_id}")
    out.add(f"  Account: {shown(item.account_name)} ({item.account_id})")
    out.add(f"  Kind: {item.kind}")
    out.add(f"  Rule: {item.rule}")
    out.add(f"  Status: {item.status}")
    out.add(f"  Revision: {revision}")
    add_machine_reasons(out, item)
    add_decided_pairs(out, item)
    add_alike_records(out, alike_decided_records(item))
    if item.rule == RULE_CANDIDATES and item.status == "open":
        add_direct_pairs(out, undecided_direct_pairs(conn, item))

    shared = rows_sharing_a_document(item)
    names = {document.content_sha256: document.file_name for document in item.documents}
    if shared:
        out.add("Records from the same document:")
    for digest, rows in shared.items():
        out.add(f"  {names[digest]}: rows {', '.join(map(str, rows))}")

    for number, entry in enumerate(item.transactions, start=1):
        out.add(f"Transaction {number} of {len(item.transactions)}: {entry.transaction_id}")
        add_transaction_evidence(out, entry, shared)
    for record in item.unresolved:
        add_record_evidence(out, record, "unresolved, no transaction", shared)

    out.add("Coverage evidence:")
    for document in item.documents:
        add_document_evidence(out, document)
    if item.account_stale:
        out.add(
            "This account has not been reconciled under the current matching rules, so this "
            "evidence may be out of date. Run reconcile."
        )
    return ReviewItemReport(item.issue_id, item.kind, item.account_id, revision, out)
