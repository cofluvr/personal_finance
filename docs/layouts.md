# Document Layouts

A layout says exactly how one document format is read. Support is defined only by
tested layouts. The two synthetic layouts are invented for development. **The institution
layouts are unverified** (D-059): each is written from the lead engineer's knowledge of the
export, not from a sample, and its fixture is invented. Each stays unverified until one real
file of it reconciles with its statement, D-059 point F. What a header cannot show is listed
under each as an assumption.

A layout's meaning never changes once used. A change needs a new `layout_id`, so
stored documents keep the meaning they were imported under. The one exception is a
synthetic-only clarification of `synthetic_checking_v1` IDs (D-026), which does not
apply to real layouts.

## What "complete" means

A complete coverage claim says: every transaction for this account whose date, on
the stated basis, falls within the inclusive interval is present in this document.

- It says nothing about dates outside the interval. Rows there are allowed.
- It covers one account.
- It comes from document metadata or a user declaration, never from row dates.
- A user declaration vouches for the whole end date, under the layout's pending
  definition below. Document metadata does not, unless its generation date shows
  the end date had passed (D-007). Dates on or after a metadata document's generation
  date do not establish completeness (D-027).
- It does not mean every row was parsed. Unresolved rows stay disclosed (D-024).

## synthetic_checking_v1

Columns: `Transaction ID, Transaction Date, Posted Date, Description, Amount, Status`.

| Property | Meaning |
|---|---|
| Amount | Signed. Negative is money leaving the account |
| Dates | `YYYY-MM-DD`. Blank stays missing, and one date is enough |
| Status | `PENDING`, `POSTED`, or blank (unknown) |
| Transaction ID | Declared reliable: stable across exports and unique within this layout's namespace for one account (D-026) |
| Metadata | Optional `# key: value` lines before the header |
| Coverage | Metadata or user declaration, on either date basis |

Complete coverage and pending transactions:

| Date basis | Claim | Pending |
|---|---|---|
| `posting` | Every posted transaction with a posting date in the interval | **Excluded.** Pending rows have no posting date, so they may appear but the claim says nothing about them |
| `transaction` | Every posted transaction with a transaction date in the interval, and every transaction pending when the document was generated | **Included** |

Metadata keys: `coverage-kind` (`complete`, `partial`, `unknown`), `coverage-start`,
`coverage-end`, `coverage-basis`, `generated-on`. Unknown, repeated or inconsistent
metadata fails the file rather than being ignored. A file without metadata has
unknown coverage.

## synthetic_card_v1

Columns: `Date, Description, Debit, Credit`.

| Property | Meaning |
|---|---|
| Debit | A positive charge. Stored as negative cents |
| Credit | A positive payment or refund. Stored as positive cents |
| Amount rule | Exactly one of the two must be filled. Both filled, or a negative value, leaves the row unresolved |
| Date | `MM/DD/YYYY`, defined as the posting date. Stored as the posting date only |
| Status | Every row is posted, by this layout's definition |
| Transaction ID | None |
| Metadata | None |
| Coverage | User declaration only, on the `posting` basis only |

Complete coverage and pending transactions:

| Date basis | Claim | Pending |
|---|---|---|
| `posting` | Every posted transaction with a date in the interval | **Excluded.** This export never contains pending transactions |

## Institution layouts: rules common to all

| Property | Meaning |
|---|---|
| Header | Must match exactly, or the file fails as `header_mismatch` and imports nothing |
| Status | `unknown` where the export does not state it, which D-006 never reads as `posted`. `bfsfcu_v1` states it |
| Transaction ID | None read, guarantee `none` (D-059 point B). Identical rows in one file are separate events, kept apart by row number |
| Metadata | None. A `#` line fails the header |
| Coverage | User declaration only, on the bases listed under each. Pending rows are not in the export, so a complete claim says nothing about them |
| Unread columns | Category, card number and running balance stay in the raw cells (D-014, D-057). An account number column is read only to check it, as in `capital_one_bank_v1` |

## capital_one_card_v1

Columns: `Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit`.

| Property | Meaning |
|---|---|
| Debit, Credit | As `synthetic_card_v1`: exactly one filled, never negative. A debit is stored negative |
| Dates | `YYYY-MM-DD`, as the column names say. Coverage on either basis |
| Confirmed | Header, date format, Debit for a charge and Credit for a payment, and newest-first order, from the owner's export on 2026-11-09 |
| Assumptions | The export holds posted transactions only |

## capital_one_bank_v1

Columns: `Account Number, Transaction Description, Transaction Date, Transaction Type,
Transaction Amount, Balance`.

| Property | Meaning |
|---|---|
| Amount | `Transaction Amount` never negative. `Transaction Type` `Debit` stores it negative, `Credit` positive, any other value leaves the row `invalid_direction` |
| Date | `MM/DD/YY`, the transaction date. Coverage on the `transaction` basis only |
| Account Number | The account's last four digits. Every row must name the importing account's registered `--last4`, else the file fails as `account_number_mismatch`, and an account with none fails it as `account_number_unknown` (D-061) |
| Confirmed | Header, date format, a positive amount with `Debit` or `Credit`, trailing zeros dropped (`1400`, `14.1`), a running balance after each row, and newest-first order, from the owner's savings and checking exports on 2026-11-09 |
| Assumptions | The export holds posted transactions only, and the date is the transaction date |

## us_bank_v1

Columns: `Date, Transaction, Name, Memo, Amount`, each quoted. U.S. Bank's CSV activity list;
its PDF statements are M7 (D-059 point D).

| Property | Meaning |
|---|---|
| Amount | Signed, negative for money out. `Transaction` `DEBIT` or `CREDIT` must agree, else `conflicting_amount`. Any other value leaves the row `invalid_direction` |
| Description | `Name`. `Memo` stays in the raw cells, unread |
| Date | `YYYY-MM-DD`, the posting date. Coverage on the `posting` basis only |
| Assumptions | The export holds posted transactions only, and its date is the posting date |

## amex_card_v1

Columns: `Date, Description, Amount`.

| Property | Meaning |
|---|---|
| Amount | Signed, **positive for a charge**, so stored negated: a charge is money out, a payment or credit money in |
| Date | `MM/DD/YYYY`, the posting date. Coverage on the `posting` basis only |
| Confirmed | Header, date format, a charge positive and a payment negative, and newest-first order, from the owner's export on 2026-11-09 |
| Assumptions | The export holds posted transactions only, and its date is the posting date |

## bfsfcu_v1

Columns, each quoted: `Transaction ID, Posting Date, Effective Date, Transaction Type, Posting
Status, Amount, Check Number, Reference Number, Description, Transaction Category, Type, Balance,
Memo, Extended Description`. The header and row format come from the owner's real export (D-059
point E). No value from it is kept, and the layout stays unverified until point F passes.

| Property | Meaning |
|---|---|
| Amount | Signed, negative for money out, with five decimals. A digit beyond the cent leaves the row `invalid_amount`. `Transaction Type` `Debit` or `Credit` must agree, else `conflicting_amount`, and any other value is `invalid_direction` |
| Status | `Posting Status` `Posted`. Any other value, `Pending` included, leaves the row `invalid_status`, since only `Posted` has been seen |
| Date | `Posting Date`, `M/D/YYYY`, the posting date. Coverage on the `posting` basis only. `Effective Date` can fall after it, so it is not read as the transaction date |
| Unread | `Transaction ID`, `Reference Number`, `Check Number`, `Effective Date`, the categories, `Balance`, `Memo` and `Extended Description` |
| Order | Newest first. Order carries no meaning |
| Assumptions | Pending transactions are absent or marked otherwise than `Posted` |

## us_bank_card_activity_pdf_v1

U.S. Bank's Recent Activity List for a credit card, printed from its website to PDF and read with
pypdf in layout mode (D-060 point 1). The structure comes from the owner's printout on 2026-11-09,
its values never kept (D-060, as amended). It is an activity list, not a statement: it states no
period and no balance.

| Property | Meaning |
|---|---|
| Structure | Every page starts with the printout's header, `M/D/YY, H:MM AM` then `Recent Activity List \| U.S. Bank`, and page 1 goes on to `Posted`. Otherwise the file fails as `statement_structure_mismatch` |
| Row | An entry line, `MM/DD/YYYY`, the description and the amount, separated by two or more spaces, then its account line, `Credit Card ...` and four digits, which can fall after a page break. Stored as the page, the entry line and the account line |
| Other lines | Any other line is an unresolved row, `unrecognized_line`, keeping its text. An entry with no account line is `missing_account_line`. No line is skipped but a page header and `Posted` |
| Amount | Signed, **positive for a charge**, so stored negated, as `amex_card_v1`. A payment or statement credit is negative, so money in. `$` and commas are read |
| Date | The posting date, as the entries sit under `Posted`. Coverage by user declaration on the `posting` basis only |
| Status | `posted` |
| Account | A credit card account only, else `account_type_mismatch`. Every account line must name the account's registered `--last4`, as D-061 |
| Parser version | `1+pypdf-6.21.2`, so another pypdf release is another interpretation (D-026) |
| Assumptions | The date is the posting date, a description never wraps onto a second line, and only posted activity is listed. A `Pending` section would leave an unresolved row |

## Test-only layouts

Tests may define extra synthetic layouts, such as one with unreliable external IDs
for A21. These live in the tests, and are not supported or production layouts.

## Rows that may be one event

Identical rows of the same status are separate events in every layout here. Each
institution layout must show this on a real file (D-059 point F). Evidence
that rows may be one event is flagged under D-021.

## What counts as a row

These definitions apply to every layout and are what import summaries count (D-036).

- A **source row** is a data row after the metadata lines and the header. Those are not rows.
- A completely blank line is not a row. Nothing is stored for it, and row numbers skip it.
- A line of spaces, or of empty cells such as `,,,`, is a row, and it ends up unresolved.
- Every source row of an imported file is either a **valid record** or an **unresolved
  record**, so rows read = valid + unresolved.
- Row numbers count source rows from 1. They are not file line numbers.
- A failed file keeps no rows. Its rows are never counted as read or stored.

## Unresolved row reasons

`missing_amount`, `missing_date`, `invalid_amount`, `invalid_date`, `invalid_status`,
`invalid_direction`, `conflicting_amount`, `wrong_column_count`, `unrecognized_line`,
`missing_account_line`. Each row keeps its original cells and creates no transaction.

## File failure codes

`unreadable_file`, `invalid_encoding`, `malformed_csv`, `header_mismatch`,
`invalid_coverage_metadata`, `coverage_basis_unavailable`, `coverage_conflict`,
`account_mismatch`, `account_number_unknown`, `account_number_mismatch`, `account_type_mismatch`,
`encrypted_pdf`, `no_text_layer`, `unreadable_pdf`, `statement_structure_mismatch`, `layout_mismatch`, `layout_definition_changed`, `database_busy`,
`internal_error`.
