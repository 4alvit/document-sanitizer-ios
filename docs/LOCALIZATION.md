# Localization

RedactLeaf supports English and Russian in the app, Share Extension and SanitizerCore error resources. iOS selects the preferred supported language; English is the development fallback. The standard per-app language setting is supported. The app has no separate language override.

`LocalizedCatalog` resolves text in the caller’s bundle. Main app and extension use their own main bundles; SanitizerCore uses `Bundle.module`. Authored runtime strings use explicit lookups. User filenames, preset names, recognized document text, identifiers, persistence keys and StoreKit display prices remain literal.

UI language controls the integer plural category. Region controls number, percentage and currency formatting. The Russian one/few/many rules are deliberately independent of the regional locale. Adding another UI language requires its plural rules and resource tests, not merely a new lproj folder. The synthetic sample keeps its original USD amount while formatting it for the current region.

Vision automatically detects document language and prefers supported English/Russian recognition languages, independently of UI language. Availability depends on the OS and Vision request revision. OCR remains an aid requiring human review, not a privacy guarantee.

Run `python3 scripts/check-localization.py` and `swift test`. Hosted `AppLocalizationTests` exercise the actual bundled app/core/extension resources and rendered sample. `LocalizationUITests` cover supported-language ordering, fallback, Russian editor/error/preset/Pro text, and the real Share Extension round trip. Run UI tests on a dedicated simulator; verify the extension language separately because launch arguments for the containing app alone do not prove a different process’s language. Never change the host or shared global language for these tests.
