#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

family="${1:-iPhone}"
if [[ $# -gt 1 || ( "$family" != "iPhone" && "$family" != "iPad" ) ]]; then
  printf 'Usage: bash scripts/check-ios-presets.sh [iPhone|iPad]\n' >&2
  exit 2
fi

xcodegen generate
CLEANSEND_TEST_FAMILY="$family" \
CLEANSEND_TEST_CONTENT_SIZE=accessibility-extra-extra-extra-large \
CLEANSEND_SEED_PRESET_FIXTURE=1 \
CLEANSEND_EXPECT_TEST_COUNT=2 \
  bash scripts/check-ios-tests.sh \
    -only-testing:CleanSendUITests/PresetUITests \
    -maximum-test-execution-time-allowance 300
