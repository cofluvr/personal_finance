# Syncing the phone: the owner's runbook

How to pair the iPhone with this Mac and hand it the snapshot over your home network (D-076). The
protocol is [sync-protocol.md](sync-protocol.md). Until the iOS app's I3 milestone exists, the
phone's side is the reference client in `tests/`. The real-phone check (YC2) waits for that app.

## Before you start

- **The real ledger must be at schema version 36.** Migrate one milestone at a time after a
  verified backup, as the handoff says. Sync needs M19's snapshot (35) and M20's tables (36).
- **The household timezone must be set** (`pf setting set household_timezone …`). `serve` builds
  today's snapshot and never assumes a zone.
- **The Mac and the phone must be on the same network.** That network must let devices reach
  each other. Guest networks and some mesh systems isolate clients, and the phone will then time
  out.
- **Find the Mac's address:** System Settings → Wi-Fi → Details → IP address, or
  `ipconfig getifaddr en0`. It must be a private address (`10.…`, `172.16.…` to `172.31.…`, or
  `192.168.…`). `pf` refuses any other.

## Once: make the Mac's identity

```sh
pf sync identity create --db /Volumes/CommonCents/ledger/ledger.db
```

This makes a key and certificate in `sync/` beside the ledger, on the encrypted image, readable
only by you. **Backups leave the key out on purpose:** after restoring a backup you make a new
identity, and the phone pairs again.

## Pair the phone (once per phone)

```sh
pf sync pair --db /Volumes/CommonCents/ledger/ledger.db --name "My iPhone" --address 192.168.1.20
```

1. **macOS's firewall may ask** whether Python may accept incoming connections. Allow it. If it
   doesn't ask and the phone can't connect, check System Settings → Network → Firewall.
2. **Scan the QR code with the app within 120 seconds.** Or type the manual code. If you type it,
   check that the phone shows the same 16 digits as the terminal before you accept.
3. The terminal prints `Paired device …` and stops.

**Anyone who sees the code can pair until it is used.** Don't share a screenshot of it.

## Each sync

```sh
pf sync serve --db /Volumes/CommonCents/ledger/ledger.db --address 192.168.1.20
```

- Open the app and pull to sync. When it says the snapshot is installed, stop `serve` with
  Ctrl-C. Otherwise it stops after 10 minutes (`--minutes`, at most 60).
- If your Mac's address changed since pairing, scan the code `serve` shows. It holds no secret.
- `pf sync deliveries --db …` lists what was served and whether each phone acknowledged it.

The phone shows data **as of the snapshot's date**, not the time you synced. A sync never fetches
new bank data: import your statements first.

## If something goes wrong

| What happens | What to do |
|---|---|
| `could not listen on …` | The address isn't this Mac's now, or the port is in use. Check the address, or pass `--port 8444` |
| `another sync pair or sync serve is running` | Stop the other one first |
| The phone times out | The firewall, client isolation, a VPN, or a wrong address |
| The phone says the certificate changed | Someone ran `identity rotate`, or something on the network is impersonating the Mac. Pair again, only if you rotated |
| `the sync identity's files are missing` | After a restore: run `pf sync identity show`, then `pf sync identity rotate --revision …`, and pair again |

## A lost or stolen phone

```sh
pf sync devices --db …                                  # find its ID and revoke revision
pf sync revoke DEVICE_ID --db … --revision dv1-…
```

From its next request on, the phone is refused, with no restart needed. To revoke **every**
device and replace the Mac's key:

```sh
pf sync identity show --db …                            # the rotate revision
pf sync identity rotate --db … --revision dv1-…
```

## The fallback without a network

`pf snapshot create --out PATH` writes the same snapshot as a file, which you can carry to the
phone yourself (D-075). The phone checks it by the same rules.

## Checked on synthetic data

This runbook's commands were run on a synthetic ledger under `build/`. The pairing and the 20
deliveries ran over loopback, through the reference client and the benchmark's test-only
loopback server. The real-address firewall prompt and a real phone are for you to check.
