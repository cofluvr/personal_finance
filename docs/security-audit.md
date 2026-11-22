# Security audit of the backend

M21.3 (D-077 point 7, ZC1). Written on 2026-11-21 by the lead engineer, from the code as built at M20
and the tests named. It makes no claim of absolute security (PRD §19). Each finding is numbered,
and is either fixed here or left for the owner's decision. D-025's proposal is reviewed item by
item in the last section.

## 1. Inventory

**Listening sockets.** Two, each only while its command runs in the foreground:

| Server | Address | Protocol | Who may use it | Proven by |
|---|---|---|---|---|
| `pf ui` (`ui/server.py`) | `127.0.0.1`, a port the system picks | HTTP | The browser holding that launch's one-use key, then its cookie; writes need M17's pipeline | `test_the_server_binds_the_loopback_constant_and_nothing_else`, `test_local_ui*.py` |
| `pf sync pair`, `pf sync serve` (`sync/server.py`) | One RFC 1918 IPv4 address, `--port` (8443 by default) | HTTPS, TLS 1.3 only | During a 120-second window, one phone holding the pairing secret; then paired devices only, read-only | `test_the_sync_server_names_no_address_and_checks_the_one_it_is_given`, `test_sync_*.py` |

**Programs run.** Three, each a fixed path with fixed arguments and no shell:

| Program | Module | When | Proven by |
|---|---|---|---|
| `/usr/sbin/diskutil info -plist` | `db/volume_probes.py` | On a real ledger's open, to check the encrypted image | `test_the_one_allowance_is_used_by_one_call_to_a_fixed_program` |
| `/usr/bin/hdiutil info -plist` | `db/volume_probes.py` | The same | The same |
| `/usr/bin/openssl req -x509 …` | `sync/identity.py` | Once per identity, with an empty environment and a 30-second timeout | `test_the_identity_runs_one_fixed_program_with_fixed_arguments`, `test_it_runs_exactly_the_pinned_command` |

pypdf's JBIG2 decoder could run `jbig2dec`. The reader runs pypdf with that program unset
(`test_pypdfs_allowance_is_only_its_jbig2_decoder_running_a_program`).

**Files written outside the ledger's folder,** each only to a destination the owner names, and
each refused at an unsafe one:

| What | Gate | Mode |
|---|---|---|
| Backups | A new folder, on a different volume from a real ledger's (D-058 point 7) | Folder `0700`, files `0400` |
| Restored ledgers | A new path, gated as a real ledger's | `0600` |
| `pf export` CSV files | No symbolic link, not in a git work tree or synced folder, a private folder, and on a real ledger an encrypted image | `0600` |
| Snapshot files | The same gate as `pf export` | `0600` |

Inside the ledger's folder:

| What | Mode |
|---|---|
| The ledger | `0600` |
| `originals/` | Folder `0700`, files `0400` |
| `sync/` | Folder `0700`; key, certificate and lock file `0600` |

Every new file is opened with `O_EXCL`, and most also with `O_NOFOLLOW`. A real ledger's folders
are checked for owner and mode on every open.

**Dependencies.** Each is pinned by version and hash in `requirements.txt` and parsed by W1:

| Package | Version | sha256 |
|---|---|---|
| pypdf | 6.21.2 | `1d44d1a3a200f25062adff0085b02040e4646431ac2ccac22e42679e91466084` |
| segno | 1.6.6 | `28c7d081ed0cf935e0411293a465efd4d500704072cdb039778a2ab8736190c7` |

Development only, without hashes: pytest 9.2.0 and Hypothesis 6.170.14. The system's LibreSSL
3.3.6 is called as a program.

**Secrets:**

| Secret | Where | Stored as | Lifetime |
|---|---|---|---|
| UI launch key, session value, form-token key | Memory only | — | One `pf ui` run |
| Sync TLS private key | `sync/<identity>/key.pem` | `0600`, never printed, backed up or put in a snapshot | Until `sync identity rotate`, which deletes it |
| Pairing secret | Terminal only | SHA-256 | One use, 120 seconds, five failures |
| Device secret | The phone's Keychain | SHA-256 | Until revoked |

## 2. Controls against their tests

| Control | Decision | Test proving it | Its failing control |
|---|---|---|---|
| No network or program but those allowed | D-058 point 9, W1 | `test_no_module_reaches_the_network_or_runs_a_program` | `test_an_added_import_fails`, one per allowance |
| Real ledger on an encrypted image, private folders | D-058 points 2 and 3 | `test_real_ledger.py`, `test_encrypted_volume.py` | Recorded probe answers refusing |
| Backups intact and restorable | D-058 points 7 and 8 | `test_backups.py` (R1 to R5) | A changed byte refused |
| UI on loopback, one-use key, Host check | D-062 | `test_local_ui.py` | Wrong Host, no cookie |
| Browser writes: Origin, fetch metadata, form token, allowlist | D-073 | `test_local_ui_writes.py` and the M17 suites | Each check refusing alone |
| Every decision checked against a token under one write lock | D-043, G3 | Each kind's refusal tests; `run_stress.py`, no stale token succeeding | A stale token refused |
| Crash safety | D-035, D-043 | `run_crashes.py`: a kill at every statement leaves the before or the after state | — |
| TLS 1.3 only, pinned certificate | D-076 points 1 and 2 | `TestADowngrade`, `TestAManInTheMiddle` | The TLS 1.3 client served |
| Pairing single-use, time-limited, failure-limited | D-076 point 3 | `TestPairing` | Pairing inside the window |
| Per-request device check, revocation | D-076 point 6 | `TestAuthentication`, `TestAnotherDeviceOnTheNetwork` | The device with its secret served |
| Fixed bodies, no echo, no logging | D-037, D-076 point 10 | `TestMalformedRequests`, `TestNothingIsLogged`; `run_fuzz.py --target sync,ui` | — |

## 3. Data flows

| Flow | Leaves the ledger as | Gate |
|---|---|---|
| Backup | A copy of the ledger and originals, with a manifest | A new folder on another volume; a real ledger's must be on an encrypted image |
| Export | CSV of transactions or a report | `db/exports.py`'s destination check |
| Snapshot file | Canonical JSON, without excluded keys (D-075 point 3) | The same destination check |
| Sync | The same snapshot, over TLS 1.3, to a paired device, only while `serve` runs | Pairing, the pin, per-request device check |
| The local UI | HTML to the loopback browser | D-062 and D-073 |

Nothing leaves the machine except the snapshot to a paired phone on the local network. Nothing
is sent to any service.

## 4. PRD §19, line by line

| §19 requirement | Met by |
|---|---|
| Local-first, no cloud | W1; no service anywhere |
| Data encrypted at rest | The real ledger on an encrypted disk image (D-058 point 3, as amended); FileVault alone is refused |
| No banking passwords | None are asked for or stored; statements are files the owner imports |
| Least access | Two listeners, foreground only; the phone is read-only |
| Security controls verified | Section 2's tests, each with a failing control; this audit |
| No absolute-security claim | Section 6 |

## 5. Findings

1. **An interrupted import leaves an unfinished run row.** Found by `run_crashes.py`. A kill
   after `import_run`'s row is written, and before its `finished_at`, leaves that row with no
   `finished_at`. No document, record or transaction is partial, because each file commits on
   its own (D-023). Nothing reads `finished_at`. **Left as designed,** and stated in the crash
   checker as the one allowed in-between state.
2. **A device on the local network can end a serve session early.** Ten unauthenticated
   requests stop it, by D-076 point 5's failure limit. A connection that stalls also holds the
   one-request server for up to 10 seconds. Both deny service only: no data is exposed, and
   the owner runs `serve` again. **Accepted,** since `serve` is foreground and time-limited.
3. **The key is written `0644` by openssl, inside a `0700` folder, for milliseconds.** The
   folder's mode keeps others out, and the file is made `0600` before the folder is moved into
   place. **No change.**
4. **segno carries code that could open a browser or load plugins.** None of it is on a path
   pairing takes, and W1 pins each use to its function (D-076's M20 slice plans). **No change;**
   a new segno release is reviewed before adoption.
5. **pypdf has had many 2026 denial-of-service advisories from crafted PDFs.** Every one found
   was fixed in 6.20.0 or earlier, and the pin is 6.21.2. The owner's PDFs are their own bank's
   statements. **No change.** Check again before any upgrade.
6. **The development dependencies are pinned without hashes.** They never run with real data.
   **Left** for the owner to decide whether to add hashes.
7. **A restored ledger has no sync key,** by design (D-076 point 2). The runbook tells the
   owner to rotate it and pair again. **No change.**

**Advisory checks,** made on 2026-11-21 by one web search per package, naming only the package:

- **pypdf:** the GitLab and Debian trackers list 2026 CVEs fixed up to 6.20.0. None affects
  6.21.2. Of those found, CVE-2026-27628 names no fixed version, and is to be checked against
  pypdf's own advisories before relying on it.
- **segno:** no advisory found, and 1.6.6 is listed as its latest release.

## 6. What is not covered

- The Python interpreter, SQLite, LibreSSL and macOS themselves.
- The browser's own storage and extensions.
- The phone and its app (D-079).
- A compromised user account on the Mac.
- Physical access to an unlocked Mac.
- Whatever a tool run outside `pf` does.

## 7. D-025's proposal, item by item

D-025's proposal (`security-controls-proposal.md`) is about something else: the **development
agent's own environment** (Claude Code's sandbox and permissions), not the product. No product
control supersedes any of it. Applying it is the owner's alone (CLAUDE.md). The lead engineer's
recommendation for each item, for the owner to decide:

| Item | Recommendation |
|---|---|
| `blockReadsOutsideWorkingDirectories`, `blockWritesOutsideWorkingDirectories` | Apply, after confirming the version |
| Deny editing `.claude/**`, and reading `.env` | Apply |
| Ask before WebFetch and WebSearch | Apply. Sessions use the network rarely, and only with approval |
| Sandbox enabled, `failIfUnavailable`, no unsandboxed commands | Apply. Test first that pytest, the suite's real openssl run, and git commit still work |
| `denyRead: ~/` with `allowRead` for the repository and `~/.gitconfig` | Apply. It is what enforces the "never read the owner's data folder" rule mechanically |
| Deny `mcp__claude-vscode__getDiagnostics` | Apply, or drop as harmless |
| The verification canaries | Run them once after applying |

Until the owner applies it, D-025 stays **unapplied**, and provides no protection.
