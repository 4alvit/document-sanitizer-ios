# Implementation contract — Draft 0.1

Product working name: RedactLeaf. Internal module, scheme and bundle names retain CleanSend. Repository: document-sanitizer-ios. Local-only iOS 17+ application. No accounts, server or durable vault. Untrusted inputs are images and PDF; outputs are new raster-only PDF, JPEG or PNG. Never mutate an input. No assertion that OCR finds all personal information. No user data in fixtures.

## Ownership

Core agent: Package.swift; Sources/SanitizerCore/**; Tests/SanitizerCoreTests/**. UI agent: project.yml; App/** except App/ProStore.swift and App/CleanSend.storekit; ShareExtension/**. Payments agent: App/ProStore.swift, App/CleanSend.storekit, docs/MONETIZATION.md. Root: integration, scripts, fixtures, CI, other docs, review and release.

## Shared core API (coordinate changes before changing these)

Swift package library `SanitizerCore` supports macOS 13+ and iOS 17+, Swift 5 language mode, no external dependencies. Public:

- `NormalizedRect: Codable, Hashable, Sendable` with Double x,y,width,height in TOP-LEFT normalized page coordinates, `init(x:y:width:height:)`. Invalid/nonfinite rectangles must be rejected during export, not silently omit redaction.
- `Redaction: Identifiable, Codable, Hashable, Sendable` with UUID id, NormalizedRect rect, initializer default id.
- `RasterPage: Identifiable` with UUID id, CGImage image, String sourceName, Int sourcePageNumber (1-based), [Redaction] redactions. init(image:sourceName:sourcePageNumber:). Pages represent visually upright crop-box pixels; UI never works with PDF coordinates.
- `RasterImporter.load(url: URL) throws -> [RasterPage]`, limit bounded file size/page count/pixel count, PDF rasterized using its crop box + rotation on an opaque white canvas. Image orientation honored and flattened. No source metadata propagated.
- `RasterSanitizer.render(_ page: RasterPage) throws -> CGImage` burns solid black masks into fresh opaque pixels, outward rounded/clamped after strict validation, no original retained in output container.
- `ExportFormat: String, CaseIterable { case pdf, png, jpeg }`
- `RasterExporter.export(pages: [RasterPage], format: ExportFormat, to directory: URL) throws -> [URL]`, fresh file per image or one PDF for batch; atomic staging and cleanup on failure; never overwrite arbitrary files; minimal constant creator/title only acceptable if documented, prefer zero metadata. Cancellation checked via Task.checkCancellation() between pages.
- `OCRMatch: Identifiable` id UUID; text String; rect NormalizedRect. `TextRecognizer.matches(in: CGImage, query: String) async throws -> [OCRMatch]`: Vision text boxes top-left normalized; query case-insensitive; ignore empty; match whole recognized line allowed but tell user whole line will be covered. OCR suggestions require confirmation in UI.

No Core UI actor requirements. Root will add CLI smoke/corpus harness if needed. All page pixel operations use identical preview/export path.

## UI

SwiftUI iOS `CleanSend` target, bundle id `io.github.4alvit.cleansend`; project generated with xcodegen. Local document selection PDF/images, PhotosPicker optional. Package workspace only: copy input to app temp, import, remove temp input. Large operations run off main thread; cancellation, cap imports, no blind reopen after cancel. Drag-to-mark rectangle in normalized top-left coords accounting for aspectFit letterbox. Page navigation; list/remove masks; query OCR suggestions across packet; select/confirm; preview burned page before explicit export. Export via share sheet, warning raster output loses selectable text and accessibility structure. Reset removes temp exports. No source names/content in logs. Synthetic sample offered for zero-state/demo (clearly labelled). Accessible controls and Dynamic Type.

ProStore API: `@MainActor final class ProStore: ObservableObject` published `isPro: Bool`, `displayPrice: String?`, `isBusy: Bool`, `message: String?`; `load() async`, `purchase() async`, `restore() async`; productID static. A new batch can be limited to 3 pages free; access/export of already loaded content never gated. Presets only gated on creation. UI must not hardcode actual price; unavailable purchase explains configuration, existing core remains usable.

StoreKit offline policy: use only verified matching transactions from StoreKit current entitlements, purchase results or updates; no app-owned persisted entitlement Boolean and no unverified optimistic grant. Direct event evidence survives its own reconciliation; the next independent complete snapshot is authoritative, including empty. Resolve contradictory process-local evidence only for the exact environment/transaction ID as documented in MONETIZATION.md; signing-time comparison is app policy, not a StoreKit ordering guarantee. Product lookup or restore network failures do not erase a previously verified in-memory entitlement. Refund detection may be delayed offline. A fresh installation without verified history requires App Store restoration. Never lock already loaded documents. Check live entitlement immediately before adding newly imported paid-capacity pages; a rejected addition preserves the old workspace and unconsumed shared source. StoreKit configuration product id io.github.4alvit.cleansend.pro, nonconsumable, local test $19.99. No purchase success without verified transaction; listen for updates, revoke the affected verified transaction, finish recognized verified transactions. Restore explicitly calls AppStore.sync.

New image containers may contain only generated technical color-space and pixel-dimension tags. Source EXIF, GPS, comments, authors, XMP and filenames must not propagate; generated output names are neutral. PDF may contain generated producer/creation metadata but no original metadata.

## Reusable mask presets

`MaskPreset` stores a stable ID, user-chosen name and normalized rectangles only.
`MaskPresetStore` keeps a bounded versioned library under Application Support,
outside the temporary workspace, with complete file protection and backup
exclusion. Creation checks current Pro access synchronously before persistence;
listing, application, deletion and explicit reset are not licensed operations.
Writes are atomic. A malformed or unsupported library blocks ordinary writes
without silently replacing its contents.

An application preview is separate from `ReviewPacket`. It renders a provisional
copy of one explicit target page through `RasterSanitizer`, preserves existing
masks and deduplicates exact geometry. Preview and commit are bound to the page,
workspace revision and operation token. Cancelled or stale work cannot publish.
A real addition creates fresh redaction IDs and invalidates final review; a
no-op does not. Every page still requires confirmation in final review before
export. See PRESETS.md for product scope and limits.
