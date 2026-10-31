# RedactLeaf Pro

RedactLeaf is free for small batches. Pro unlocks larger document batches and creation of reusable mask presets through one **non-consumable** purchase, product ID `io.github.4alvit.cleansend.pro`. The current local test price is USD 19.99. This is a pricing experiment, not a live App Store offer.

Preset creation checks current Pro access at the actual save operation. Listing,
previewing, applying and deleting saved presets remain available after a refund,
with an unavailable product price or while a purchase is pending. A preset stores
only a user-chosen name and normalized mask rectangles, not the source document.
Applying a saved preset to an existing page is not a new paid-capacity import.
See [the preset contract](PRESETS.md).

The app must never block viewing, editing, or basic export of an already loaded workspace because a transaction is missing, pending, refunded, or unavailable. Check the batch limit both when an import starts and immediately before newly decoded pages are added. If Pro is revoked during decoding, reject an addition exceeding free capacity without changing existing pages, masks, review or exports. Keep a rejected shared batch for retry within the ordinary queue lifetime. Workspace queue refresh protects its active shared batches from expiry until their worker finishes, including cancellation cleanup. The main app owns the 24-hour queue cleanup; the extension never prunes other batches. Clearing the queue removes only displayed, completed batches and preserves in-flight imports and extension staging. This is not a cross-process retention lease for a stalled extension lasting more than 24 hours. Show the localized `Product.displayPrice`, never a hardcoded purchase price. A nil price means no available offer; the UI can retry loading and always retain Restore Purchases.

## Entitlement behavior

`ProStore` is a main-actor observable object. Create one app-lifetime instance, call `load()` at initial appearance and when the scene becomes active, and call `purchase()`/`restore()` only after the corresponding person-initiated action. Purchase, restore and product lookup are serialized; foreground entitlement refresh still runs while one of those actions is busy. Automatic refresh preserves the latest action feedback unless a new error or transaction result replaces it. The transaction listener starts on initialization and is cancelled on deinitialization without retaining the store indefinitely.

- Grant access only to a **verified**, non-revoked non-consumable transaction with the exact product ID. An unverified transaction never grants access and is not finished.
- Read `Transaction.currentEntitlements` for current access. It includes finished non-consumable purchases; refunded/revoked products are excluded by StoreKit. Explicitly reject a nonnil revocation date as well.
- Observe `Transaction.updates` for approval on another device, interrupted transactions and refunds. Apply recognized verified events, reconcile current entitlements, then finish the transaction. Revocation removes that transaction's access; another valid purchase may still confer Pro. Loaded documents remain usable.
- A verified, matching, non-revoked purchase/update can grant access directly. Preserve that evidence through the refresh triggered by the same event; the next independent complete snapshot, including an empty snapshot, is authoritative. User cancellation is a neutral result. Pending approval itself grants no access and does not erase a separate valid purchase; the listener handles later approval.
- `AppStore.sync()` runs only after Restore Purchases because it may prompt for account authentication. Network failure during restore preserves the existing verified entitlement.
- There is no app-owned persisted Pro Boolean, test entitlement switch, server, receipt logging or dependency on a developer account ID in source. Offline access uses StoreKit's locally available verified transaction history. A failed product lookup does not erase valid entitlements. A fresh install without locally available verified history cannot invent proof of purchase and needs the App Store to restore it. Refund detection can be delayed while offline; refresh on foreground and listen for updates when the system receives them.

The Pro flag protects convenience features, not the confidentiality of documents. Modifying a device/application binary is outside this local licensing model.

### Ordering policy and limits

A generation check discards snapshots superseded by a newer refresh. Within the
process, contradictory verified evidence for the exact environment and
transaction ID is resolved by `signedDate`; revocation wins an equal-time
conflict. Older active evidence therefore cannot undo an already observed newer
refund. A newer active state or an independent purchase can restore access.
Numeric transaction IDs and `originalID` are not clocks or permanent deny lists.
Apple supports refund reversals, including for non-consumables.

This is an application conflict policy, **not** an Apple guarantee that JWS
signing dates form a monotonic transaction version or that the two sequences
converge in a documented order. Evidence is not persisted as a local license.
The original pre-approval Pro finding remains open; these controlled fixes do
not establish its cause. See [payment findings](STOREKIT-TESTING.md).

## Local testing

`ProStoreControlledTests` injects a demand-driven source at the StoreKit adapter
boundary and explicitly pauses snapshots, product lookup and purchase results.
`ImportAuthorizationTests` pauses after real PDF decoding and changes the
delivered entitlement before publication. These tests exercise application
ordering, cancellation and preservation; they do not verify Apple's service,
signatures or payment routing. Run them without invoking the payment service:

```sh
bash scripts/check-ios-tests.sh \
  -only-testing:CleanSendTests/ProStoreControlledTests \
  -only-testing:CleanSendTests/ImportAuthorizationTests
```

Production constructs `AppleStoreKitSource`, which maps Apple's verification
result without upgrading an unverified transaction. No launch argument,
stored preference or UI control enables the injected test source.

`App/CleanSend.storekit` contains a synthetic non-consumable offer. Select it in the Xcode Run scheme's StoreKit Configuration for manual testing. Automated tests load it through `SKTestSession`; the file must be copied into the test bundle. Run serially because the local StoreKit service is shared by tests. The test plan selects tests and timeouts; it has **not** been demonstrated to activate the local StoreKit environment on a fresh simulator. The installed Xcode 27 test-plan editor exposes no StoreKit configuration option.

Every StoreKit test first performs a synthetic local purchase and requires a verified current entitlement whose environment is `.xcode`, then clears that history. This diagnoses transaction-history routing, but does **not** prove that `Product.purchase()` or `AppStore.sync()` uses the same environment. A fresh-simulator CLI run on Xcode 27 / iOS 27 passed this preflight and then displayed an Apple Account sign-in during the actual purchase. That run was stopped without entering credentials. Do not sign in to fix local StoreKit tests, and do not report this suite as passing until the complete payment paths pass on a reproducibly configured clean simulator.

Hosted unit tests use a Debug-only empty application shell while XCTest is loaded. This prevents the ordinary app window from creating its own store and querying StoreKit before the test initializes `SKTestSession`. Each test then creates the real `ProStore` implementation. This changes neither transaction verification nor entitlements; the shell branch does not exist in Release builds. Normal app launches and UI-test application launches still construct the complete app window. This isolation alone did not resolve the observed fresh-simulator CLI routing failure.

`Tests/EntitlementTests/ProStoreTests.swift` exercises purchase, StoreKit-local history on a new store instance, explicit restore, refund listener updates, cancellation, Ask to Buy pending then approval, invalid-signature rejection, product-lookup network failure, and restore network failure. It uses StoreKitTest error injection, not a mock that can grant a production entitlement. It requires a hosted iOS XCTest target importing `CleanSend`, the StoreKitTest framework, and an installed simulator runtime.

Local StoreKit tests are not evidence of production payment processing. The network-failure tests simulate StoreKit API errors; they do not prove all physical-device offline behavior. Before release, also verify on a device with a sandbox account: purchase, force-quit/relaunch, airplane mode after confirmed purchase, restore on another device, refund, and cancel. Verify Free/Pro limits in the UI and confirm a refund never strands an open workspace.

## App Store setup and release gates

1. The account holder must have active Apple Developer Program membership and approve required paid-app agreements, tax and banking details. Do not accept legal terms or pay enrollment automatically.
2. Register and provision the app bundle ID `io.github.4alvit.cleansend`. Configure the signing team and App Store Connect app. Enable In-App Purchase as appropriate for the registered app. No signing certificate or account secret belongs in the public repository.
3. Create the exact non-consumable product `io.github.4alvit.cleansend.pro` in App Store Connect, set regional pricing/availability, supply localized name/description and review screenshot, and submit the purchase with the app as required by App Store Connect. Family Sharing is disabled in the local configuration; changing that is a separate product decision.
4. Test against App Store sandbox with the local StoreKit Configuration turned off. Confirm the live product resolves and the production UI shows its localized price. A local `.storekit` file does not create an App Store Connect product.
5. Provide working support/privacy URLs, accurate privacy answers and screenshots, a reviewer explanation of the small-batch free limit, and steps to verify purchase/restore. Inspect the release archive and do not claim App Store availability until review and actual release complete.

An operator Apple Account has been selected, but paid Developer Program membership is **not activated**. The signing team, certificates, App Store Connect agreements, the live product, sandbox transactions and App Review approval remain **not verified**. They are external release gates, not failures to be bypassed by a local Pro flag.

## Apple references

- [Current entitlements](https://developer.apple.com/documentation/storekit/transaction/currententitlements)
- [Transaction updates](https://developer.apple.com/documentation/storekit/transaction/updates)
- [Explicit App Store sync](https://developer.apple.com/documentation/storekit/appstore/sync())
- [Transaction signing date](https://developer.apple.com/documentation/storekit/transaction/signeddate)
- [Refund and refund reversal notifications](https://developer.apple.com/documentation/appstoreservernotifications/notificationtype)
- [StoreKit testing in Xcode](https://developer.apple.com/documentation/xcode/setting-up-storekit-testing-in-xcode)

API signatures were also checked against the installed Xcode 27 StoreKit and StoreKitTest SDK interfaces. The deployment target remains iOS 17.
