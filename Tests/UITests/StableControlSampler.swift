import Foundation
import CoreGraphics

// Test-only sampling policy. Snapshot geometry and live hittability remain
// separate observations because XCTest snapshots do not expose hittability.
struct StableControlGeometry {
    let frame: CGRect
    let enabled: Bool
}

struct StableControlSampler {
    private let deadline: TimeInterval
    private var lastTime: TimeInterval
    private var previous = CGRect.null
    private var stableSince: TimeInterval?

    init(started: TimeInterval) {
        deadline = started + 6
        lastTime = started
    }

    private mutating func reset() {
        previous = .null
        stableSince = nil
    }

    private mutating func admissible(_ time: TimeInterval) -> Bool {
        guard time.isFinite, time >= lastTime, time <= deadline else {
            reset()
            return false
        }
        lastTime = time
        return true
    }

    mutating func poll(
        now: () -> TimeInterval,
        snapshot: () -> StableControlGeometry?,
        isHittable: () -> Bool
    ) -> Bool {
        guard admissible(now()) else { return false }
        let geometry = snapshot()
        guard admissible(now()) else { return false }
        guard let geometry, geometry.enabled,
              geometry.frame.origin.x.isFinite, geometry.frame.origin.y.isFinite,
              geometry.frame.width.isFinite, geometry.frame.height.isFinite,
              geometry.frame.width > 0, geometry.frame.height > 0 else {
            reset()
            return false
        }
        let hittable = isHittable()
        let completed = now()
        guard admissible(completed) else { return false }
        guard hittable else {
            reset()
            return false
        }
        guard geometry.frame == previous, let stableSince else {
            previous = geometry.frame
            stableSince = completed
            return false
        }
        return completed - stableSince >= 1
    }
}
