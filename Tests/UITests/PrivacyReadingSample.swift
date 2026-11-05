import Foundation
import CoreGraphics

// Values from one public XCUIElement snapshot. No value is retained after a gesture.
struct PrivacyReadingElement: Equatable {
    let identifier: String
    let label: String
    let frame: CGRect
}

struct PrivacyReadingTree {
    let appFrame: CGRect
    let elements: [PrivacyReadingElement]
    let navigationBars: [PrivacyReadingElement]
}

struct PrivacyReadingSample {
    enum Invalid: Error {
        case missingOrAmbiguousList, ambiguousTarget, unexpectedTargetType, ambiguousNavigationBar
        case invalidFrame, unusableViewport
    }

    struct Position: Equatable {
        let appFrame: CGRect
        let target: PrivacyReadingElement?
        let listFrame: CGRect
        let viewport: CGRect
        let positioned: Bool
    }

    let position: Position
    let ready: Bool
    var target: PrivacyReadingElement? { position.target }
    var listFrame: CGRect { position.listFrame }
    var viewport: CGRect { position.viewport }

    init(position: Position, targetIsHittable: () -> Bool) {
        self.position = position
        // The interactive reading gate still requires its original live hit-test.
        ready = position.positioned && targetIsHittable()
    }

    static func read(
        listIdentifier: String, targetIdentifier: String, needsCenter: Bool,
        snapshot: () throws -> PrivacyReadingTree,
        navigationBarIsHittable: (PrivacyReadingElement) throws -> Bool,
        targetIsHittable: () -> Bool
    ) throws -> Self {
        let position = try readPosition(listIdentifier: listIdentifier, targetIdentifier: targetIdentifier,
                                        needsCenter: needsCenter, snapshot: snapshot,
                                        navigationBarIsHittable: navigationBarIsHittable)
        return Self(position: position, targetIsHittable: targetIsHittable)
    }

    static func readPosition(
        listIdentifier: String, targetIdentifier: String, needsCenter: Bool,
        snapshot: () throws -> PrivacyReadingTree,
        navigationBarIsHittable: (PrivacyReadingElement) throws -> Bool
    ) throws -> Position {
        let tree = try snapshot()
        let lists = tree.elements.filter { $0.identifier == listIdentifier }
        let targets = tree.elements.filter { $0.identifier == targetIdentifier }
        guard lists.count == 1 else { throw Invalid.missingOrAmbiguousList }
        guard targets.count <= 1 else { throw Invalid.ambiguousTarget }
        guard validFrame(tree.appFrame), validFrame(lists[0].frame),
              targets.allSatisfy({ validFrame($0.frame) }),
              tree.navigationBars.allSatisfy({ finiteFrame($0.frame) }) else {
            throw Invalid.invalidFrame
        }
        var identities = Set<[String]>()
        for bar in tree.navigationBars {
            guard identities.insert([bar.identifier, bar.label]).inserted else {
                throw Invalid.ambiguousNavigationBar
            }
        }
        let listFrame = lists[0].frame
        var visible = listFrame.intersection(tree.appFrame)
        for bar in tree.navigationBars {
            // Such a bar cannot change max(visible.minY, bar.maxY), even if hittable.
            // Other bars still require a real live hit-test, never geometry alone.
            if bar.frame.maxY <= visible.minY { continue }
            guard validFrame(bar.frame) else { throw Invalid.invalidFrame }
            if try navigationBarIsHittable(bar) {
                let top = max(visible.minY, bar.frame.maxY)
                visible = CGRect(x: visible.minX, y: top, width: visible.width,
                                 height: max(0, visible.maxY - top))
            }
        }
        visible = visible.insetBy(dx: 4, dy: 12)
        guard visible.width > 20, visible.height > 40 else { throw Invalid.unusableViewport }
        let target = targets.first
        let frame = target?.frame ?? .zero
        let overlap = visible.intersection(frame)
        let positioned = target != nil && (needsCenter ? visible.contains(CGPoint(x: frame.midX, y: frame.midY))
            : !overlap.isNull && overlap.height >= min(24, frame.height))
        return Position(appFrame: tree.appFrame, target: target, listFrame: listFrame,
                        viewport: visible, positioned: positioned)
    }

    private static func validFrame(_ frame: CGRect) -> Bool {
        finiteFrame(frame) && frame.size.width > 0 && frame.size.height > 0
    }

    private static func finiteFrame(_ frame: CGRect) -> Bool {
        frame.origin.x.isFinite && frame.origin.y.isFinite && frame.size.width.isFinite &&
            frame.size.height.isFinite && frame.maxX.isFinite && frame.maxY.isFinite
    }
}

// Capture-only settling after a successful reading gate. Static text need not
// supply a second activation point; every observation still uses fresh geometry.
struct PrivacyReadingStability {
    private var previous: PrivacyReadingSample.Position?
    private var stableSince: TimeInterval?
    private var lastObservation: TimeInterval?

    mutating func observe(_ position: PrivacyReadingSample.Position, at time: TimeInterval) -> Bool {
        guard time.isFinite, position.positioned,
              let target = position.target,
              horizontallyReadable(target.frame, in: position),
              !target.label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            previous = nil
            stableSince = nil
            lastObservation = nil
            return false
        }
        if previous != position || stableSince == nil || time < (lastObservation ?? time) {
            previous = position
            stableSince = time
            lastObservation = time
            return false
        }
        lastObservation = time
        return time - stableSince! >= 0.5
    }

    private func horizontallyReadable(_ frame: CGRect, in position: PrivacyReadingSample.Position) -> Bool {
        let bounds = position.listFrame.intersection(position.appFrame)
        // Match the paragraph wrapping tolerance while also requiring actual
        // horizontal overlap. This is a capture rule, not a replacement hit-test.
        return frame.intersection(position.viewport).width > 0 &&
            frame.minX >= bounds.minX - 2 && frame.maxX <= bounds.maxX + 2
    }
}
