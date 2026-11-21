# Decisions for the iOS companion

The index line is in [decisions.md](decisions.md). The product is [PRD-ios.md](PRD-ios.md), and
the boundary with the backend is [shared-contract.md](shared-contract.md).

## D-079 iOS companion plan — Proposed, for the owner's approval

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
