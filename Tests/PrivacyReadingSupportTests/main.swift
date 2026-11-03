import Foundation
import CoreGraphics

func check(_ condition: Bool, _ message: String) {
    if !condition { fatalError(message) }
}
func item(_ id: String, _ frame: CGRect, _ label: String = "Текст") -> PrivacyReadingElement {
    PrivacyReadingElement(identifier: id, label: label, frame: frame)
}
let bounds = CGRect(x: 0, y: 0, width: 400, height: 600)
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
default: fatalError("Unknown scenario")
}
print("PASS \(scenario)")
