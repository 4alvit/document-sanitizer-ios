# Product backlog

## Qualified development simulator preview

CI run [41249291386](https://github.com/4alvit/document-sanitizer-ios/actions/runs/41249291386)
at `d08d2ac` passed the separate eight-case native StoreKit cohort on
Xcode 26.3/iOS 26.2, core/export checks, Russian iPad AX5 and exact Release-package
Share Extension. This is scoped simulator evidence, not closure of the
historical Xcode 27 P1 or the physical-device/Apple requirements below.

## Before a broader public beta

- Diagnose and close the observed early Pro unlock before Ask to Buy approval.
  The immutable-configuration control reproduced a four-page import during
  the first pending purchase without a previous refund, and a fifth page
  during a subsequent pending purchase after a refund. Keep this finding
  separate from controlled application defects and cold routing; see
  STOREKIT-TESTING.md for the recorded evidence and limits.
- Investigate the historical fresh-simulator routing failure on unqualified
  toolchains. The actual purchase/restore paths now pass on the qualified
  Xcode 26.3 cohort; that does not establish a universal routing fix.
  See STOREKIT-TESTING.md.
- Complete and inspect iPhone/iPad UI tests, including the largest text setting.
- Verify Files providers and the Share Extension on a physical device, including
  interrupted copies, screen locking, full storage and low-memory conditions.
- Publish the managed repository, run CI on its exact PR commit and obtain the
  required independent approval. Make the support and privacy URLs live.
- Configure signing, App Group and the real App Store Connect product; complete
  sandbox tests with local StoreKit configuration disabled, then TestFlight.

## Validate willingness to pay

- Recruit people who repeatedly share receipts, rental or insurance documents.
- Observe whether they complete an export without help and return with another
  document. Record usability notes without collecting the documents themselves.
- Test whether a complete three-page free workflow and a one-time larger-batch
  unlock solve a sufficiently frequent problem. USD 19.99 is a test hypothesis.
- Review conversion and refund feedback before expanding the paid feature set.

## Consider after feedback

- Applying a preset to multiple explicitly selected pages in one action.
- Localized interface and storefront text based on the first actual audiences.
- Better navigation for long packets and additional accessibility improvements.
- Additional audited encoder profiles and older supported iOS runtime coverage.

Cloud storage, team accounts, automatic certification of privacy, subscriptions
and permanent storage of originals are outside the first version's scope.
