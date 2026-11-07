import Foundation
import CoreGraphics

func check(_ value: Bool, _ message: String) {
    if !value { fatalError(message) }
}

var clock: TimeInterval = 0
var sampler = StableControlSampler(started: clock)
var frame = CGRect(x: 10, y: 20, width: 100, height: 40)
var present = true
var enabled = true
var hittable = true
var snapshotCost: TimeInterval = 0
var hitCost: TimeInterval = 0
var snapshots = 0
var hitQueries = 0

func poll() -> Bool {
    sampler.poll(now: { clock }, snapshot: {
        snapshots += 1
        clock += snapshotCost
        return present ? StableControlGeometry(frame: frame, enabled: enabled) : nil
    }, isHittable: {
        hitQueries += 1
        clock += hitCost
        return hittable
    })
}

var pauses = 0
var observations: [TimeInterval] = []
var snapshotCosts: [TimeInterval] = []
var hitCosts: [TimeInterval] = []
var moveEachSample = false
var recoverAfterFirst = false
var pauseMode = "full"

func wait() -> Bool {
    sampler.wait(now: { clock }, snapshot: {
        observations.append(clock)
        if !snapshotCosts.isEmpty {
            snapshotCost = snapshotCosts[min(snapshots, snapshotCosts.count - 1)]
        }
        snapshots += 1
        clock += snapshotCost
        if moveEachSample { frame.origin.x += 1 }
        if recoverAfterFirst { enabled = snapshots > 1 }
        return present ? StableControlGeometry(frame: frame, enabled: enabled) : nil
    }, isHittable: {
        if !hitCosts.isEmpty { hitCost = hitCosts[min(hitQueries, hitCosts.count - 1)] }
        hitQueries += 1
        clock += hitCost
        return hittable
    }, pause: { interval in
        check(interval > 0 && interval <= 1, "Pause stays within one second")
        pauses += 1
        switch pauseMode {
        case "early": clock += min(0.2, interval)
        case "late": clock += interval + 6
        case "frozen": break
        case "backwards": clock -= 1
        case "nonfinite": clock = .nan
        default: clock += interval
        }
    })
}

let scenario = CommandLine.arguments[1]
switch scenario {
case "native-cost-delayed-predicate":
    // Original xcresult: first callback waits 1.043s; between callbacks 0.700s.
    // These are measured AX activity costs, not assumed ready-state evidence.
    clock = 1.043; snapshotCost = 1.267; hitCost = 1.038
    check(!poll(), "First observed geometry does not establish stability")
    clock += 0.700; snapshotCost = 1.765; hitCost = 0.483
    check(!poll(), "Observed predicate scheduling crosses the unchanged deadline")
    check(clock > 6 && snapshots == 2 && hitQueries == 2, "Reproduce scheduling exhaustion")
case "driver-native-costs":
    snapshotCosts = [1.267, 1.765]; hitCosts = [1.038, 0.483]
    check(wait(), "The same AX costs fit with an immediate first observation")
    check(abs(clock - 5.553) < 0.001, "No larger deadline or faster fake native observations")
    check(observations.first == 0 && snapshots == 2 && hitQueries == 2 && pauses == 1,
          "Immediate observation; same two geometry/live-hit samples")
case "driver-fast", "driver-early-yield":
    if scenario == "driver-early-yield" { pauseMode = "early" }
    check(wait(), "Stable control is accepted")
    check(clock >= 1 && clock < 6 && snapshots == 2 && hitQueries == 2,
          "At least one second and no extra AX requests on early run-loop returns")
case "driver-moving", "driver-disabled", "driver-unhittable", "driver-missing", "driver-invalid-geometry", "driver-nonfinite-geometry":
    moveEachSample = scenario == "driver-moving"
    enabled = scenario != "driver-disabled"
    hittable = scenario != "driver-unhittable"
    present = scenario != "driver-missing"
    if scenario == "driver-invalid-geometry" { frame.size.width = 0 }
    if scenario == "driver-nonfinite-geometry" { frame.origin.x = .nan }
    check(!wait(), "Moving or invalid controls cannot pass")
    check(clock == 6 && snapshots == 6 && observations.allSatisfy { $0 < 6 },
          "One observation per second; no new AX request at exhausted budget")
case "driver-recovers":
    recoverAfterFirst = true
    check(wait(), "A valid control can recover after an invalid observation")
    check(clock == 2 && snapshots == 3 && hitQueries == 2,
          "Invalid observation does not count towards the one-second stable window")
case "driver-late-snapshot":
    snapshotCosts = [1.267, 3.0]; hitCosts = [1.038]
    check(!wait(), "Snapshot returned after deadline cannot pass")
    check(clock > 6 && snapshots == 2 && hitQueries == 1,
          "No live hit request after a late snapshot")
case "driver-late-hittability":
    snapshotCosts = [1.267, 1.765]; hitCosts = [1.038, 1.1]
    check(!wait(), "Live hit returned after deadline cannot pass")
    check(clock > 6 && snapshots == 2 && hitQueries == 2,
          "Late live hit is rejected without starting another observation")
case "driver-late-pause", "driver-frozen-clock", "driver-backwards-clock", "driver-nonfinite-clock":
    pauseMode = ["driver-late-pause": "late", "driver-frozen-clock": "frozen",
                 "driver-backwards-clock": "backwards", "driver-nonfinite-clock": "nonfinite"][scenario]!
    check(!wait(), "Invalid or late scheduling cannot pass")
    check(snapshots == 1 && hitQueries == 1 && pauses == 1,
          "No further AX request after invalid scheduling")
case "slow-snapshots":
    snapshotCost = 1.1; hitCost = 1.1
    check(!poll(), "One observation cannot establish stability")
    check(poll(), "Two stable slow observations fit the unchanged six seconds")
    check(snapshots == 2 && hitQueries == 2 && clock < 6, "Only two AX requests per sample")
    check(6 * 1.1 > 6, "The previous three-request implementation exceeds this same budget")
case "moved":
    check(!poll(), "Initial sample")
    clock = 1.1; frame.origin.x += 1
    check(!poll(), "Motion resets stability")
    clock = 1.8; check(!poll(), "New geometry needs a full second")
    clock = 2.2; check(poll(), "New geometry became stable")
case "disabled", "unhittable", "missing":
    check(!poll(), "Initial sample")
    clock = 1.1
    if scenario == "disabled" { enabled = false }
    if scenario == "unhittable" { hittable = false }
    if scenario == "missing" { present = false }
    check(!poll(), "Invalid observation resets stability")
    enabled = true; hittable = true; present = true
    clock = 1.2; check(!poll(), "Recovery starts a new window")
    clock = 2.1; check(!poll(), "Recovery has not lasted a full second")
    clock = 2.3; check(poll(), "Recovered control is stable")
case "late-snapshot":
    check(!poll(), "Initial sample")
    clock = 5.5; snapshotCost = 0.6
    check(!poll(), "A late snapshot cannot pass")
    check(hitQueries == 1, "Do not issue another AX request after expiry")
case "late-hittability":
    check(!poll(), "Initial sample")
    clock = 5.5; snapshotCost = 0.1; hitCost = 0.5
    check(!poll(), "A late live result cannot pass")
case "expired-start":
    clock = 6.1; check(!poll(), "Expired sample must not start")
    check(snapshots == 0 && hitQueries == 0, "No requests after expiry")
case "backwards-clock":
    clock = 2; check(!poll(), "Initial sample")
    clock = 1; check(!poll(), "Clock regression invalidates stability")
    clock = 3; check(!poll(), "Recovery starts a new window")
    clock = 4.1; check(poll(), "Recovered monotonic window")
default:
    fatalError("Unknown scenario")
}
print("PASS \(scenario)")
