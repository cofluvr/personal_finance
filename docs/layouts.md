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
| Status | `unknown`: no export states it, and D-006 never reads it as `posted` |
| Transaction ID | None, guarantee `none` (D-059 point B). Identical rows in one file are separate events, kept apart by row number |
| Metadata | None. A `#` line fails the header |
| Coverage | User declaration only, on the bases listed under each. Pending rows are not in the export, so a complete claim says nothing about them |
| Unread columns | Category, card or account number and running balance stay in the raw cells (D-014, D-057) |

## capital_one_card_v1

Columns: `Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit`.

| Property | Meaning |
|---|---|
| Debit, Credit | As `synthetic_card_v1`: exactly one filled, never negative. A debit is stored negative |
| Dates | `YYYY-MM-DD`, as the column names say. Coverage on either basis |
| Assumptions | The export holds posted transactions only, and Debit is money out |

## capital_one_bank_v1

Columns: `Account Number, Transaction Description, Transaction Date, Transaction Type,
Transaction Amount, Balance`.

| Property | Meaning |
|---|---|
| Amount | `Transaction Amount` never negative. `Transaction Type` `Debit` stores it negative, `Credit` positive, any other value leaves the row `invalid_direction` |
| Date | `MM/DD/YY`, the transaction date. Coverage on the `transaction` basis only |
| Assumptions | The export holds posted transactions only, the date is the transaction date, and Balance is a running balance |

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
| Amount | Signed, **positive for a charge**, so stored negated: a charge is money out, a payment or credit money in. Nothing in a row can confirm the sign |
| Date | `MM/DD/YYYY`, the posting date. Coverage on the `posting` basis only |
| Assumptions | The sign, the export holds posted transactions only, and its date is the posting date. The sign is checked only by D-059 point F |

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
`invalid_direction`, `conflicting_amount`, `wrong_column_count`. Each row keeps its original cells and
creates no transaction.

## File failure codes

`unreadable_file`, `invalid_encoding`, `malformed_csv`, `header_mismatch`,
`invalid_coverage_metadata`, `coverage_basis_unavailable`, `coverage_conflict`,
`account_mismatch`, `layout_mismatch`, `layout_definition_changed`, `database_busy`,
`internal_error`.
