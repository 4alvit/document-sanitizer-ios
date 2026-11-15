# Payment validation and open findings

Status as of 2026-10-31: **qualified native cohort passed; historical P1 remains open**.
At `d08d2ac`, [CI run 41249291386](https://github.com/4alvit/document-sanitizer-ios/actions/runs/41249291386)
passed all eight exact native cases with zero failures or skips on a fresh owned
iOS 26.2 Simulator (23C54), Xcode 26.3 (17C529). This includes pending approval,
purchase/new-store restore, refund, failed restore, empty restore, cancellation,
unverified transactions and cached entitlement during product-network failure.
Source and compiled host remained unchanged; the owned device was deleted and
all process groups were absent. The separate Release Share and AX5 jobs passed.

This supports a development simulator/source preview on the qualified profile.
It does not establish the cause or closure of the historical Xcode 27 P1 below,
prove every runtime correct, or satisfy live Sandbox, physical-device or App Store
acceptance. The original observations and remaining broad-public-beta gates
are retained; a local offer is not a live product.

## Early Pro unlock before approval: open P1

The latest immutable-configuration control used ordinary Xcode Run at
`61ded9fc120a413c4e1f4d97c98b194eca67127e`, Xcode 27.0 (27A266a), and a fresh
iOS 27.0 simulator (24A434). Ask to Buy was enabled and saved before Run;
the configuration, its modification time and all 76 tracked source hashes
remained unchanged during the control.

The **first pending purchase, without any previous refund**, returned
`.pending`, but native `Transaction.currentEntitlements` then delivered a
verified, non-revoked Xcode transaction ID 0. Pro became available and an
actual four-page import committed before the first Approve action. The
transaction manager still showed Pending Ask to Buy. After that one approval
and a refund, the app returned to Free. A second pending purchase delivered
a new verified Xcode transaction ID 1 and permitted a fifth page before any
second approval. The second transaction was left pending.

The simulator-only diagnostic recorded both the accepted transaction and
the authorization at the actual import commit. First-import event 36 and
second-import event 73 belong to the same contiguous 73-event trace
(`SHA-256 cfd8e2b328afd70c9ce4e5a21043924625de57903f395683f3c1fc6a26243a02`).
The immutable StoreKit configuration hash was
`a8205cdac6570525342c45ffdf413d297f3468c752152d2bed254ab2720dd5c4`.

This rules out a previous refund or a configuration edit during Run as
necessary conditions. It does not establish a universal SDK defect or
production App Store behavior. The pending branch itself did not grant
access: the app accepted a subsequent verified native entitlement. A global
pending veto would also risk rejecting valid approved, restored or
other-device purchases, and has not been introduced. The P1 remains open;
local controlled tests do not replace the real Sandbox acceptance gate.

### Earlier observations

An ordinary local Xcode Run on `cde4d82fc74351f1f19dc857d1f44d7e335a27b0`
showed Pro after a refund and a subsequent Ask to Buy purchase was still
pending. The application accepted an actual fifth page before the single
approval action. That run did not record the verified entitlement payload,
so the transaction responsible for access and the root cause are unknown.

The diagnostic-only commit `20e7a8eae7846ae36d5be1ce02b499eee9bb9126`
preserved the production access predicates. A short instrumented control and
one full-history replay both refused the pending fifth-page import and first
observed the new transaction during approval. These are nonreproductions,
not proof that the original finding was fixed or caused by StoreKit.

Controlled source tests can establish application behavior for chosen event
orders. They cannot by themselves establish which order caused a native
failure. The later immutable control above supersedes the earlier
nonreproductions as current evidence. Keep the P1 open until there is causal
evidence and corresponding validation; avoid repeated manual replays without
a new hypothesis.

## Fresh-simulator routing reproduction

The observed toolchain is Xcode 27.0 (27A266a), with iOS Simulator 27.0
(24A434), arm64. The diagnostic source was commit
`38bcfc23c2e5f681fa831396710f01577ff27f7a`. Subsequent changes remove the
unsupported test-plan StoreKit key and correct documentation; they do not claim
to fix payment routing.

Generate the project, then run the one purchase test:

```sh
xcodegen generate
bash scripts/check-ios-tests.sh \
  -only-testing:CleanSendTests/ProStoreTests/testPurchaseAndNewStoreRestoreFromVerifiedHistory
```

The script creates a new dedicated simulator, uses the explicit test plan,
runs serially, and removes only its own device. Do not enter an Apple Account
to make a local test pass. If account authentication appears, stop that test
and preserve its result bundle and logs.

The preflight uses `SKTestSession(contentsOf:)` with the configuration copied
into the test bundle. It checks the synthetic transaction's environment,
product type, product ID and app bundle ID, waits for verified current
entitlements, then clears the synthetic history. Each test subsequently
instantiates the real production `ProStore`.

## Observations

- Some cold runs returned an empty entitlement stream after a synthetic
  `.xcode` purchase.
- A later cold run passed the verified `.xcode` history preflight and loaded
  the configured product. The subsequent `Product.purchase()` requested
  Sandbox authentication. The simulator displayed an empty Apple Account
  login, and the run was stopped without entering credentials.
- One controlled Xcode IDE run used the same diagnostic source in a separate
  project on another new iPhone 17 Pro simulator. The purchase test was started
  directly from the Test navigator, without a preceding Run action. It showed
  the same account prompt and was stopped. Its result is canceled, not passed.
- Isolating hosted unit tests in a Debug-only empty app shell did not resolve
  this behavior. No production entitlement bypass was introduced.
- The Xcode 27 test-plan editor exposes no StoreKit configuration setting.
  The previous handwritten JSON key did not establish activation and has been
  removed. The scheme's Run action still references the local configuration
  for manual development.

The history preflight is diagnostic, not a guarantee that all StoreKit APIs
use the same environment. A test on a previously prepared simulator cannot
replace a reproducible cold run. The regular hosted application step uses controlled purchase-service fixtures
and excludes `ProStoreTests`. A separate guarded job builds signed Debug test
products from the same source, then selects all eight native cases on that host. These
results must be evaluated separately from the controlled fixtures and UI smoke.

## Related upstream report and next acceptance

Apple's [StoreKit setup documentation](https://developer.apple.com/documentation/xcode/setting-up-storekit-testing-in-xcode)
describes selecting the configuration in the scheme's Run options. A related
[Apple Developer Forums report](https://developer.apple.com/forums/thread/826971)
describes cold CLI configuration synchronization failures on earlier versions;
Apple staff acknowledged an issue and later reported a fix for Xcode 26.6.
This similarity does not prove that our Xcode 27 observation has the same cause.

The next accepted result must record the source, toolchain, configuration,
fresh device and complete payment path. Purchase, cancellation, pending
approval, unverified transactions, refund, restore and network-error cases
must execute against the intended local service. Apple account, signing, App Store Connect product and legal checks remain
separate from this Simulator evidence. Physical-device testing is outside this
preview's requested validation scope. Do not use private service overrides, invented entitlements or
an undisclosed warm-up to turn this gate green.

## Bounded hosted native payment gate

The dedicated job builds signed Debug test products from the committed Xcode
project, with the iOS26.2 Simulator SDK, in a step limited to nine minutes. It
uses one `test-without-building` invocation for all eight
existing `ProStoreTests`, on a fresh owned iPhone 16 Pro Simulator with iOS 26.2
and Xcode 26.3 (17C529). It reuses the same job's Debug application and unit-test bundle;
the native test driver does not rebuild, re-sign or enter an Apple Account.
Missing embedded test products, invalid signatures or changed source fail closed.
The empty Debug unit-test host lets each case initialize its local StoreKit
session before constructing the real production `ProStore`. The per-case setup
first resets and clears the StoreKitTest ledger and requires it to be empty.
It then performs the disclosed synthetic preflight purchase. The first
app-facing `Transaction.currentEntitlements` query must return that exact
transaction ID and product ID, verified in the `.xcode` environment. After
finishing and clearing the preflight purchase, setup still requires both an
empty StoreKitTest ledger and zero verified or unverified app-facing
entitlements before any real test case proceeds. A stale transaction cannot
satisfy the identity check. The adapter adds no separate warm-up.

The ordering alone was an explicit hypothesis, not an isolated native fix. In run
`41239753264` at `f7287727`, the fresh iOS 18.5 host booted, but the first
pre-purchase empty-history iterator never completed. The background and
MainActor diagnostic callbacks both ran while it was suspended. The revised
ordering removes that redundant pre-purchase query while preserving the strict
empty-history barrier before each real case. The optional scheduling trace now
labels its first query `firstPreflightIterator`. Offline regressions execute the
actual Swift setup methods against an in-memory service model; they prove
ordering, exact identity matching and failure handling, not Apple's service or
payment routing. Acceptance still requires all eight native cases on a fresh
host, with the existing 120/180-second per-case policy and the bounded
startup/case partition below. No retry, account sign-in or acceptance bypass
is introduced.

The purchase case verifies local native history after `Product.purchase()`,
then exercises a new store instance and restore. The pending case observes the
native verified entitlement stream and live Pro access for ten seconds before
its approval call. A failure stops that case before approval and retains a
bounded attachment without account identifiers or receipts. This finite
observation does not prove that a delayed event can never occur, or that a
different toolchain fixed the historical P1.

All eight exact case identities must pass with zero failures or skips. The
120/180-second per-case policy is unchanged. Native work uses one original
1,200-second worker clock: boot remains bounded by 376 seconds, the first
admitted case must be observed before 526 seconds, and its one 300-second case
window ends no later than 826 seconds. Later case markers never restart it.
The native child must be stopped by 830 seconds; final verification ends at
980, recovery at 1,002, shutdown at 1,039, deletion at 1,058, absence verification
at 1,080, and evidence before 1,192. No first case, a late first case, incomplete
case allowance, any missing host marker, failure, skip or missing case fails.

This is an explicit temporal-contract change: the old single 300-second ceiling
included cold XCTest runner/app startup. Startup now uses the already bounded
pre-case partition, so the native child may run longer than 300 seconds while
the original total, cleanup deadlines, full case allowance and all acceptance
checks remain fixed. Contexts declare `original-clock-startup-then-cases-v1`
and `case_window_seconds`; old `outer_seconds` contexts are refused.

The parent verifies actual remaining time in the dedicated 30-minute job before
admitting the complete 1,200-second native window plus its 180-second outer
reserve. The profile/build maxima do not guarantee admission: if actual setup
has consumed that time, native work is refused. There is no automatic retry,
new clock, account sign-in or acceptance bypass. The separate packaged Share
smoke retains its 900-second total and shared 300-second XCTest policy.

On failure, the driver retains the last observed host/case stdout markers.
After cleanup attempts it also reads existing staging session logs for a few
fixed launch milestones. This read checks a two-second cooperative budget within
the original evidence deadline; the existing parent process deadline remains
the hard bound. It permits 128 entries, four regular session files of at most 256 KiB
each, and 32 milestones per file; symlinks and changing files are rejected.
The receipt contains milestone types/times, hashes and sizes, not raw launch
arguments, paths or environment values. It runs no additional native command
and cannot change failed acceptance to success or establish a launch root cause.

The native job waits for the verification job and requires its successful Release
asset upload. It can run if a later ordinary test failed, but that failure remains
fatal to overall acceptance. Release asset upload and privacy success independently
admit the packaged share smoke after both producer jobs finish. Verification and
privacy run first; native payment and packaged smoke can then run in parallel.
This four-job graph permits at most two workers. Acceptance requires all four jobs,
including the independent exact Release-package smoke; Debug payment evidence does
not replace it. A local-service result cannot establish App Store purchase routing.

### Distinguish native iterator progress

The native setup trace records fixed `Transaction.currentEntitlements.yield`
markers with only `verified` or `unverified` classification. The existing
`Transaction.currentEntitlements` / `end` marker is emitted only after the
entire iteration completes. A yield without an end identifies a later suspended
iteration; absence of a yield alone does not establish why native iteration is
blocked. These markers contain no transaction, product, receipt or account values
and share the existing phase count and line-size caps. They do not add requests,
change verification or permit early acceptance.

The Xcode 16.4/iOS 18.5 runs from 2026-10-31 blocked before completing this
iteration with either empty-first or synthetic-purchase-first setup. The ordering
change alone did not resolve those runs. The later Xcode 26.3 cohort passed all
eight native cases; this does not establish which platform behavior caused the
older stall. Controlled tests or a passing Share/privacy job remain insufficient
substitutes for the dedicated native cases.

## Scoped Xcode 26.3 native cohort

The dedicated `native-storekit` job overrides the workflow's Xcode selection
with Xcode 26.3 (17C529), builds its own Debug app and unit-test bundle against
the iOS 26.2 SDK, and runs only on that exact available runtime. It does not
download or reuse an app from a different job/toolchain. The Release build,
Russian iPad privacy and exact-package Share jobs retain their Xcode 16.4
profile and existing package metadata contracts. Their results must not be
described as Xcode 26.3 acceptance.

This cohort began as a diagnostic response to the incomplete native entitlement
iteration observed on Xcode 16.4. RedactLeaf's own eight native cases now pass
on Xcode 26.3 in the run recorded above; this is profile-specific acceptance,
not proof of the older platform failure's cause. The fixed
per-yield markers distinguish a missing first result from a later incomplete
iteration. All eight native cases, exact transaction identity, verified results,
strict empty-history barriers and original process/resource/time limits remain
required. The existing narrow installation-mode allowance is retained unchanged;
new toolchain payload differences still fail for review rather than being
automatically accepted.

### Failed-restore precondition

The failed-restore scenario first waits for the purchased entitlement to appear
in the app-facing verified history using the same bounded native helper as the
catalog-network-failure scenario. A completed `SKTestSession.buyProduct` call alone
does not establish that precondition. The initial entitlement, failed-restore
retention, idle state, and network-error-message assertions remain mandatory.
The Xcode26.3 diagnostic executed all eight cases: seven passed, while this case
failed at its initial entitlement assertion before the simulated restore error.
The additional barrier addresses that setup race; native acceptance must still
pass all eight cases after the change.


### Parent allocation observation policy

The parent supervisor checks its original absolute deadline and the 12 GiB free
floor on every poll. Its complete owned-allocation inventory now has a minimum
five-second interval measured from the previous inventory's completion. The
independent worker retains its one-second interval and existing phase checks.
First and final parent observations, plus observed UUID, phase, command
start/finish/count, first-case and cleanup transitions, force fresh inventories.
Only those stable identity fields form the transition fingerprint; changing
scan counters and diagnostic timestamps do not trigger extra walks. A short
transition between parent polls may remain unseen by the parent; the worker's
independent checks remain in force.

This explicitly changes the parent's sampled observation policy. Between
unchanged-epoch inventories, allocation growth may be detected nominally up to
four seconds later than with the previous one-second minimum interval, plus
polling, scan and OS delays. Neither policy is a filesystem quota or a guaranteed
maximum detection latency. Every full inventory retains fresh independent
`lstat` calls, both directory observations, no-follow traversal, the 100,000
entry cap, and the 2 GiB allocated-byte cap. First failure evidence remains
latched; the final forced inventory cannot turn a failure into success. Parent
and worker scan counts and timings are recorded separately and run in parallel;
their durations must not be added as elapsed startup time. This policy does not
extend any total, work, native-case, cleanup or admission deadline, waive native
cases, or establish a successful native result. Actual source-bound native CI
must still pass.
