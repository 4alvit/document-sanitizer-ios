# Synthetic Share Sheet timing

The existing [ShareTiming observer](../App/ShareTiming.swift) separates export
work, the worker-to-main handoff, Share Sheet construction and later lifecycle
callbacks. It helps investigate [issue #14](https://github.com/4alvit/document-sanitizer-ios/issues/14).
It does not fix or prove a cause for the historical iOS 18.5 delay, change the
ten-second native Close requirement, or replace screenshot/AX and installed-byte
acceptance evidence.

## Activation

Tracing is off unless all of these conditions hold:

- The app runs in an iOS Simulator; the physical-device `start` path returns nil.
- The workspace contains the explicitly selected synthetic example. Importing
  real pages clears that synthetic state.
- The app launch environment contains exactly `REDACT_SHARE_TIMING=1` and a fresh
  canonical lowercase UUID in `REDACT_SHARE_TRACE`.

The existing [Share UI test](../Tests/UITests/ShareExtensionEntryTests.swift)
sets both variables for its own launch and emits the selected UUID only after
that case starts and its workspace is ready. The normal exact-package smoke
collector binds to that single marker. Do not set the variables globally or
reuse a trace UUID for another launch. No extra compilation condition or
instrumented replacement binary is needed; an ordinary launch without the
opt-in records no trace.

## What the phases mean

Each export gets its own operation identity. Its published export packet keeps
that same observer through presentation and cleanup:

1. `exportStarted` to `filesReady`: the detached worker renders and protects the
   completed export files; this excludes later native activity population.
2. `mainActorResumed` to `packetPublished`: the result returns to the main actor
   and becomes the matching export packet.
3. `controllerStarted`, `controllerInitialized`, `controllerViewReady` and
   `controllerReturned`: the observed native activity-controller construction
   boundaries, including its first view access.
4. `sheetAppeared`: SwiftUI observed presentation. This does **not** establish
   that native activities or the Close button are ready.
5. `activityCompleted`, `sheetDisappeared`, `cleanupStarted` and `cleanupFinished`:
   the matching packet's later callbacks and owned export-directory cleanup.

Use differences between a trace's `uptime` values for in-app intervals. The
auxiliary wall-clock `time` is for approximate correlation, not a replacement
for monotonic ordering. Events capture their time before asynchronous file I/O;
file modification times are not export or presentation times. A long interval
locates an observed boundary, but does not by itself prove main-queue blockage,
Apple service behavior, or an application defect.

## Evidence and limits

The app writes only controlled phase names, trace/operation/optional packet UUIDs,
sequence numbers and timestamps. It records no document bytes, filenames, URLs,
labels or arbitrary error text. Each observer accepts at most 32 events and
16 KiB; the writer requests a private directory/file and refuses to overwrite an
existing trace. Write failure disables further output without changing export
readiness, privacy decisions or Share Sheet deadlines.

The raw path is `Library/Caches/ShareTiming/<trace UUID>.jsonl` in the owned app's
data container. The existing [exact-package collector](../scripts/release_smoke/run.py)
reads only the selected trace through its bounded no-follow
[reader/parser](../scripts/release_smoke/evidence.py), then writes
`share-timing.json` alongside the smoke metadata. Other trace files are not swept
or imported. Symlinks, changing files, unexpected/private fields, wrong trace UUIDs or invalid UUID formats,
non-finite clocks, backward uptime and invalid sequences cannot become valid timing rows.

Parser status `complete` means the available lines ended completely; it does
not mean every phase occurred or the Share test passed. `partial` retains only
the valid complete prefix. `missing`, `changing`, `unavailable` and `invalid`
remain diagnostic observations, never success substitutes. Keep the original
native test outcome, ten-second readiness check, installed payload and cleanup
records authoritative. A later successful smoke does not retroactively qualify
the failed historical iOS 18.5 run.

The current contract is covered by the [Swift observer tests](../Tests/WorkspaceTests/ShareTimingTests.swift)
and [inert reader/privacy regressions](../scripts/test_share_timing.py). The latter
can be run without an app, Simulator or network:

```sh
python3 -B -m unittest discover -s scripts -p 'test_share_timing.py'
```
