# User Guide: From Setup to the Web and Phone Displays

As of 2026-11-27. A how-to for running the app end to end. It gathers steps whose detail lives in
the [README](../README.md), the [sync runbook](sync-runbook.md), the
[readiness checklist](real-data-readiness.md), [layouts](layouts.md) and the
[iOS README](../ios/README.md); where they disagree, those files win.

## Overview

The app is a command-line ledger, `pf`, that runs on your Mac. It shows your finances in two places:
web pages in a browser on that Mac (`pf ui`), and the CommonCents app on your iPhone, which gets a
snapshot over home Wi-Fi.

```text
 Your Mac ─────────────────────────────────────────────────────────┐
 │                                                                 │
 │  Bank exports ──pf import──▶ Ledger ──▶ pf ui ──▶ Mac browser   │
 │  (CSV, PDF)                 (SQLite)    (127.0.0.1 only)        │
 │                                │                                │
 │                                └──▶ pf sync serve ──────────────┼──same Wi-Fi──▶ CommonCents (iPhone)
 └─────────────────────────────────────────────────────────────────┘                read-only, offline
```

You import bank exports into one ledger file. `pf ui` serves it to a browser on the same Mac, where
review forms can also write back. `pf sync serve` hands the phone a read-only copy that works
offline. Nothing goes to the cloud, and no bank logins are stored.

The end-to-end path is: install (section 2), import and review (3), open the web pages (4), install
the phone app (5), then pair and sync (6). In the commands, `pf` means `bin/pf` from the repository
root, and `L` means your ledger path, such as `/Volumes/CommonCents/ledger/ledger.db`.

## 1. Prerequisites

You need a Mac with Python 3.12 or later, plus Xcode if you want the phone app. Network access is
needed only once, to install the two pinned dependencies.

| Need | Version | Used for |
| --- | --- | --- |
| macOS | Current release (built on 27.2) | Everything; the Mac is the source of truth |
| Python | 3.12 or later (built on 3.12.6) | The `pf` command and the web UI |
| pypdf, segno | 6.21.2, 1.6.6, pinned by hash | Reading PDF statements; drawing the pairing QR code |
| FileVault | On | Required if you use the private-folder ledger option |
| Xcode | 27 with an iOS 26 simulator | Building the CommonCents iPhone app |
| Apple ID | A free personal team works | Signing the app for your own iPhone |
| iPhone | Developer Mode on, same Wi-Fi as the Mac | Viewing the snapshot on the go |
| Bank exports | CSV or text-based PDF | Your data (see section 3 for supported formats) |

No paid API, subscription or cloud account is required. The app never stores bank passwords.

## 2. Setup: install, test, and create a ledger

Setup is four commands, then one `pf init` to make the ledger file. Run everything from the
repository root.

### 2.1 Install the environment

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --no-deps -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt   # only for running tests
.venv/bin/python -m pytest -m "not slow"                  # optional check, offline, synthetic data
```

`bin/pf` runs the app with this checkout's `.venv`, from any directory. To type `pf` instead of
`bin/pf`, add the `bin` folder to your `PATH`:

```sh
echo "export PATH=\"$PWD/bin:\$PATH\"" >> ~/.zshrc
source ~/.zshrc
pf --help
```

The full test suite takes about 23 to 40 minutes and needs about 6 GB free; the `not slow` subset
is enough to confirm an install.

### 2.2 Choose where the real ledger lives

The ledger is one SQLite file. Keep it outside the git checkout. A real ledger is made with
`--real` and one of two protections, which cannot be changed later.

| | Encrypted disk image (default) | Private folder |
| --- | --- | --- |
| Command | `pf init --real --db /Volumes/CommonCents/ledger/ledger.db` | `pf init --real --protection private-folder --db <folder>/ledger.db` |
| Where | A mounted, encrypted `.sparsebundle` | Any folder you own, iCloud Drive included |
| Setup | Create and mount the image first | Make the folder |
| Two Macs | No | Yes, via iCloud Drive, one Mac at a time |
| Pick it when | The ledger must be safe even on your unlocked Mac | FileVault is on and that is enough |

For the disk image, follow [real-data-readiness.md](real-data-readiness.md) step by step: create
and mount the image, `pf init`, add accounts, back up, test a restore. On an unmounted image every
command fails with `database not found`, which is the intended lock.

To try the app first without real data, make a throwaway ledger:
`DB="$(mktemp -d)/demo.db"; bin/pf init --db "$DB"`. The README's "Synthetic Example" imports the
bundled invented files into it.

### 2.3 One-time ledger settings

1. Set the household timezone. The dashboard, budgets and phone sync all need it.

   ```sh
   pf setting show --db L                 # copy the revision shown
   pf setting set --db L --revision <rev> household_timezone America/Chicago
   ```
2. Add each account. Credit cards and banks whose export carries an account number need `--last4`.

   ```sh
   pf account add --db L --name "Checking" --type checking
   pf account add --db L --name "Capital One Card" --type credit_card
   ```
3. Optional: name household members with `pf household member`, set the shared split with
   `pf household share`, and add categories with `pf category add`.

### 2.4 After pulling new code

An older ledger is refused until it is upgraded. Back up first, then:

```sh
pf backup create --db L --to /Volumes/CommonCentsBackup/backups/$(date +%F)
pf migrate --db L
pf reconcile --db L
```

Phone sync needs schema version 36. A ledger far behind should be migrated one milestone at a time,
with a verified backup before each step.

## 3. Getting data in: import, review, plan

Every figure on the web and the phone comes from statements you import on the Mac. Nothing connects
to a bank, so refresh means downloading new exports and importing them again.

### 3.1 Supported exports

The file's header must match exactly, or the file fails as `header_mismatch` and imports nothing.
Full rules: [layouts.md](layouts.md).

| Institution | Export | `--layout` | Notes |
| --- | --- | --- | --- |
| Capital One card | CSV | `capital_one_card_v1` | Posted rows only |
| Capital One bank | CSV | `capital_one_bank_v1` | Account needs `--last4` |
| U.S. Bank | CSV activity | `us_bank_v1` | Posting date basis |
| U.S. Bank card | PDF printout of Recent Activity | `us_bank_card_activity_pdf_v1` | Credit card account with `--last4` |
| American Express | CSV | `amex_card_v1` | Charges positive in the file, stored as money out |
| BFSFCU | CSV | `bfsfcu_v1` | Still unverified on a real export |

To preview what a PDF import would read, without touching the ledger: `pf pdf text FILE.pdf`.

### 3.2 Import

Keep statement files inside the protected location (for example
`/Volumes/CommonCents/statements`), never in the repository.

```sh
pf import --db L --account "Capital One Card" --layout capital_one_card_v1 \
  --declare-complete-coverage --coverage-start 2026-10-01 --coverage-end 2026-10-31 \
  --coverage-basis posting  /Volumes/CommonCents/statements/capone-oct.csv
```

- `--declare-complete-coverage` says the file holds every transaction in those dates. It lets
  duplicates across overlapping files merge confidently. Leave it off if unsure.
- Overlapping exports are fine: duplicates are detected, not double-counted.
- Exit code 1 means at least one file failed; the others are kept. Exit code 2 means the command
  stopped.
- A real ledger keeps a copy of each imported file in its `originals` folder. Check them with
  `pf archive verify --db L`.

### 3.3 Review what the importer was unsure about

```sh
pf review list --db L          # open items: possible duplicates, unreadable rows, conflicts
pf review show --db L ITEM_ID  # evidence, plus the revision to act on
pf totals --db L               # account movement and what is still unclassified
```

The common actions, each needing the `--account` and `--revision` printed by the show command
(details in the [README](../README.md)):

| Situation | Command |
| --- | --- |
| Two rows are the same purchase | `pf review confirm … --group T1 T2` |
| Two rows are different purchases | `pf review reject … --pair T1 T2` |
| A row could not be read | `pf review complete …` or `pf review dismiss …` |
| A value is wrong | `pf review correct … --field amount --value=-12.50` |
| Say what a transaction is | `pf review classify … --type purchase` |
| Link a card payment or transfer | `pf review transfers`, then `pf review transfer match …` |

Every action can be undone and keeps the original on record. Most of these are also available as
forms in the web UI (section 4). Classify transfers and card payments: otherwise they count as
spending.

### 3.4 Planning inputs that feed the displays

The dashboard and phone show more as you add these. Each follows the same pattern: `preview`
(writes nothing), then `add` or `set` with the preview's revision.

| Input | Command | Drives |
| --- | --- | --- |
| Income sources | `pf income proposals`, `pf income add` | Next payday, income report |
| Monthly budget | `pf budget preview`, `pf budget set` | Budget pace, revised allowances |
| Goals and funds | `pf fund preview`, `pf fund add`, `pf fund assign` | Goals tab, protected money |
| Recurring bills | `pf obligation …` | Obligations, safe to spend |
| Loans | `pf loan …` | Loan report, debt |
| Balances | `pf balance record` | Net worth, accounts tab |
| Spendable accounts | `pf account liquidity` | Safe to spend |

Check the result in the terminal with `pf dashboard --db L` or `pf safe-to-spend --db L --explain`.

## 4. The web displays: `pf ui` in a Mac browser

The "web" side is `pf ui`, a local server on `127.0.0.1` that only a browser on the same Mac can
open. It is not a hosted website and cannot be reached from the phone or another computer.

### 4.1 Launch it

1. Mount the ledger's disk image if you use one.
2. Start the server:

   ```sh
   pf ui --db /Volumes/CommonCents/ledger/ledger.db
   ```
3. The terminal prints a one-time address like `http://127.0.0.1:<port>/start?key=…`. Open it in a
   **private window**, so the browser keeps no history of the pages.
4. That address works once, in one browser. Opening it again, or from another browser, shows a
   "restart pf ui" message: press Ctrl-C and run step 2 again.
5. Stop with Ctrl-C when done. The port is chosen fresh on each launch.

Each page re-reads the ledger, so after an import in another terminal tab just reload the page.

### 4.2 What each page shows

The sidebar groups the pages:

| Group | Page | Shows |
| --- | --- | --- |
| Overview | Dashboard | Safe to spend, budget pace, funds, net worth, income, review counts, freshness |
| Overview | Totals | Account movement and transaction types; filter by account |
| Overview | Net worth | Net worth from recorded balances, by member |
| Overview | Visuals | The eight charts, the same figures as `pf report visuals` |
| Money | Monthly | Income and spending by month, with a date range |
| Money | Budget | A month's spending against its plan, revised allowances |
| Money | Income | Income by source against its schedule |
| Money | Household | Spending by member or shared |
| Money | Funds | Each goal's standing and this month's allocation |
| Money | Obligations | Recurring bills and spending by class |
| Activity | Transactions | Every transaction; click one for its detail and source |
| Activity | Review queue | Open items from imports; click one to act on it |
| Activity | Import results | Imported documents and their coverage |
| Planning | Scenarios | What-if plans and their comparison |
| Setup | Accounts and members | Accounts, liquidity, members |
| Setup | Settings and backups | Settings, buffer, backup history |

Many pages take a date in the toolbar (`as of`, `month`, `from`/`to`) to look at another day or
period.

### 4.3 What you can change from the browser

The pages have forms for review and tidy-up work. Each form runs the same command as the terminal
and refuses in the same cases.

- **Review queue:** confirm, reject, complete, dismiss, undo.
- **Transaction detail:** classify, categorize, tag, correct a value, separate a merge, mark
  one-sided transfers.
- **Accounts and settings:** liquidity accounts, the safety buffer.
- **Obligations and scenarios:** link an obligation to a loan or fund; add or undo scenario inputs.

Imports, budgets, funds, income sources, backups and phone sync stay in the terminal.

## 5. The phone: install CommonCents

CommonCents is a read-only iPhone app that shows a snapshot the Mac hands it. It does no math of its
own, and you install it from Xcode, not the App Store.

### 5.1 Optional: try it in the simulator first

```sh
open ios/CommonCents/CommonCents.xcodeproj
```

In Xcode, choose the CommonCents scheme and an iPhone 17 Pro simulator. To see invented demo
figures, edit the scheme (Product → Scheme → Edit Scheme → Run → Arguments) and add `-demo` and
`-unlocked`. These only work in debug builds and only while no real snapshot is installed. Two
simulators share the name iPhone 17 Pro; pick by OS version.

### 5.2 Put it on your iPhone

1. In Xcode, open `CommonCents.xcodeproj`, select the CommonCents target, then
   **Signing & Capabilities**.
2. Choose your personal team (your Apple ID) and change the bundle identifier to one of your own,
   such as `com.yourname.commoncents`.
3. Connect the iPhone by cable. On the phone, turn on
   **Settings → Privacy & Security → Developer Mode** and restart when asked.
4. Pick the iPhone as the run destination and press Run.
5. On the phone, trust the certificate under **Settings → General → VPN & Device Management**, then
   open the app.
6. Allow Face ID when asked; the app locks its figures behind it.

With a free Apple ID the app stops opening after 7 days. Run it from Xcode again; your snapshot and
pairing survive. **Deleting or reinstalling the app removes both**, so you would pair and sync
again.

This step (I4) has not yet been done on a real phone, so check Apple's current wording for these
settings as you go.

## 6. The phone displays: pair, sync, view

The phone gets data only when you run `pf sync serve` on the Mac while both are on the same home
Wi-Fi. Pairing happens once per phone; syncing whenever you want fresh figures.

### 6.1 Before the first sync

- The ledger is at schema version 36 (`pf migrate`) and the household timezone is set (section 2.3).
- Both devices are on the same network. Guest networks, some mesh systems, and VPNs block
  device-to-device traffic.
- Find the Mac's address: `ipconfig getifaddr en0`, or System Settings → Wi-Fi → Details. It must
  be private (`192.168.…`, `10.…`, or `172.16.…` to `172.31.…`). Below it is `192.168.1.20`.

### 6.2 Once: create the Mac's sync identity

```sh
pf sync identity create --db L
```

This writes a key and certificate into `sync/` beside the ledger. Backups leave it out on purpose:
after a restore, make a new identity and pair again.

### 6.3 Once per phone: pair

1. On the Mac:

   ```sh
   pf sync pair --db L --name "My iPhone" --address 192.168.1.20
   ```
2. If macOS asks whether Python may accept incoming connections, choose **Allow**.
3. In the app, open the **Sync** tab and tap **Scan the QR code** within 120 seconds. Or type the
   code, then tap **It matches** only if the phone shows the same 16 digits as the terminal.
4. The terminal prints `Paired device …` and exits.

Anyone who sees the code can pair until it is used, so don't screenshot or share it.

### 6.4 Each sync

1. Import new statements first (section 3). A sync never fetches bank data.
2. On the Mac:

   ```sh
   pf sync serve --db L --address 192.168.1.20
   ```
3. Open the app and pull down to sync. When it says the snapshot is installed, press Ctrl-C on the
   Mac. Otherwise `serve` stops by itself after 10 minutes (`--minutes`, up to 60).
4. If the Mac's address changed since pairing, use **Use a reconnect code** in the app and scan the
   code `serve` shows.
5. `pf sync deliveries --db L` lists what was served and whether the phone confirmed it.

The snapshot holds 90 days of transactions by default (`--window-days`, up to 366).

### 6.5 What the phone shows

The phone shows data as of the snapshot's date, not the moment you synced, and says so when it is
old.

| Tab | Shows |
| --- | --- |
| Today | Safe to spend today, with **Why?** showing the two limits (budget and cash until payday); this month's budget pace; goals; things to check |
| Spending | A month's spending by category and by member, with charts; tap through to read-only transactions |
| Goals | Each fund or savings goal and its progress |
| Accounts | Balances with the date each was observed; debt |
| Sync | Data status per account, sync history, the paired Mac, the household or member view, and **Delete local data** |

The app unlocks with Face ID and stays unlocked if you return within a minute. Switch between the
household and one member under **View**.

### 6.6 Lost phone

```sh
pf sync devices --db L                                     # find its ID and revoke revision
pf sync revoke DEVICE_ID --db L --revision <rev>
```

To cut off every device and replace the Mac's key, use `pf sync identity show`, then
`pf sync identity rotate --revision <rev>`, and pair again.

## 7. Routine and troubleshooting

### 7.1 The monthly routine

1. Download new exports from each bank into the protected statements folder.
2. Mount the disk image, then `pf import` each file (section 3.2).
3. Clear the review queue, in `pf ui` or with `pf review`.
4. Check the Dashboard in `pf ui`.
5. Run `pf sync serve` and pull to sync on the phone.
6. Back up to a new folder: `pf backup create --db L --to <backup volume>/backups/<date>`, then
   `pf backup verify --from …`.
7. Quit `pf ui` and eject the image.

### 7.2 When something goes wrong

| Symptom | Likely cause and fix |
| --- | --- |
| `Error: no Python environment at …/.venv` | Run the setup in 2.1 |
| `database not found` | The disk image is not mounted, or the `--db` path is wrong |
| `a real ledger must be on a mounted disk image` | The ledger path is on the startup disk; use the image or the private-folder option |
| A command refuses an older ledger | Back up, then `pf migrate` and `pf reconcile` (2.4) |
| A file fails with `header_mismatch` | Wrong `--layout`, or the bank changed its export format |
| `account_number_mismatch` / `_unknown` | The account's `--last4` is missing or differs from the file |
| Browser says to restart `pf ui` | The one-time address was already used; restart and open it once |
| `could not listen on …` | The address is not the Mac's current one, or the port is busy; check it, or pass `--port 8444` |
| `another sync pair or sync serve is running` | Stop the other one first |
| Phone times out | Firewall, guest Wi-Fi or client isolation, a VPN, or a wrong address |
| Phone says the certificate changed | Someone ran `identity rotate`, or something is impersonating the Mac; pair again only if you rotated |
| `the sync identity's files are missing` | After a restore: `pf sync identity show`, then `rotate`, then pair again |
| App will not open after a week | Free signing expired; run it from Xcode again |
| iCloud shows `ledger 2.db` | Two Macs changed the private-folder ledger at once; keep one as `ledger.db`, move the other out |

### 7.3 Good to know

- `pf snapshot create --db L --out PATH` writes the phone's snapshot as a file, but the current app
  has no screen to open a file, so Wi-Fi sync is the working route.
- Spending totals exclude transfers and card payments only once they are classified and matched.
- The app writes no logs. Output goes to the terminal; the ledger and its originals are the only
  files it writes.
- Known limits: [status.md](status.md).
