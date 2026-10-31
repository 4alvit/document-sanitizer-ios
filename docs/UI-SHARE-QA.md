# Interface and Share Extension checks

These checks use synthetic documents and private simulator UUIDs. They do not
purchase a product or establish physical-device, provider or payment acceptance.

## System text size and Files

After `xcodegen generate`, run each family separately:

```sh
bash scripts/check-ios-accessibility.sh iPhone
bash scripts/check-ios-accessibility.sh iPad
```

The runner sets and reads back the simulator's largest accessibility text size
before launching XCTest. Unlike the earlier SwiftUI-only debug flag, this also
applies to the native Files picker and activity controller. It creates a labelled
two-page PDF in that private simulator's local Files provider. The app imports
the PDF through the real picker; its workspace is not preloaded by a test hook.

The dedicated command requires all selected cases to pass with no skips. The
environment-dependent cases explicitly skip in an ordinary default-size test
run; that run alone does not satisfy this accessibility gate. Inspect screenshots
as well as results: a successful tap does not prove that a label is fully visible.

## Actual extension entry

```sh
CLEANSEND_TEST_CONTENT_SIZE=accessibility-extra-extra-extra-large \
CLEANSEND_EXPECT_TEST_COUNT=3 \
  bash scripts/check-ios-tests.sh -only-testing:CleanSendUITests/ShareExtensionEntryTests
```

This suite also requires the largest system text size and rejects skipped cases.
The tests export the app's synthetic sample, select RedactLeaf in the system
activity controller, and operate the installed extension. They cover PDF import,
PNG discard, and cancellation before copying. They do not insert a `.ready`
directory themselves. Sharing from the containing app also checks that a newly
queued batch appears when the activity ends without requiring an app restart or
a scene transition.

Simulator tests use a local ad-hoc signature so the app and extension retain
their App Group entitlement. No Apple certificate or enrollment is needed for
this simulator signature. A fully unsigned preview lacks the shared container;
its extension reports that limitation instead of silently pretending to save.

To verify temporary-file cleanup, preserve read-only listings of the private
simulator's App Group `SharedInbox` and app `tmp/CleanSend` before sharing,
while a batch is queued, and after import/discard. Include file hashes to match
the queued copy to the exported input. UI disappearance alone is not disk-cleanup
evidence. Record the actual device UUID, source revision and any local changes.

These URL-provider tests do not establish Photos or third-party Files-provider
compatibility. Interrupted provider copies, screen locking, low storage and
memory pressure remain physical-device checks.

## Packaged Release preview

`scripts/package-prerelease.py` produces `RedactLeaf-adhoc-simulator.zip` for a
ready-to-install Share Extension demonstration, alongside the original unsigned
variant. Both are Release builds with the same bundle identifier; install one
variant at a time. Extract the ad-hoc ZIP, then use your own simulator UUID:

```sh
xcrun simctl install DEVICE_UUID /path/to/CleanSend.app
xcrun simctl launch DEVICE_UUID io.github.4alvit.cleansend
```

Try the synthetic sample, review its page, export a PDF and choose RedactLeaf in
the system share sheet (possibly under More). Tap Save, then Done; return to the
workspace and Import or Discard the queued batch. The unsigned ZIP cannot
perform this shared-container workflow.

Xcode's local simulator signing uses `codesign` with identity `-`, with no Apple
certificate or team. Runtime simulator entitlements are embedded by the linker
in `__TEXT,__entitlements` and `__TEXT,__ents_der`; the code-signature entitlement
dictionary may be empty. Signing an existing unsigned app alone does not add
these sections. The packager builds the signed Release separately and checks
all included architectures of the app and extension, including their App Group
and agreement between the XML and DER simulator entitlements.

The source-based XCTest commands above rebuild the application. They are not
evidence about a shipped ZIP. For an exact-package check, install the extracted
payload, compare its complete file hashes with `payload-sha256.json`, and verify
the installed bundle before and after the smoke. An existing UI runner can use
a separate `.xctestrun` whose `UITargetAppPath` points at that extracted app,
with `test-without-building`; record the runner's separate origin and confirm
that XCTest did not replace the application. Preserve actual group-container
creation, queue-copy hashes, cleanup and screenshots as independent runtime
evidence. A passing signature check alone does not prove these behaviors.

## Same-run packaged Release smoke in CI

The `package-smoke` job waits until verification and privacy finish. It requires
a successful Release asset upload and a successful privacy job; a later core
or native-payment failure keeps verification red without hiding package-smoke
diagnostics. Overall acceptance still requires all three jobs to pass.
It binds exactly their current run/attempt/head artifacts, preserves checksums
and source provenance, and uses the Release UI runner already built by the
privacy job. It does not rebuild or re-sign the packaged app. The one selected
case exports the synthetic PDF through the actual Share Extension, saves it,
imports its queued copy, and records matching export/queue hashes and cleanup.

This hosted profile is an iPad Pro 13-inch M4 (16 GB), portrait, iOS 18.5,
Xcode 16.4, with the actual system AX5 size. Fresh inventory must confirm that
exact installed runtime/device/toolchain before creating the private simulator.
Installed app and runner payloads are compared before, during and after the case.
No native StoreKit test, purchase, App Store release or physical-device result is
implied by this development Simulator check.

The new job has a 25-minute ceiling and runs after the two existing jobs, so
peak macOS parallelism remains two. Its own bounds are 180 seconds for two
artifact transfers without retry, 120 additional seconds for validation and
selective extraction, and 780 seconds for the private native session including
cleanup. The case retains 240 seconds inside a 300-second XCTest command limit;
work ends at 560 seconds, device cleanup at 660, and the complete native session
at 780. Missing exact inputs, unsupported runtime, insufficient capacity or
unconfirmed process cleanup fail the job; there is no automatic alternate route.

## Busy-state layout evidence

The archived `BusyLayoutTests` diagnostic captured real view components at the
largest text size while the workspace operation was pending. Its source, PNGs
and metadata are preserved with the local QA evidence, outside the permanent
test target: constructing a real ContentView dependency starts a StoreKit
listener, which must not interfere with separate payment-test initialization.
The probe neither tapped Cancel nor simulated a long operation. Its custom host
and layer renderer do not reproduce every device safe area or material effect.
Treat those PNGs as bounded layout evidence, not as an end-to-end cancellation
or responsiveness test.

The privacy driver's AX5 setter and readback each retain a 60-second maximum.
Each command clips its actual allowance to the original work deadline, keeping
215 seconds for the unchanged XCTest admission check and four seconds for that
command's stop. Time used by the setter reduces the readback allowance; it does
not start a new budget. Exact system-size readback, the selected case limit,
the 300-second outer test cap, and the 560/660/780-second work/cleanup/whole
deadlines remain unchanged. Passing admission does not guarantee test completion.

The verification pipeline builds the committed Xcode project, matching Release
packaging. Project regeneration is an authoring action performed before commit,
not a CI build step. This keeps same-host unit-test products bound to the checked-in
project and preserves the native gate's strict clean-source and hash checks.


The exact-package smoke preserves its original 256-second startup boundary and
reserves the full 300-second test window plus four-second stop allowance. If its
initial system AX5 setter times out, the owned process group must be reaped and
absent before a readback. An exact AX5 readback still suffices. A responsive
`large` readback with the same owned device UUID and directory identity permits
one additional idempotent setter, capped at 15 seconds, and a 10-second exact
readback; admission requires 33 seconds including both command-stop reserves.
No original phase deadline is extended. Other errors or sizes do not trigger
convergence, and a second wrong result fails before launching the Share test.
This is bounded setup convergence, not a native-test or session retry. Evidence
retains both attempts, the first timeout and the final mandatory system value.
