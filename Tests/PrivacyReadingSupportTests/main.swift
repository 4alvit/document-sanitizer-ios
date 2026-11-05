import Foundation
import CoreGraphics

func check(_ condition: Bool, _ message: String) {
    if !condition { fatalError(message) }
}
func item(_ id: String, _ frame: CGRect, _ label: String = "Текст") -> PrivacyReadingElement {
    PrivacyReadingElement(identifier: id, label: label, frame: frame)
}
var bounds = CGRect(x: 0, y: 0, width: 400, height: 600)
var list = item("list", bounds)
var target = item("target", CGRect(x: 10, y: 150, width: 300, height: 50))
var elements = [list, target]
var bars: [PrivacyReadingElement] = []
var barHit = true
var targetHit = true
var snapshotCalls = 0
var barHitCalls = 0
var targetHitCalls = 0
func read(_ center: Bool = false) throws -> PrivacyReadingSample {
    try PrivacyReadingSample.read(listIdentifier: "list", targetIdentifier: "target", needsCenter: center,
        snapshot: {
            snapshotCalls += 1
            return PrivacyReadingTree(appFrame: bounds, elements: elements, navigationBars: bars)
        }, navigationBarIsHittable: { _ in barHitCalls += 1; return barHit },
        targetIsHittable: { targetHitCalls += 1; return targetHit })
}
func position() throws -> PrivacyReadingSample.Position {
    try PrivacyReadingSample.readPosition(listIdentifier: "list", targetIdentifier: "target", needsCenter: false,
        snapshot: {
            snapshotCalls += 1
            return PrivacyReadingTree(appFrame: bounds, elements: elements, navigationBars: bars)
        }, navigationBarIsHittable: { _ in barHitCalls += 1; return barHit })
}
func rejects(_ body: () throws -> Void) {
    do { try body(); fatalError("Expected rejection") } catch { }
}
let scenario = CommandLine.arguments[1]
switch scenario {
case "ready-once":
    let result = try read()
    check(result.ready && result.target?.label == "Текст", "Preserve ready text")
    check(result.target?.frame == target.frame && result.listFrame == list.frame, "Return exact sampled frames")
    check(snapshotCalls == 1 && targetHitCalls == 1, "One snapshot and one live target hit")
case "offscreen", "missing":
    target = item("target", CGRect(x: 10, y: 700, width: 300, height: 50))
    elements = scenario == "missing" ? [list] : [list, target]
    check(!(try read()).ready, "Absent/offscreen target is not ready")
    check(targetHitCalls == 0, "No needless offscreen live hit")
case "live-unhittable":
    targetHit = false
    check(!(try read()).ready && targetHitCalls == 1, "Snapshot geometry cannot substitute for live hit")
case "changed-after-scroll":
    target = item("target", CGRect(x: 10, y: 700, width: 300, height: 50))
    elements = [list, target]
    check(!(try read()).ready, "First observation needs scrolling")
    list = item("list", CGRect(x: 0, y: 50, width: 400, height: 500))
    target = item("target", CGRect(x: 10, y: 170, width: 300, height: 50), "Новый текст")
    elements = [list, target]
    bars = [item("navigation", CGRect(x: 0, y: 0, width: 400, height: 130))]
    let result = try read()
    check(result.ready && result.target?.label == "Новый текст", "Read fresh post-scroll target")
    check(result.viewport.minY == 142 && result.listFrame == list.frame, "Read fresh list and navigation geometry")
    check(snapshotCalls == 2 && barHitCalls == 1 && targetHitCalls == 1, "No cross-gesture reuse")
case "navigation-changed":
    bars = [item("navigation", CGRect(x: 0, y: 0, width: 400, height: 130))]
    check(try read().ready, "Initially below bar")
    bars = [item("navigation", CGRect(x: 0, y: 0, width: 400, height: 190))]
    check(!(try read()).ready, "New bar geometry clips target to less than24px")
    check(barHitCalls == 2 && targetHitCalls == 1, "Fresh bar hit per relevant state")
case "irrelevant-navigation":
    list = item("list", CGRect(x: 0, y: 100, width: 400, height: 500)); elements = [list, target]
    bars = [item("navigation", CGRect(x: 0, y: 0, width: 400, height: 90))]
    check(try read().ready, "Bar above viewport cannot clip it")
    check(barHitCalls == 0, "Omit only a provably ineffective bar query")
case "nonhittable-navigation":
    bars = [item("navigation", CGRect(x: 0, y: 0, width: 400, height: 190))]; barHit = false
    check(try read().ready, "Nonhittable bar must not clip reading viewport")
    check(barHitCalls == 1, "Hittability was checked")
case "center-required":
    target = item("target", CGRect(x: 10, y: 550, width: 300, height: 150)); elements = [list, target]
    check(try read().ready, "24px overlap permits paragraph reading")
    check(!(try read(true)).ready, "Links must have their center inside")
    check(targetHitCalls == 1, "Do not hit-test a link before center enters")
case "duplicate-target":
    elements.append(target); rejects { _ = try read() }
case "duplicate-list":
    elements.append(list); rejects { _ = try read() }
case "duplicate-navigation":
    bars = [item("nav", bounds), item("nav", bounds)]; rejects { _ = try read() }
case "missing-list":
    elements = [target]; rejects { _ = try read() }
case "empty-viewport":
    bars = [item("nav", bounds)]; rejects { _ = try read() }
case "all-twenty-targets":
    for index in 0..<20 {
        target = item("target", CGRect(x: 10, y: 150, width: 300, height: 50), "Текст \(index)")
        elements = [list, target]
        let result = try read(index >= 17)
        check(result.ready && result.target?.label == "Текст \(index)", "Each paragraph/footer/link keeps its own content")
    }
    check(snapshotCalls == 20 && targetHitCalls == 20, "No target shares another target's readiness")
case "long-static-settle":
    // Exact geometry retained from the failed AX5 iPad observation.
    bounds = CGRect(x: 0, y: 0, width: 1376, height: 1032)
    list = item("list", CGRect(x: 398, y: 196, width: 580, height: 640))
    target = item("target", CGRect(x: 414, y: 773.5, width: 548, height: 1573.5))
    bars = [item("navigation", CGRect(x: 398, y: 196, width: 580, height: 56))]
    elements = [list, target]
    check(try read().ready, "Keep the initial real hit-test for the partially visible paragraph")
    targetHit = false
    var stability = PrivacyReadingStability()
    check(!(stability.observe(try position(), at: 0)), "First observation is not yet stable")
    check(!(stability.observe(try position(), at: 0.49)), "Keep the full half-second interval")
    check(stability.observe(try position(), at: 0.5), "A stable readable long paragraph may be captured")
    check(targetHitCalls == 1 && snapshotCalls == 4, "Fresh geometry without a second activation-point query")
case "stability-frame", "stability-label", "stability-list", "stability-navigation":
    var stability = PrivacyReadingStability()
    check(!stability.observe(try position(), at: 0), "Start observation")
    switch scenario {
    case "stability-frame": target = item("target", target.frame.offsetBy(dx: 0, dy: 1))
    case "stability-label": target = item("target", target.frame, "Изменённый текст")
    case "stability-list": list = item("list", CGRect(x: 0, y: 1, width: 400, height: 599))
    default: bars = [item("nav", CGRect(x: 0, y: 0, width: 400, height: 40))]
    }
    elements = [list, target]
    check(!stability.observe(try position(), at: 0.6), "Changed content or geometry resets settling")
    check(!stability.observe(try position(), at: 1.09), "No old interval reuse")
    check(stability.observe(try position(), at: 1.1), "Only the new stable interval qualifies")
case "stability-offscreen", "stability-missing", "stability-empty-label":
    var stability = PrivacyReadingStability()
    let original = target
    check(!stability.observe(try position(), at: 0), "Start observation")
    target = scenario == "stability-empty-label" ? item("target", target.frame, " \n")
        : item("target", CGRect(x: 10, y: 700, width: 300, height: 50))
    elements = scenario == "stability-missing" ? [list] : [list, target]
    check(!stability.observe(try position(), at: 0.6), "An unreadable observation cannot qualify")
    target = original; elements = [list, target]
    check(!stability.observe(try position(), at: 1), "Returning content starts a new interval")
    check(!stability.observe(try position(), at: 1.49), "No interval across disappearance")
    check(stability.observe(try position(), at: 1.5), "A fresh stable interval qualifies")
case "invalid-frames":
    let invalidFrames = [
        CGRect.zero,
        CGRect(x: 0, y: 0, width: 20, height: 0),
        CGRect(x: 0, y: 0, width: -20, height: 50),
        CGRect(x: CGFloat.nan, y: 0, width: 20, height: 50),
        CGRect(x: 0, y: 0, width: CGFloat.infinity, height: 50)
    ]
    for invalid in invalidFrames {
        for slot in 0..<3 {
            rejects {
                _ = try PrivacyReadingSample.readPosition(
                    listIdentifier: "list", targetIdentifier: "target", needsCenter: false,
                    snapshot: {
                        PrivacyReadingTree(appFrame: slot == 0 ? invalid : bounds,
                            elements: [item("list", slot == 1 ? invalid : bounds),
                                       item("target", slot == 2 ? invalid : target.frame)],
                            navigationBars: [])
                    }, navigationBarIsHittable: { _ in fatalError("Invalid geometry must reject before hit-testing") })
            }
        }
    }
case "irrelevant-empty-navigation":
    bars = [item("hidden-nav", .zero)]
    check(try read().ready, "Preserve the ineffective finite navigation-bar skip")
    var stability = PrivacyReadingStability()
    check(!stability.observe(try position(), at: 0), "Start capture observation")
    check(stability.observe(try position(), at: 0.5), "An irrelevant empty bar does not prevent capture")
    check(barHitCalls == 0, "Do not hit-test an ineffective bar")
case "invalid-navigation":
    for frame in [
        CGRect(x: 0, y: 20, width: 0, height: 20),
        CGRect(x: 0, y: 50, width: 400, height: 0),
        CGRect(x: 0, y: 20, width: -20, height: 20),
        CGRect(x: CGFloat.nan, y: -100, width: 400, height: 20),
        CGRect(x: 0, y: -100, width: CGFloat.infinity, height: 20)
    ] {
        bars = [item("nav", frame)]
        rejects { _ = try position() }
    }
    check(barHitCalls == 0, "Reject relevant invalid or any nonfinite bar before hit-testing")
case "horizontal-capture-boundary":
    let original = target
    for x in [396.0, 397.0, 395.9, -296.0, -295.9] {
        var stability = PrivacyReadingStability()
        target = original; elements = [list, target]
        check(!stability.observe(try position(), at: 0), "Start with a readable position")
        target = item("target", CGRect(x: x, y: 150, width: 300, height: 50))
        elements = [list, target]
        check(!stability.observe(try position(), at: 0.6), "An edge or horizontal sliver cannot qualify")
        check(!stability.observe(try position(), at: 1.2), "Remaining outside does not become stable")
        target = original; elements = [list, target]
        check(!stability.observe(try position(), at: 1.5), "Returning content starts a fresh interval")
        check(stability.observe(try position(), at: 2), "Only the fully readable interval qualifies")
    }
    target = item("target", CGRect(x: 395.9, y: 150, width: 300, height: 50)); elements = [list, target]
    check(try read().ready, "The original reveal gate still delegates its decision to the live hit-test")
    check(targetHitCalls == 1, "Capture-only containment must not replace the original live gate")
case "horizontal-wrap-tolerance":
    target = item("target", CGRect(x: -2, y: 150, width: 404, height: 50)); elements = [list, target]
    var stability = PrivacyReadingStability()
    check(!stability.observe(try position(), at: 0), "Start at the existing wrap tolerance")
    check(stability.observe(try position(), at: 0.5), "Preserve both two-pixel wrap boundaries")
    target = item("target", CGRect(x: -2.1, y: 150, width: 404.2, height: 50)); elements = [list, target]
    check(!stability.observe(try position(), at: 1), "Reject a target exceeding the existing wrap tolerance")
    list = item("list", CGRect(x: -100, y: 0, width: 600, height: 600))
    target = item("target", CGRect(x: -50, y: 150, width: 500, height: 50)); elements = [list, target]
    check(!stability.observe(try position(), at: 2), "Being within the list is insufficient outside the actual app bounds")
case "stability-clock":
    var stability = PrivacyReadingStability()
    let sample = try position()
    check(!stability.observe(sample, at: 10), "Start interval")
    check(!stability.observe(sample, at: 10.4), "Not yet stable")
    check(!stability.observe(sample, at: 10.2), "Backward observation resets interval")
    check(!stability.observe(sample, at: 10.6), "No pre-reset time credit")
    check(!stability.observe(sample, at: .nan), "Nonfinite time resets interval")
    check(!stability.observe(sample, at: 11), "Start again after invalid time")
    check(stability.observe(sample, at: 11.5), "Fresh valid interval qualifies")
default: fatalError("Unknown scenario")
}
print("PASS \(scenario)")
