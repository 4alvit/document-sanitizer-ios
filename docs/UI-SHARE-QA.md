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
