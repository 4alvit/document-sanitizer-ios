import UIKit
import Combine

/// Cover every app window, including presented previews, before the app switcher snapshot.
@MainActor
final class PrivacyShield: NSObject, ObservableObject {
    private var covers: [UIView] = []
    override init() {
        super.init()
        NotificationCenter.default.addObserver(self, selector: #selector(cover), name: UIApplication.willResignActiveNotification, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(reveal), name: UIApplication.didBecomeActiveNotification, object: nil)
    }
    @objc private func cover() {
        reveal()
        for scene in UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }) {
            for window in scene.windows where !window.isHidden {
                let panel = UIView(frame: window.bounds)
                panel.autoresizingMask = [.flexibleWidth, .flexibleHeight]
                panel.backgroundColor = .systemBackground
                let title = UILabel(); title.text = L10n.text("RedactLeaf"); title.font = .preferredFont(forTextStyle: .largeTitle)
                title.translatesAutoresizingMaskIntoConstraints = false
                panel.addSubview(title)
                NSLayoutConstraint.activate([title.centerXAnchor.constraint(equalTo: panel.centerXAnchor), title.centerYAnchor.constraint(equalTo: panel.centerYAnchor)])
                window.addSubview(panel); covers.append(panel)
            }
        }
    }
    @objc private func reveal() { covers.forEach { $0.removeFromSuperview() }; covers = [] }
}
