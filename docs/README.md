# Documentation

Product and engineering records for RedactLeaf, an iOS app that masks parts of a
document before it is shared, kept at a prerelease stage.

## Product definition

- [Implementation contract — draft 0.1](IMPLEMENTATION-CONTRACT.md) — the working name, module names and repository layout.
- [Threat model and export contract](THREAT-MODEL.md) — what the export must preserve and which risks it accepts.
- [Product backlog](BACKLOG.md) — the open items.
- [RedactLeaf Pro](MONETIZATION.md) — what the paid tier unlocks and what stays free.

## Behaviour

- [Local mask presets](PRESETS.md) — how a saved page layout is stored and reused.
- [Localization](LOCALIZATION.md) — English and Russian across app, extension and error resources.
- [Synthetic Share Sheet timing](SHARE_TIMING.md) — how the export path is split and measured.
- [Interface and Share Extension checks](UI-SHARE-QA.md) — the synthetic checks and what they do not cover.

## Release and store

- [Release checklist](RELEASE.md) — the current prerelease version and what a simulator build is not.
- [Payment validation and open findings](STOREKIT-TESTING.md) — the native cohort result and the historical P1.
- [App Store materials](app-store/README.md) — English and Russian drafts for the first version.
- [App Store text drafts — EN/RU](APP-STORE-METADATA.md) — text prepared against a specific source revision, not submission-ready.

## Published text

- [RedactLeaf privacy policy — prerelease](PRIVACY.md) — the privacy text in both languages.
- [RedactLeaf support — prerelease](SUPPORT.md) — support text in both languages.
