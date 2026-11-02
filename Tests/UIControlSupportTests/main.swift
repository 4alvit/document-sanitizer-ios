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

let scenario = CommandLine.arguments[1]
switch scenario {
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
