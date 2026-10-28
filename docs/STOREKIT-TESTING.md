# Payment validation and open findings

Status as of 2026-10-21: **not passed**. The actual purchase and restore paths
must pass before payment acceptance or a public beta. Export validation is
separate evidence and does not establish payment correctness.

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
and excludes `ProStoreTests`. A separate guarded step on that same host selects
all eight native cases from the products already compiled by that step. These
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

The dedicated step uses one `test-without-building` invocation for all eight
existing `ProStoreTests`, on a fresh owned iPhone 16 Pro Simulator with iOS 18.5
and Xcode 16.4. It reuses the same job's Debug application and unit-test bundle;
it does not build, re-sign or enter an Apple Account.
The existing empty Debug unit-test host lets each case initialize its local
StoreKit session before constructing the real production `ProStore`. The existing
per-case preflight performs a synthetic purchase, verifies `.xcode` history, then
clears it and waits for an empty entitlement stream. That disclosed barrier is
unchanged; the adapter adds no separate warm-up.

The purchase case verifies local native history after `Product.purchase()`,
then exercises a new store instance and restore. The pending case observes the
native verified entitlement stream and live Pro access for ten seconds before
its approval call. A failure stops that case before approval and retains a
bounded attachment without account identifiers or receipts. This finite
observation does not prove that a delayed event can never occur, or that a
different toolchain fixed the historical P1.

All eight exact case identities must pass with zero failures or skips. They
share one 300-second XCTest command ceiling; the existing per-case maximum
remains 180 seconds. Native work ends at 560 seconds, owned-device cleanup at
660, and the whole step at 780. The parent verifies actual remaining time in
the unchanged 30-minute job before admitting native work, preserving cleanup
and evidence-upload time. There is no automatic retry or cap increase.

Release asset upload and privacy success independently admit the packaged
share smoke after both producer jobs finish, even if this native payment gate
fails. The verification job and overall CI still fail; acceptance requires all
three jobs. A local-service result cannot establish App Store purchase routing.
