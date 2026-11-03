import Foundation
import CoreGraphics

// Values from one public XCUIElement snapshot. No value is retained after a gesture.
struct PrivacyReadingElement {
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
        case missingOrAmbiguousList, ambiguousTarget, ambiguousNavigationBar, unusableViewport
    }

    let target: PrivacyReadingElement?
    let listFrame: CGRect
    let viewport: CGRect
    let ready: Bool

    static func read(
        listIdentifier: String, targetIdentifier: String, needsCenter: Bool,
        snapshot: () throws -> PrivacyReadingTree,
        navigationBarIsHittable: (PrivacyReadingElement) throws -> Bool,
        targetIsHittable: () -> Bool
    ) throws -> Self {
        let tree = try snapshot()
        let lists = tree.elements.filter { $0.identifier == listIdentifier }
        let targets = tree.elements.filter { $0.identifier == targetIdentifier }
        guard lists.count == 1 else { throw Invalid.missingOrAmbiguousList }
        guard targets.count <= 1 else { throw Invalid.ambiguousTarget }
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
        let positioned = needsCenter ? visible.contains(CGPoint(x: frame.midX, y: frame.midY))
            : !overlap.isNull && overlap.height >= min(24, frame.height)
        // Do not ask AX to hit-test an absent/offscreen target.
        let ready = target != nil && positioned && targetIsHittable()
        return Self(target: target, listFrame: listFrame, viewport: visible, ready: ready)
    }
}
