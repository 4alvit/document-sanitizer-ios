import Foundation

#if CLEANSEND_SHARE_TRACE
func check(_ value: Bool, _ message: String) {
    if !value { fatalError(message) }
}

final class Fixture: @unchecked Sendable {
    var now: Double = 100
    var events: [ShareTraceRecorder.Event] = []
}

let scenario = CommandLine.arguments[1]
let fixture = Fixture()
let recorder = ShareTraceRecorder(clock: { fixture.now }, sink: { fixture.events.append($0) })
switch scenario {
case "opt-in":
    check(!SharePhaseTrace.enabled([:]), "Disabled by default")
    for value in ["", "0", "true", "yes", "1 "] {
        check(!SharePhaseTrace.enabled(["CLEANSEND_SHARE_TRACE": value]), "Only exact opt-in")
    }
    check(SharePhaseTrace.enabled(["CLEANSEND_SHARE_TRACE": "1"]), "Explicit opt-in")
case "phase-order":
    recorder.record(.appeared)
    check(fixture.events.isEmpty, "No recording before export")
    check(recorder.begin(), "First export starts")
    check(!recorder.begin(), "Never replace an earlier capture")
    for phase in [ShareTracePhase.workerComplete, .mainResume, .publicationBegin, .publicationEnd,
                  .controllerBegin, .controllerInitialized, .viewLoadBegin, .viewLoaded, .appeared] {
        fixture.now += 0.25
        recorder.record(phase)
    }
    check(fixture.events.map { $0[1] } == Array(1...10).map(UInt64.init), "Exact phase sequence")
    check(fixture.events.allSatisfy { $0.count == 4 && $0[0] == 1 && $0[3] == 0 }, "Numeric schema")
case "main-delay":
    recorder.begin(); fixture.now += 12
    recorder.record(.mainPulse, lateness: 11)
    check(fixture.events.last == [1, 11, 112_000_000, 11_000_000], "Main queue delay retained")
case "time-bound":
    recorder.begin(); fixture.now += 60
    recorder.record(.mainPulse)
    check(fixture.events.last?[1] == 14 && !recorder.isActive, "Deadline terminates")
    recorder.record(.appeared)
    check(fixture.events.count == 2, "Nothing after deadline")
case "event-bound":
    recorder.begin()
    for _ in 0..<1000 { recorder.record(.mainPulse) }
    check(fixture.events.count == 128 && fixture.events.last?[1] == 14, "Hard event limit terminates")
case "concurrent":
    recorder.begin()
    DispatchQueue.concurrentPerform(iterations: 256) { _ in recorder.record(.mainPulse) }
    check(fixture.events.count == 128 && fixture.events.last?[1] == 14, "Concurrent emissions stay bounded")
    check(fixture.events.allSatisfy { $0[2] == 100_000_000 }, "Ordered numeric clock")
case "completion", "disappearance":
    recorder.begin()
    recorder.record(scenario == "completion" ? .completion : .disappeared)
    check(!recorder.isActive, "Stop on lifecycle termination")
    recorder.record(.mainPulse)
    check(fixture.events.count == 2, "No background trace after termination")
case "invalid-clock":
    fixture.now = .nan
    check(!recorder.begin() && fixture.events.isEmpty, "Invalid initial clock refused")
    fixture.now = 100; recorder.begin(); fixture.now = 99
    recorder.record(.mainResume)
    check(!recorder.isActive && fixture.events.count == 1, "Backward clock stops")
case "file", "existing", "symlink", "invalid-event", "file-cap":
    let root = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
    let target = root.appendingPathComponent("trace.jsonl")
    let sentinel = Data("unchanged".utf8)
    if scenario == "existing" { try sentinel.write(to: target) }
    if scenario == "symlink" {
        let original = root.appendingPathComponent("original")
        try sentinel.write(to: original)
        try FileManager.default.createSymbolicLink(at: target, withDestinationURL: original)
    }
    let sink = ShareTraceFileSink(url: target)
    if scenario == "file-cap" {
        for _ in 0..<2000 { sink.append([1, 11, 123456789012345, 0]) }
        sink.drain()
        let data = try Data(contentsOf: target)
        check(data.count <= ShareTraceFileSink.maximumBytes && data.last == 10, "Complete numeric lines under file cap")
    } else if scenario == "invalid-event" {
        sink.append([]); sink.append([1, 0, 1, 0]); sink.append([2, 1, 1, 0])
        sink.drain()
        check(!FileManager.default.fileExists(atPath: target.path), "Malformed events create no file")
    } else {
        sink.append([1, 1, 100, 0]); sink.append([1, 12, 101, 0]); sink.drain()
        let data = try Data(contentsOf: target)
        if scenario == "file" {
            check(data == Data("[1,1,100,0]\n[1,12,101,0]\n".utf8), "Exact numeric content")
            let mode = try FileManager.default.attributesOfItem(atPath: target.path)[.posixPermissions] as! NSNumber
            check(mode.intValue & 0o777 == 0o600, "Private file permissions")
            sink.append([1, 11, 102, 0]); sink.drain()
            check(try Data(contentsOf: target) == data, "No append after termination")
        } else {
            check(data == sentinel, "Existing data never overwritten")
        }
    }
default: fatalError("Unknown scenario")
}
print("PASS " + scenario)
#else
print("TRACE_COMPILED_OUT")
#endif
