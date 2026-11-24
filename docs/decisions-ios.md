# Decisions for the iOS companion

The index line is in [decisions.md](decisions.md). The product is [PRD-ios.md](PRD-ios.md), and
the boundary with the backend is [shared-contract.md](shared-contract.md).

## D-079 iOS companion plan — Approved on 2026-11-20, I1 to I3 built for review

Written on 2026-11-19, with the screen mock-ups in [ios-mockups/index.html](ios-mockups/index.html)
(open the file in a browser). Nothing of it is built. The owner's notes of 2026-11-19 asked for the
iOS app to be planned and started with mock-ups once the backend milestones were done. CLAUDE.md asks
for a plan approved before any of a new milestone is built, so this stops at the plan.

**What it depends on.** The phone renders a snapshot and computes nothing (PRD §10). Two backend
milestones come first, and both are planned already:

| Needs | From | State |
|---|---|---|
| The snapshot: its canonical JSON, schema version, validation and window | M19 (D-075) | Approved, not built. No security control changes, but a new kind of file leaves the ledger folder |
| Pairing and local-network sync | M20 (D-076) | Approved, not built. A security change, a dependency (`segno`) and a listener beyond loopback, each needing the owner's approval in a session that allows them |
| The dashboard's figures | M16 (D-072) | Built for review: `pf dashboard` is what the Today screen shows |

**Recommendations, each with its alternatives:**

1. **Milestones.**

   | Milestone | Scope | Needs |
   |---|---|---|
   | I1 | The app shell on synthetic snapshot files bundled for tests: every screen of the mock-ups, read-only, light and dark, Face ID lock, app-switcher blur, stale and month-boundary states | M19's snapshot schema, written down. Can start on a draft of it |
   | I2 | Snapshot storage: validation against the schema, atomic install, keep the last valid one, reject unsupported versions with an actionable error, local deletion | M19 built |
   | I3 | Pairing and sync: M20's protocol, the paired Mac's identity in the Keychain, revocation, sync history | M20 built and approved |
   | I4 | Provisioning and recovery instructions, tested: free development provisioning and its reprovisioning, checked against Apple's documentation at the time (PRD §2), and reinstallation data loss | I1 to I3 |

   Alternatively **I1 and I2 together, after M19:** fewer throwaway fixtures, but no screen to review
   until M19 is built.

2. **Technology.** SwiftUI for iOS 26 on the iPhone 17 Pro, Swift 6 strict concurrency, and no
   third-party package. The system frameworks cover everything: `LocalAuthentication` for Face ID,
   the Keychain for the pairing secret, `CryptoKit` for verifying a snapshot's integrity, and file
   protection (`completeUnlessOpen` or stronger) for the stored snapshot. Alternatively **UIKit:**
   no gain for a read-only app of lists and cards.

3. **Where it lives.** An `ios/` folder in this repository, with its Xcode project, so the
   snapshot schema and its fixtures are versioned with the backend that writes them.
   Alternatively **a separate repository:** cleaner tooling, but the schema and the app could drift.

4. **No calculation on the phone.** Every figure, label and provisional reason comes from the
   snapshot as the backend wrote it, so the app has no money arithmetic beyond formatting cents. A
   test fails if the app's sources do arithmetic on money values. The only date logic is comparing
   the snapshot's generation time with the phone's clock, for the stale warning (24 hours,
   configurable) and the month boundary, which never fabricates a new month (PRD §8).

5. **Screens,** as the mock-ups show: Lock, Today (household or a member), Why this number,
   Spending (categories and members), Transactions (search and detail), Goals, Accounts (net worth,
   balances with valuation dates, debt), Data status and sync, Settings and pairing. Five tabs.

**Open questions for the owner,** also at the end of the mock-ups: the app's name, the tab set,
what a member view shows while per-member safe to spend is out of M16, how many warnings Today
lists, and whether Today shows both sync time and bank-data freshness.

**For the owner's decision, with the lead engineer's recommendation first:**

- **A.** The four milestones I1 to I4, with I1 started on a draft of M19's schema (point 1).
- **B.** SwiftUI and the system frameworks only (point 2).
- **C.** An `ios/` folder beside the backend (point 3).
- **D.** The mock-ups as the screens to build, with the open questions answered.
- **E.** M19 before I2, and M20, with its security approval, before I3.

### I1 to I3 slice plan — Approved by the owner's notes of 2026-11-21

Written before any of the app was built, after M20. The owner's notes of 2026-11-21 give sign-off
on everything not specifically excepted, and ask that iOS work start once the backend's
milestones are done. This session takes that as approving A to E as recommended, these answers
to the open questions, and this plan.

**The open questions, answered as the mock-ups recommend:**

- The name stays **CommonCents** until the owner gives another.
- **Five tabs:** Today, Spending, Goals, Accounts, Sync, with Settings under Sync.
- **A member view shows budget pace only,** never a per-member safe to spend, until the backend
  computes one (D-072).
- **Today shows the most material warning,** and lists the rest under "Why this number".
- **Today shows both** bank-data freshness and sync time, labelled apart, since they differ
  (shared-contract §5).

**I1, I2 and I3 together,** since M19 and M20 are built. **Two parts, in `ios/`:**

1. **`ios/CommonCentsKit`, a Swift package** with everything but the screens:
   - the snapshot's model (`Codable`, every money field `Int` cents);
   - the validator: canonical bytes, envelope, digest, the schema subset of `schema_v1.json`
     read from the package's copy, reconciliations and excluded keys, as `snapshot/files.py`'s
     `verified`;
   - the store: atomic install, keeping the last valid, refusing another major with both versions
     named, local deletion;
   - freshness and the month boundary;
   - formatting cents;
   - the pairing payload and manual code;
   - the sync client of [sync-protocol.md](sync-protocol.md): pinning in a `URLSession`
     delegate, the Keychain, fetch, install, acknowledge.

   Its tests run with `swift test` on the Mac and on the iOS simulator. They read the backend's
   golden fixture `tests/fixtures/synthetic/snapshots/v1.0/household.json` and mutated copies, so
   the two sides are tested against the same bytes. A test fails if a source file under `Sources/`
   does arithmetic on a money value (point 4).
2. **`ios/CommonCents`, the SwiftUI app** for iOS 26: every screen of the mock-ups, light and dark;
   Face ID through `LocalAuthentication`, locking after a minute in the background; the
   app-switcher blur; and the stale and month-boundary states. A bundled synthetic snapshot is
   used only when nothing is installed and the app is run with `-demo` from Xcode. A release
   build never shows it.

**Verification here:** `swift test`; `xcodebuild build` and `test` for the simulator; and screenshots
from the simulator of each tab in light and dark, under `build/ios/`. The real phone, its Face ID
and a real pairing are the owner's (I4, YC2).

**Not in I1 to I3:** I4's provisioning guide, which needs the owner's Apple ID and phone; any
write from the phone; background sync; widgets.

### The owner's review of 2026-11-23: I1 to I3 approved, with charts

The owner approved the app and D-080, and asked for "graphs and graphics wherever possible". Made
as a review change, in `ios/CommonCents/CommonCents/Visuals.swift`, with Swift Charts (a system
framework, so B holds):

| Screen | Chart |
|---|---|
| Today | The two daily limits as bars, the lower in color; the budget's spent-of-target bar; original against revised daily allowance; each goal's assigned and still-needed bar |
| Member view | That member's spent-of-target bar, drawn only where the plan gives them a part |
| Why this number | The two limits; liquid against protected |
| Spending | Income and spending by month (tapping a month chooses it); the month's categories, largest first; the members' split of the month's spending |
| Transactions | Money in and out each day over the window |
| Goals | Each goal's assigned and still-needed bar |
| Accounts | Each account's counted balance either side of zero; each loan's due periods, colored by state |

**Point 4 still holds.** A chart is given only figures the snapshot holds, and every amount it
shows as text is one of them, through `Money.text`. A bar's length, a stack and an axis scale are
Swift Charts' drawing, not a figure the app states: no total, share or difference appears that
the Mac did not write. Axis ticks use `Money.dollars`, `Money.text` without its cents. Every chart
sits beside the rows that give its exact figures, and `noSourceDoesArithmeticOnMoney` covers the
new file.

**Color** follows the data-viz reference palette, light and dark steps: one hue for sizes, fixed
categorical slots by member index, blue and red either side of zero, and the reserved status
colors for loan states, each named in the legend. **VoiceOver** reads single-series bars mark by
mark; the grouped and dated charts (the monthly trend, the cash flow, the loan dues) speak as one
element whose value lists each figure, since Swift Charts would otherwise read them as raw cents.

**Tests:** `testChartsSpeakTheSnapshotsFigures` checks the charts reach VoiceOver with the
snapshot's own figures; `testATransactionIsReadOnly` now opens a transaction by its description,
since the first cell is the cash-flow chart. The Transactions link moved up, under the trend.
