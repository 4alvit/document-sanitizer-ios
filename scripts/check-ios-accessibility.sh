#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

family="${1:-iPhone}"
if [[ $# -gt 1 || ( "$family" != "iPhone" && "$family" != "iPad" ) ]]; then
  printf 'Usage: bash scripts/check-ios-accessibility.sh [iPhone|iPad]\n' >&2
  exit 2
fi

# check-ios-tests.sh owns one newly created UUID and deletes it on every exit,
# unless CLEANSEND_KEEP_TEST_DEVICE=1 requests explicit follow-up and cleanup.
# Set the system preference before the runner and app launch, covering UIKit
# sheets as well as SwiftUI. Seed a synthetic document in its native Files
# provider; two layout cases and one actual Files-import case must all pass.
CLEANSEND_TEST_FAMILY="$family" \
CLEANSEND_TEST_CONTENT_SIZE=accessibility-extra-extra-extra-large \
CLEANSEND_SEED_FILES_FIXTURE=1 \
CLEANSEND_EXPECT_TEST_COUNT=3 \
  bash scripts/check-ios-tests.sh \
    -only-testing:CleanSendUITests/AccessibilityFollowupTests \
    -only-testing:CleanSendUITests/FilesImportTests
