# CommonCents for iPhone

The read-only companion to the Mac ledger ([PRD-ios.md](../docs/PRD-ios.md), D-079 in
[decisions-ios.md](../docs/decisions-ios.md)). Every figure is the Mac's, carried in a snapshot.
The phone formats cents and compares dates, and computes nothing else.

| Folder | Holds |
|---|---|
| `CommonCentsKit/` | A Swift package with everything but the screens: the snapshot's model and validator, the store, freshness, the pairing codes, and the sync client |
| `CommonCents/` | The SwiftUI app: `CommonCents.xcodeproj`, its sources, and a synthetic demo snapshot |
| `interop/` | `run_interop.py`, which runs the package's Interop tests against the real Mac server on loopback |

## Build and test on the Mac

Needs Xcode 27 with an iOS 26 simulator. No third-party package is used.

```sh
cd ios/CommonCentsKit && swift test                       # the package, on the Mac
.venv/bin/python ios/interop/run_interop.py --work build/ios/interop   # against the real server
xcodebuild -project ios/CommonCents/CommonCents.xcodeproj -scheme CommonCents \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test  # builds, then 7 UI tests
```

The UI tests run the app on the demo snapshot. They check that:

- the lock shows no figure;
- an old snapshot is labelled not current and keeps its own month;
- every tab opens, and "Why?" shows the two limits;
- a transaction is read-only;
- Sync waits for pairing, and Settings offers deletion;
- returning within a minute stays unlocked.

The package's tests read the backend's golden snapshot,
`tests/fixtures/synthetic/snapshots/v1.0/household.json`, so the phone and the Mac are checked
against the same bytes. One test fails if any source but the validator's reconciliation checks
does arithmetic on a money value.

**Demo data.** A debug build launched with `-demo` shows the bundled synthetic snapshot, and only
while nothing is installed. `-unlocked` skips Face ID, and `-tab N` opens on tab N, for
screenshots. A release build ignores all three.

## Putting it on your iPhone (I4, yours)

Not done yet: it needs your Apple ID and your phone. In short:

1. In Xcode, open `CommonCents.xcodeproj`. Under Signing & Capabilities, choose your personal
   team, and change the bundle identifier to one of your own.
2. Connect the iPhone, enable Developer Mode on it, choose it as the destination, and Run.
3. On the phone, trust the developer certificate under Settings → General → VPN & Device
   Management.

With free provisioning, the app stops opening after 7 days, and you run it from Xcode again.
**Your data survives that,** as long as the app is not deleted. **Deleting or reinstalling the
app removes the snapshot and the pairing:** you sync again, and pair again with
`pf sync pair`. Check these steps against Apple's documentation when you do them (PRD §2).

Then pair and sync by [sync-runbook.md](../docs/sync-runbook.md). The one real-phone delivery it
asks for is acceptance criterion YC2.
