# RedactLeaf App Store materials

English and Russian drafts for the first App Store version. The application
behavior described here is pinned to
[`e40d693`](https://github.com/4alvit/document-sanitizer-ios/tree/e40d6933bff2100c028259aa54be3ea8f3a6a66a).
These materials are for review; they have not been submitted to App Store Connect.

## Text and support

- [Listing, in-app purchase and review notes](../APP-STORE-METADATA.md): readable
  EN/RU copy with character and UTF-8 byte counts.
- [Structured copy](localizations.json): the same text, explicit field limits,
  source references and unset owner fields. This is an authoring format, not an
  App Store Connect API payload. The two review-note translations are alternatives
  for Apple's single review-note fields.
- [Privacy policy](../PRIVACY.md) and [support guide](../SUPPORT.md): bilingual
  prerelease pages describing actual local storage, export and support behavior.
- [Screenshot inventory](screenshots.json): original capture identity, dimensions,
  locale, application source and SHA-256 for every selected image.

Free includes editing, OCR search, review and export for up to three pages per
workspace. Pro is a planned one-time non-consumable purchase that permits up to
30 pages and creation of saved area presets. Both modes retain the 24-million
working-pixel limit. The description explains raster output, resolution limits,
loss of selectable text and accessibility structure, and the need to inspect
every page. No live price, unlimited capacity or automatic privacy guarantee is
claimed.

## Screenshots

The current set contains ten frames: three English iPhone images, three Russian
iPhone images, and two 13-inch iPad images per language. The Russian iPhone set
includes two normal-text-size overviews and the preserved supplementary image
showing manual controls at the largest text size. The normal-size welcome frame
shows the introduction and three steps; its import button extends below the
scroll viewport. The sample frame shows the synthetic receipt and nearby
controls, with lower OCR content outside the viewport.

The first capture attempt stopped before any app scenario because its separate
runner could not load XCTest. After correcting the generated loader environment,
one replacement session passed all three capture cases and produced six new
frames in 194 seconds including device cleanup. The same frozen `e40d693` app
was supplied without rebuilding or re-signing it. Both pre-test installed
payloads matched the release's 27 files; the frozen app and runner also remained
unchanged. Post-test installed-payload inventories were not recorded, so no
before-and-after verification of the installed copies is claimed. The inventory
preserves this evidence limitation and the history of the first attempt.

The selected images show actual app screens using synthetic content. They are
not mockups and have no replaced text, composited prices, cropping or resizing.
Use the inventory's locale and display-slot fields when preparing an upload.
An image with a valid size is still a draft asset, not evidence of App Review
acceptance or a tested payment flow.

Apple's [screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)
currently require at least one medium Dynamic Island iPhone image and, for this
iPad-compatible app, at least one 13-inch iPad image. The inventory records the
applicable portrait or landscape dimensions and verifies RGB images without an
alpha channel. Recheck the specification at submission time.

The review-only IAP screenshot is separate from the listing images. It remains
pending until the real product is configured and its payment flow is accepted.
No image of an unavailable offer or local test price is presented as a live
purchase. An optional promotional IAP image is not supplied.

## Public URLs

The repository and its [public issue tracker](https://github.com/4alvit/document-sanitizer-ios/issues)
exist. Issues can be read without signing in, but submitting one requires a
GitHub account. They are public and must not contain personal documents or
payment information.

The intended stable privacy and support paths are:

- `https://github.com/4alvit/document-sanitizer-ios/blob/main/docs/PRIVACY.md`
- `https://github.com/4alvit/document-sanitizer-ios/blob/main/docs/SUPPORT.md`

They depend on the required PR review and merge to `main`. A reachable,
commit-pinned draft is not proof that a stable `main` URL works. Verify both
stable URLs without authentication after merge. The owner must also provide
approved public contact information; a reachable GitHub issue tracker alone
does not establish that Apple's support-contact requirements are met.

## Remaining owner facts and release work

Freemium and the USD 19.99 one-time Pro target are already specified. Current
names, EN/RU locales, the Productivity category and manual release are proposed
defaults pending account checks. These routine choices do not require a repeated
product-preference decision. Actual seller/copyright identity, approved public
support contact, private App Review contact and account-holder prerequisites
are still required. Developer membership, signing, app/product registration,
agreements and account details remain separate work. The configured App Store
price and availability have not been verified; required actual values remain
unset where there is no evidence.

Before submission, review App Privacy answers against the actual device build
and services, finish the [payment and physical-device gates](../RELEASE.md), and
obtain the required PR approval. This documentation does not close those gates.
The existing `e40d693` simulator package retains its original source and checksum
provenance; this materials update does not relabel or rebuild it.

Field-limit sources: [app information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information/),
[platform and App Review fields](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information/),
and [IAP fields](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information/).
