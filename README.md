# RedactLeaf

An original, local iPhone and iPad utility for making document copies with details hidden. Import PDF or a still image, draw black areas or find text, review every rendered page, and share a new PDF, PNG or JPEG.

**Development prerelease. Not available on the App Store yet.** RedactLeaf is a working consumer name; App Store name reservation is still pending. Internal Xcode targets and bundle identifiers retain the original CleanSend names. The app includes a StoreKit implementation and local test offer. Payment validation remains blocked by fresh-simulator routing and a local pre-approval Pro unlock, reproduced on the first pending purchase without a previous refund as well as after a refund. Its root cause is unresolved. A local offer is not a live product. See the [findings and release gates](docs/STOREKIT-TESTING.md).

## What it does

- Rasterizes visible PDF content, including annotation appearances, onto opaque pixels. Source text layers, interactive objects, attachments and source metadata are not transferred.
- Uses exactly the same rendered pixels for review and export. Manual areas are burned into the pixels. OCR only proposes areas; the user confirms them.
- Leaves original files unchanged. Workspaces are temporary, with no account, document server, analytics SDK or cloud sync.
- Imports through Files or a Share Extension. Each queued batch can be imported or discarded independently. Queued copies are excluded from backups and expired copies are removed when the main app next checks the queue after 24 hours.
- Supports a complete free workflow for up to three pages. A single non-consumable Pro purchase permits larger workspaces, up to 30 pages subject to the pixel budget, and creation of reusable mask presets. Existing content remains exportable if Pro becomes unavailable.
- Saves named mask geometry locally, separately from temporary documents. Preview a saved preset on a selected page before applying it, then check every page in the final review. Using and deleting existing presets remains available after Pro is revoked. See [presets](docs/PRESETS.md).

Image-only copies lose selectable text, links, interactive forms and accessibility structure. The source appearance of a signature is only an image in the export, not a valid digital signature. Resolution can decrease. Check all pages: OCR can miss private details, and the app does not certify that a document contains no personal information.

## Build and verify

Requirements: macOS, Xcode with iOS SDK, XcodeGen, Python 3, Poppler and the packages pinned in `requirements-qa.txt`. The deployment target is iOS 17. The core package also runs on macOS 13 or later.

```sh
brew install xcodegen poppler
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-qa.txt
bash scripts/check.sh
```

This runs native core tests, an independent synthetic export corpus, and builds the app, Share Extension and hosted tests for iOS Simulator. The corpus uses Poppler, Pillow and pypdf rather than the app's PDF renderer as its reference. It checks crop/rotation, visible black annotations, explicit masks, source metadata removal, opaque output, exact PDF embedded raster equality and unchanged originals.

The separate `scripts/verify_export.py FILE...` command validates the narrow
generated container profile and emits JSON. Its independent positive/negative
probe checks retained text, comments, actions, attachments, source metadata,
unused image resources, malformed files and valid white images. Unknown encoder
variants fail closed. It cannot determine whether a user covered all private
pixels; preview and geometry checks remain necessary.

With an iOS simulator runtime installed:

```sh
bash scripts/check-ios-tests.sh
CLEANSEND_TEST_FAMILY=iPad bash scripts/check-ios-tests.sh -only-testing:CleanSendUITests
bash scripts/check-ios-accessibility.sh iPhone
bash scripts/check-ios-accessibility.sh iPad
```

This creates and removes its own simulator, runs workspace/coordinate tests and StoreKit purchase, pending, cancellation, verification, refund and restore scenarios. It does not buy a real product. For manual use, run `xcodegen generate`, open `CleanSend.xcodeproj`, and run the `CleanSend` scheme. Use the clearly marked synthetic demo receipt without supplying personal files.

For deterministic application tests without StoreKit service calls, select
`CleanSendTests/ProStoreControlledTests` and
`CleanSendTests/ImportAuthorizationTests` with `-only-testing:` arguments.
These cover event ordering and imports suspended during entitlement changes;
passing them does not replace the blocked full payment suite.

GitHub CI runs the core/corpus checks, builds all targets and runs hosted
application tests with controlled purchase-service fixtures. It explicitly
excludes `ProStoreTests`, whose native StoreKit prerequisites and unresolved
payment findings are tracked in [StoreKit testing](docs/STOREKIT-TESTING.md).
A green CI run does not satisfy the payment or App Store release gates. Native
UI and StoreKit commands above remain separate, deliberate checks.

The dedicated accessibility commands require the largest system text size and
exercise the native Files picker, multipage review and image exports. Simulator
tests use local ad-hoc signing to preserve the Share Extension's App Group.
See [interface and extension QA](docs/UI-SHARE-QA.md) for evidence requirements
and the limits of the code-signing-disabled preview.

For ready-to-install local previews, commit the source and run
`python3 scripts/package-prerelease.py`. Use `RedactLeaf-adhoc-simulator.zip` to
demonstrate the Share Extension on iOS Simulator without rebuilding. The
separate code-signing-disabled ZIP is also retained. Both are Release builds; local ad-hoc
signing uses no Apple certificate and does not enable installation on an iPhone
or distribution through TestFlight or the App Store. See the package README
and [exact-package checks](docs/UI-SHARE-QA.md#packaged-release-preview).

## Boundaries

Inputs are limited to 50 MiB each; the Share Extension also limits a batch to 50 MiB and 20 files. A workspace is limited to 30 pages and 24 million working pixels. PDF pages render at up to 144 dpi, with a maximum edge of 2,400 pixels. Animated/multi-frame images and password-locked PDFs are rejected. Splitting a large document may be necessary even with Pro.

Exports receive neutral filenames. Fresh images can contain generated color-space and dimension tags; no source EXIF/GPS/author/comments are copied. Clearing the app cannot erase copies already sent to other applications, backups made by those applications, or the user's original files. No secure flash-erasure claim is made.

See [monetization and entitlement behavior](docs/MONETIZATION.md), [privacy](docs/PRIVACY.md), [threat model](docs/THREAT-MODEL.md), [release checklist](docs/RELEASE.md), [backlog](docs/BACKLOG.md), and [contribution guide](CONTRIBUTING.md). MIT licensed.

English and Russian [App Store draft materials](docs/app-store/README.md) and the
[support guide](docs/SUPPORT.md) are available for review. They do not announce
an App Store launch or a live Pro offer.
