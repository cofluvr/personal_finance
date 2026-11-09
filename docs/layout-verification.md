# Layout Verification

D-059 point F: the owner's check of each institution layout on one real file, before any real
import into the real ledger. Every layout is unverified until it passes. Imports are never
deleted, so the check runs in a throwaway real ledger, removed afterwards.

Walked through on `capital_one_card.csv`, the suite's invented fixture, in a synthetic ledger in
`build/`. IDs differ on each run. Run `pf` as `bin/pf` from this checkout, with
`/Volumes/CommonCents` mounted.

## 1. A throwaway ledger

```sh
mkdir -m 700 /Volumes/CommonCents/layout-check
pf init --db /Volumes/CommonCents/layout-check/check.db --real
pf account add --db /Volumes/CommonCents/layout-check/check.db --name "Capital One card" --type credit_card
```

```text
Created real ledger /Volumes/CommonCents/layout-check/check.db
Added account Capital One card: <ID>
```

Below, `C` is `/Volumes/CommonCents/layout-check/check.db`. Use one account per layout, of its
type: `credit_card` for `capital_one_card_v1` and `amex_card_v1`, `checking` or `savings` for
`capital_one_bank_v1` and `us_bank_v1`. For `capital_one_bank_v1`, add the account with
`--last4` and the four digits its export shows in `Account Number`, or the import fails as
`account_number_unknown` (D-061).

## 2. One statement period

Export the CSV for exactly one statement's period, and import it with that period as complete
coverage. `capital_one_bank_v1` offers only `--coverage-basis transaction`, the others only
`posting`, except `capital_one_card_v1`, which takes either. Use `posting` where it is offered.

```sh
pf import --db C --account "Capital One card" --layout capital_one_card_v1 \
  --declare-complete-coverage --coverage-start 2026-01-01 --coverage-end 2026-01-31 \
  --coverage-basis posting /Volumes/CommonCents/<statements folder>/<export>.csv
```

```text
<export>.csv: imported; coverage complete 2026-01-01 to 2026-01-31, posting basis (user_declared)
  Source rows read: 7 (7 valid, 0 unresolved)
```

**Stop if** the file fails (`header_mismatch` means the export's columns differ from the layout),
or any row is unresolved. Either means the layout is wrong for this export.

## 3. The statement's balances

Record the statement's opening balance on the day before its period, and its closing balance on
its last day. A card or loan states what it owes with `--owed`, any other account `--balance`.

```sh
pf balance record --db C --account "Capital One card" --date 2025-12-31 --owed 300.00
pf balance record --db C --account "Capital One card" --date 2026-01-31 --owed 163.89
pf balance check --db C --account "Capital One card"
```

```text
After 2025-12-31 through 2026-01-31: agrees
  Opening owed 300.00, account movement 136.11 over 7 transactions, expected owed 163.89, observed owed 163.89
  Covered: complete posting-basis coverage spans every day of it.
  Of unknown status, counted: 7 transactions, 136.11
```

**The layout passes** when the line says `agrees`. That checks the sign, the dates and that no
row was lost. `capital_one_bank_v1` reports the interval not covered, since its coverage is on the
transaction basis: that is expected, and `agrees` still passes it.

**It fails** on `differs by`. A difference of twice the period's movement means the sign is
reversed. A difference equal to a few transactions at the period's edges means the export's date
is not the one the layout assumes. Either way, report the line, not the statement.

## 4. Removing the throwaway ledger

Only after recording each layout's result:

```sh
chmod -R u+w /Volumes/CommonCents/layout-check
rm -r /Volumes/CommonCents/layout-check
```

Originals are kept read-only, so `chmod` first, or `rm` asks about each. This removes the throwaway ledger and its copies of the originals, never the statements. Repeat
steps 1 to 4 for each layout. A layout that passed may then import into the real ledger.
