#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/check-localization.py
swift test
swift build --product sanitizer-cli
python3 -m unittest discover -s scripts -p 'test_*.py'
mkdir -p .qa
python3 scripts/probe_export_verifier.py scripts/verify_export.py > .qa/verifier-probe.json
python3 scripts/check-corpus.py
# Build the committed project, as release packaging does. Regeneration belongs
# to source authoring and would change inputs before the native provenance gate.
xcodebuild -project CleanSend.xcodeproj -scheme CleanSend -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' -derivedDataPath .derivedData CODE_SIGNING_ALLOWED=NO build-for-testing

