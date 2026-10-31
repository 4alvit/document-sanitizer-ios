#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Choose an installed iOS runtime and a compatible device type;
# create a private test device so other projects' StoreKit sessions are untouched.
selection=$(python3 - <<'PY'
import json, os, subprocess, sys
def items(kind):
    return json.loads(subprocess.check_output(["xcrun", "simctl", "list", kind, "--json"]))[kind]
def version(value):
    parts = [int(v) for v in value.split(".")]
    return tuple((parts + [0, 0, 0])[:3])
family = os.environ.get("CLEANSEND_TEST_FAMILY", "iPhone")
runtimes = sorted(items("runtimes"), key=lambda r: version(r["version"]), reverse=True)
device_types = sorted(items("devicetypes"), key=lambda d: version(d["minRuntimeVersionString"]), reverse=True)
for runtime in runtimes:
    if not runtime.get("isAvailable") or ".iOS-" not in runtime["identifier"]:
        continue
    for device in device_types:
        if device.get("productFamily") == family and version(device["minRuntimeVersionString"]) <= version(runtime["version"]) <= version(device["maxRuntimeVersionString"]):
            print(device["identifier"], runtime["identifier"])
            sys.exit(0)
sys.exit("No compatible installed simulator. Install an iOS runtime in Xcode first.")
PY
)
read -r device_type runtime <<< "$selection"
test_device=$(xcrun simctl create "CleanSend-QA-$$" "$device_type" "$runtime")
cleanup() {
  if [[ "${CLEANSEND_KEEP_TEST_DEVICE:-0}" == "1" ]]; then
    printf 'Retained private simulator for explicit follow-up and cleanup: %s\n' "$test_device"
    return
  fi
  xcrun simctl shutdown "$test_device" >/dev/null 2>&1 || true
  xcrun simctl delete "$test_device" >/dev/null 2>&1 || true
}
trap cleanup EXIT
xcrun simctl boot "$test_device"
xcrun simctl bootstatus "$test_device" -b
if [[ -n "${CLEANSEND_TEST_CONTENT_SIZE:-}" ]]; then
  xcrun simctl ui "$test_device" content_size "$CLEANSEND_TEST_CONTENT_SIZE"
  content_size_readback=$(xcrun simctl ui "$test_device" content_size)
  printf 'System content size for private simulator %s: %s\n' "$test_device" "$content_size_readback"
  if [[ "$content_size_readback" != "$CLEANSEND_TEST_CONTENT_SIZE" ]]; then
    printf 'Content size readback did not match the requested category.\n' >&2
    exit 1
  fi
fi
if [[ "${CLEANSEND_SEED_FILES_FIXTURE:-0}" == "1" ]]; then
  # A newly booted device has not necessarily created the Files provider's
  # group container yet. Initialize only this device's Files app first.
  xcrun simctl launch "$test_device" com.apple.DocumentsApp
  files_container=""
  for attempt in {1..10}; do
    files_container=$(xcrun simctl get_app_container "$test_device" com.apple.DocumentsApp groups 2>/dev/null | python3 -c '
import sys
for line in sys.stdin:
    fields = line.rstrip("\n").split("\t", 1)
    if len(fields) == 2 and fields[0] == "group.com.apple.FileProvider.LocalStorage":
        print(fields[1])
        sys.exit(0)
sys.exit(1)
') || files_container=""
    [[ -n "$files_container" && -d "$files_container" ]] && break
    sleep 1
  done
  if [[ -z "$files_container" || ! -d "$files_container" ]]; then
    printf 'The private simulator Files provider group is unavailable.\n' >&2
    exit 1
  fi
  files_storage="$files_container/File Provider Storage"
  mkdir -p "$files_storage"
  python3 scripts/make-accessibility-fixture.py "$files_storage/RedactLeaf-QA-Two-Pages.pdf"
  xcrun simctl terminate "$test_device" com.apple.DocumentsApp
fi
mkdir -p .qa
result=".qa/hosted-tests-$(date -u +%Y%m%dT%H%M%SZ).xcresult"
test_action=test
if [[ "${CLEANSEND_SEED_PRESET_FIXTURE:-0}" == "1" ]]; then
  # This opt-in UI gate uses an existing synthetic geometry library, never an
  # entitlement override. The default StoreKit test launch path is unchanged.
  xcodebuild -project CleanSend.xcodeproj -scheme CleanSend -testPlan CleanSend \
    -destination "platform=iOS Simulator,id=$test_device" \
    -parallel-testing-enabled NO -derivedDataPath .derivedData \
    CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- build-for-testing
  xcrun simctl install "$test_device" .derivedData/Build/Products/Debug-iphonesimulator/CleanSend.app
  preset_container=$(xcrun simctl get_app_container "$test_device" io.github.4alvit.cleansend data)
  python3 - "$preset_container" <<'PY'
import json, sys
from pathlib import Path
target = Path(sys.argv[1]) / "Library/Application Support/RedactLeaf/Presets/library.json"
target.parent.mkdir(parents=True, exist_ok=True)
fixture = {"version": 1, "presets": [{
    "id": "11111111-2222-3333-4444-555555555555", "name": "QA address areas",
    "rectangles": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}]
}]}
# The private simulator is new; never overwrite an unexpected existing library.
with target.open("x") as output:
    json.dump(fixture, output)
print("Seeded one synthetic geometry preset on the private test device.")
PY
  test_action=test-without-building
fi
# Local ad-hoc signing preserves simulator App Group entitlements. It does not
# use an Apple account, development certificate, or provisioning profile.
xcodebuild -project CleanSend.xcodeproj -scheme CleanSend -testPlan CleanSend \
  -destination "platform=iOS Simulator,id=$test_device" \
  -parallel-testing-enabled NO -derivedDataPath .derivedData \
  -collect-test-diagnostics never \
  -resultBundlePath "$result" CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- "$test_action" "$@"

# Dedicated environment-dependent suites can require an exact number of
# passing tests, so a skipped environment precondition never counts as success.
if [[ -n "${CLEANSEND_EXPECT_TEST_COUNT:-}" ]]; then
  xcrun xcresulttool get test-results summary --path "$result" --format json | python3 -c '
import json, os, sys
summary = json.load(sys.stdin)
expected = int(os.environ["CLEANSEND_EXPECT_TEST_COUNT"])
passed = summary.get("passedTests", 0)
skipped = summary.get("skippedTests", 0)
failed = summary.get("failedTests", 0)
total = summary.get("totalTestCount", 0)
if (passed, skipped, failed, total) != (expected, 0, 0, expected):
    sys.exit(f"Required {expected} passing tests with no skips; got passed={passed}, skipped={skipped}, failed={failed}, total={total}.")
print(f"Verified {passed}/{expected} passing tests with no skips.")
'
fi
