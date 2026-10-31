# Product backlog

## Before a public beta

- Diagnose and close the observed early Pro unlock before Ask to Buy approval.
  The immutable-configuration control reproduced a four-page import during
  the first pending purchase without a previous refund, and a fifth page
  during a subsequent pending purchase after a refund. Keep this finding
  separate from controlled application defects and cold routing; see
  STOREKIT-TESTING.md for the recorded evidence and limits.
- Resolve the reproducible fresh-simulator StoreKit routing issue and complete
  the actual purchase/restore paths. Verified Xcode history alone did not prove
  that a subsequent purchase used the local environment. See STOREKIT-TESTING.md.
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
