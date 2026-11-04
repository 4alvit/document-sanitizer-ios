# Diagnosing delayed native Share Sheet content

This diagnostic distinguishes completed export work, main-thread presentation,
and delayed population of the native activity sheet. It does not change the
ten-second Close requirement or the real Share extension and Files assertions.
A diagnostic success does not retroactively qualify a failed release test.

## Isolation and activation

Both opt-ins are required:

1. Build the application **and UI test runner** with the additional Swift
   compilation condition `CLEANSEND_SHARE_TRACE`. No project configuration,
   scheme or normal workflow enables this condition. Ordinary optimized builds
   compile out the recorder and every call site.
2. On an iOS Simulator only, give the selected UI test process the environment
   variable `CLEANSEND_SHARE_TRACE=1`. That test explicitly forwards it to its
   application launch. Other values and an absent variable leave tracing off.

For a release-mode reproduction, retain the existing exact-package Share job's
Release configuration and add the compilation condition to its build. Do not
substitute a Debug package for a Release latency comparison. Keep the existing
owned-simulator lifecycle, source/package binding, one selected test, process
budgets, and cleanup. Never publish the instrumented package as a release.

The first export in that process starts one trace. The file is
`Library/Caches/cleansend-share-phase-trace-v1.jsonl` inside that application's
data container. The writer creates it exclusively with mode `0600`, refuses an
existing file or symlink, and never overwrites a previous capture. Begin with a
fresh owned simulator; require the trace to be absent before the test.

## Data and bounds

Each line is an array of four unsigned integers:

`[schema_version, phase, system_uptime_microseconds, main_queue_lateness_microseconds]`

The schema is `1`. Lateness is zero except for phase 11. No filenames, paths,
document contents, titles, URLs, errors or arbitrary strings enter a record.

- 1: accepted export starts
- 2: detached export worker has finished writes/protection/cancellation check
- 3: MainActor has resumed after that worker
- 4/5: before/after publishing the completed export and clearing busy state
- 6/7: before/after `UIActivityViewController` initialization
- 8/9: before/after the first explicit access to its lazy `view`
- 10: SwiftUI reports the share presentation appeared
- 11: one-second main-queue liveness callback, with scheduling lateness
- 12: native activity completion callback
- 13: share presentation disappeared
- 14: duration or event limit reached

The recorder accepts at most 128 events and stops at completion, disappearance,
or the first observation at/after 60 seconds. A blocked main queue can delay that
observation; its actual delay remains visible. There is at most one pending main-queue liveness callback, with
at most 60 callbacks. It performs no screenshot, accessibility query or file I/O
on the main queue. File writes run on a separate serial queue and are capped at
16 KiB; disk failure simply stops recording. The UI never waits for the writer.
The file can remain incomplete after process termination; incomplete evidence
must be reported as such, not used to infer a missing phase.

The opted-in UI test also prints `REDACT_SHARE_TRACE_WAIT uptime_us=<integer>`
immediately before its unchanged ten-second wait. This gives the trace and test
observer a monotonic timing anchor. Do not move the wait to after export or
replace Close with the empty remote container.

## One causal reproduction

The isolated `share-phase-diagnostic.yml` workflow accepts only the **creation**
push of `diagnostics/sanitizer14-share-phase-timing`, on attempt 1. Its Python guard also
checks the exact repository, workflow, branch, event before/after SHA, and current
checkout. Updating that branch or rerunning a job cannot silently run another
experiment. Create it only after reviewing the exact source and confirming the
remote branch is absent. It is not a required release check and cannot qualify
a release.

The preparation stage has a 420-second deadline and a 2-GiB owned-data cap,
requires 16 GiB free plus its cap at admission, and runs one Release build.
Settings-only queries omit `-testPlan`, which Xcode accepts only for testing;
the actual build retains the test plan and selected test. Metadata commands
capture stderr separately (at most 64 KiB), without mixing it into JSON stdout
or replacing the original command failure.

Resolved ordinary/diagnostic build settings must agree on optimization (`-O`),
testability, coverage, architecture and SDK before compilation. Both compiled
products must contain their diagnostic marker. No package is downloaded or
published. A source inventory and payload hashes bind the local diagnostic ZIP
and UI runner to that exact build; the existing native runner then uses its
unchanged 900-second lifecycle, 300-second XCTest command and ten-second Close
verdict. Numeric trace collection uses the existing cleanup reservation; it
does not extend any deadline.

The final cleanup step deletes only owned build/runner/package/extracted paths
after command-group and owned-device absence proofs. If those proofs are missing,
it preserves the local paths and reports failure. The upload allowlist contains
only JSON/JSONL/log evidence and the original PNG/text accessibility attachments;
it never includes a ZIP, app, test runner, or raw build directory. Failure to
collect a trace cannot replace the original test failure with success.

1. Bind the instrumented build, runner and test selection to the same reviewed
   source; preserve normal optimization, SDK/runtime and AX5 settings.
2. Run the existing PDF Share case once on the owned iOS 18.5 simulator. Keep its
   original result, early/late accessibility attachments and file observer.
3. Before deleting that simulator, resolve the exact app container using the
   existing guarded lifecycle. Read only the fixed trace file above, reject a
   symlink/nonregular/oversized file, and retain its SHA-256 with the run/source
   identity. An absent trace means diagnostics were unavailable.
4. Correlate the numeric phases and main-queue lateness with the original Close
   verdict. A long 2→3 gap indicates delayed MainActor resumption; 6→7 or 8→9
   isolates controller initialization or lazy view loading. Early 9/10 with
   responsive phase-11 callbacks and a late native Close narrows the delay to
   subsequent activity-sheet population; it does not by itself identify an
   Apple service or prove an application fix.
5. Shut down/delete only the owned simulator and clean the instrumented build
   after preserving the small evidence. Choose a production change only from
   the measured cause; do not increase the timeout, prewarm the sheet or replace
   its actual activities merely to obtain a passing result.

## Portable validation

Run `python3 -m unittest scripts/test_share_phase_trace.py -v` on a Mac with the
existing Swift toolchain. The Foundation-only fixtures cover event ordering,
queue lateness, concurrency, duration/event/file caps, lifecycle termination,
invalid clocks, exclusive file creation and symlink refusal. A separate optimized
build confirms the trace is compiled out without the condition. These tests do
not claim native Share Sheet acceptance.

### Pre-test lifecycle diagnosis

The corrected metadata adapter built successfully on run `41805980308`, but the
native test never ran: `simctl bootstatus` exceeded its unchanged 120-second
command budget. Its output is not proof of process exit. The first cleanup probe
reported an unreaped leader and a present group; the three-second cleanup reserve
was exhausted before a signal could be attempted. The later supervisor found all
process groups absent, but simulator deletion was not verified. The Share Sheet
latency cause therefore remains unknown.

Only the diagnostic grant enables numeric `bootstatus_timing`: preparation, spawn
and wait boundaries, Python version numbers, first/last cleanup probe boundaries,
and at most two signal-decision timestamps. A failed optional timestamp is marked
without preventing the existing cleanup or replacing the original failure. No
extra native query, retry, timeout increase, or stdout-based success is introduced.
Ordinary runs perform no extra clock or process probes. The diagnostic supervisor
may retain the worker's existing bounded error type/stack alongside its own exit
error; this does not change its verdict or make the run release evidence.
