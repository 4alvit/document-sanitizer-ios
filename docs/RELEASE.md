# Release checklist

Current product version: 0.1.0 development prerelease. A simulator build is not an App Store release or an installable signed iPhone package.

The [App Store materials](app-store/README.md) include English and Russian listing
and in-app purchase drafts, field-length checks, screenshot provenance, and
prerelease privacy/support pages. They describe the reviewed `e40d693` application
source. Documentation or screenshot updates do not supersede that simulator
package or establish payment, physical-device, or App Store acceptance.

Payment acceptance remains blocked by two distinct findings in
[StoreKit testing](STOREKIT-TESTING.md): fresh-simulator purchase routing and an
observed early Pro unlock before Ask to Buy approval. The latter has no proven
root cause. An immutable-configuration control reproduced it on the first
pending purchase without a previous refund, and again after a refund.
Controlled application tests, export validation
and interface tests do not satisfy the full payment acceptance gate.

After regenerating the project with `xcodegen generate` and committing the tested
sources, run `python3 scripts/package-prerelease.py`. The packager builds the
committed project so a different checkout directory cannot change its inputs.
It builds two separate Release simulator variants: code signing disabled and
locally ad-hoc signed. A minimal linker-generated ad-hoc signature may still
exist in the code-signing-disabled variant. The signed variant includes simulator App Group entitlements and can
demonstrate the Share Extension without rebuilding. This local signature uses
no Apple certificate, developer team or provisioning profile, and is unrelated
to Apple Ad Hoc distribution to physical devices. The packager verifies both
identities and absence of test StoreKit configuration, archives only Git-tracked
source, checks ZIP integrity, and records the commit, Xcode version, signatures,
simulator entitlements and SHA-256 checksums in `.qa/releases/`. A separate
`payload-sha256.json` records every app payload file for exact-install checks.
It does not run the separate test gates or publish anything.

Release builds disable coverage instrumentation, including local Swift package
dependencies, and use Xcode's normal postprocessing and symbol stripping. Debug
test settings are unchanged. Before accepting either app bundle or ZIP, the
packager scans the main executable and Share Extension for local developer paths,
LLVM coverage/profile data and embedded debug metadata. Missing or malformed
inputs fail this gate. `release-binary-scan.json` records the results alongside
the package checksums; CI repeats this gate for both Release variants.

To check an existing preview independently, run
`python3 scripts/verify_release_package.py PATH_TO_APP_OR_ZIP --json REPORT.json`.
The older `e67a692` simulator previews contain build paths and coverage data and
must not be distributed; preserve them only as regression evidence. A newer
source commit alone does not certify a rebuilt archive: both binary scans and
the separately recorded exact-package smoke must pass.

## Engineering gates

- Run `scripts/check.sh` and `scripts/check-ios-tests.sh` on the exact proposed release commit. Preserve result bundles and synthetic corpus results.
- Independently review source changes affecting PDF drawing, mask coordinates, metadata, temporary storage or StoreKit. Visible black PDF annotations must remain visible; stripping their appearance before rasterization can expose covered content.
- Manually test portrait/landscape iPhone and iPad layouts, Dynamic Type, VoiceOver, Files import, Share Extension import/discard, every export format and review of a multipage packet.
- Run the dedicated system text-size and actual extension checks in [UI-SHARE-QA.md](UI-SHARE-QA.md). Default-size test runs do not replace the dedicated accessibility gate; inspect screenshots and preserve temporary-file cleanup evidence.
- Run the dedicated [preset interface checks](PRESETS.md#development-checks) on
  iPhone and iPad, with both cases passing and no skipped fixture preconditions.
  These checks seed geometry only; verify creation with actual Pro access in
  the separately recorded native payment integration.
- Test physical-device memory pressure, cancellation, low disk space, background/foreground and locked-device file protection. Synthetic simulator tests do not establish physical-device behavior.
- Verify the archive contains no personal documents, credentials, diagnostics with document text, local paths or analytics SDK. Local `.storekit` data is a test configuration only.

## Repository and distribution gates

- The public `4alvit/document-sanitizer-ios` repository was provisioned through the Terraform owner on 2026-10-24. Keep repository policy under that owner. Verify support/privacy links after the source is merged to `main`; the initial seed contains only the MIT license.
- Base a signed feature branch on the provisioned remote's main branch; open a PR and obtain the required fresh approval and passing CI. Do not overwrite the remote's seed commit.
- Attach the tested commit, source archive and SHA-256 checksum to a development release only after remote provisioning and review. Clearly identify simulator artifacts as such.

## Apple gates

An operator Apple Account has been selected. Paid Developer Program membership
is not activated; no signing team or certificates have been confirmed.
The account address is intentionally excluded from public project materials.

- Reserve the working App Store name `RedactLeaf: PDF & Photo`; availability is not confirmed until App Store Connect accepts it.
- Verify Developer Program membership, the signing team, app and Share Extension identifiers, App Group and provisioning profiles. The account holder must handle any enrollment payment or legal agreement.
- Verify paid-app agreements, tax and banking details in App Store Connect. Register the non-consumable product `io.github.4alvit.cleansend.pro`. The assigned one-time Pro target is USD 19.99. Configure and verify the actual App Store Connect price when account access is available; the local StoreKit price is not a live offer or a revenue forecast.
- With local StoreKit configuration disabled, complete sandbox purchase, cancellation, pending approval, refund, restore on another device and offline relaunch on a physical device. Show Apple's localized price.
- Publish working privacy and support pages. Check App Store privacy answers against the final binary. Supply final screenshots, accessibility review, metadata and reviewer instructions.
- Produce and validate a signed archive, distribute through TestFlight, collect feedback, fix release blockers, then submit for App Review. Record approval and actual availability before claiming release.

## Commercial validation

The first experiment is payment for faster preparation of larger document packets: complete three-page free workflow, one-time Pro unlock. Recruit people who regularly share receipts, insurance or rental documents; measure completed clean exports, repeated use and requests to process larger packets. Do not collect document contents for analytics. Establish real willingness to pay before expanding into subscriptions, team accounts or cloud storage.
