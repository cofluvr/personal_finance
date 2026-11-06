# Document Layouts

A layout says exactly how one document format is read. Support is defined only by
tested layouts. **No real institution's format is supported.** Both layouts below
are invented for development.

A layout's meaning never changes once used. A change needs a new `layout_id`, so
stored documents keep the meaning they were imported under.

## What "complete" means

A complete coverage claim says: every transaction for this account whose date, on
the stated basis, falls within the inclusive interval is present in this document.

- It says nothing about dates outside the interval. Rows there are allowed.
- It covers one account.
- It comes from document metadata or a user declaration, never from row dates.
- The end date is included in full. Boundary dates are treated cautiously when
  matching (D-007).

## synthetic_checking_v1

Columns: `Transaction ID, Transaction Date, Posted Date, Description, Amount, Status`.

| Property | Meaning |
|---|---|
| Amount | Signed. Negative is money leaving the account |
| Dates | `YYYY-MM-DD`. Blank stays missing, and one date is enough |
| Status | `PENDING`, `POSTED`, or blank (unknown) |
| Transaction ID | Declared reliable: stable across exports for one account |
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

## Rows that may be one event

Identical rows of the same status are separate events in both layouts. This is a
property of these invented layouts, and each real layout must prove it. Evidence
that rows may be one event is flagged under D-021.

## Unresolved row reasons

`missing_amount`, `missing_date`, `invalid_amount`, `invalid_date`, `invalid_status`,
`conflicting_amount`, `wrong_column_count`. Each row keeps its original cells and
creates no transaction.

## File failure codes

`unreadable_file`, `invalid_encoding`, `malformed_csv`, `header_mismatch`,
`invalid_coverage_metadata`, `coverage_basis_unavailable`, `coverage_conflict`,
`account_mismatch`, `layout_mismatch`, `database_busy`, `internal_error`.
