import Foundation

/// Bundled information has no purchase or networking dependency. Keep online
/// resources separate so reading the information never opens a URL.
enum PrivacySupportContent {
    struct Section: Identifiable {
        let id: String
        let titleKey: String
        let paragraphKeys: [String]
    }

    static let sections: [Section] = [
        Section(id: "overview", titleKey: "privacy.overview.title", paragraphKeys: ["privacy.overview.offline", "privacy.overview.processing"]),
        Section(id: "files", titleKey: "privacy.files.title", paragraphKeys: ["privacy.files.workspace", "privacy.files.temporary"]),
        Section(id: "queue", titleKey: "privacy.queue.title", paragraphKeys: ["privacy.queue.copies", "privacy.queue.deletion"]),
        Section(id: "presets", titleKey: "privacy.presets.title", paragraphKeys: ["privacy.presets.storage", "privacy.presets.deletion", "privacy.presets.placement"]),
        Section(id: "sharing", titleKey: "privacy.sharing.title", paragraphKeys: ["privacy.sharing.review", "privacy.sharing.output", "privacy.sharing.recipients"]),
        Section(id: "apple", titleKey: "privacy.apple.title", paragraphKeys: ["privacy.apple.services"]),
        Section(id: "support", titleKey: "privacy.support.title", paragraphKeys: ["privacy.support.public", "privacy.support.safe", "privacy.support.help"])
    ]

    // Published preview documents. A stable final policy and actual operator
    // details remain submission gates; do not point preview users at seed main.
    static let privacyPolicyURL = URL(string: "https://github.com/4alvit/document-sanitizer-ios/blob/d4976ab9a424fa1b3ef008b762fa668e8efb14b1/docs/PRIVACY.md")!
    static let supportGuideURL = URL(string: "https://github.com/4alvit/document-sanitizer-ios/blob/d4976ab9a424fa1b3ef008b762fa668e8efb14b1/docs/SUPPORT.md")!
    static let issuesURL = URL(string: "https://github.com/4alvit/document-sanitizer-ios/issues")!

    static let localizedKeys = sections.flatMap { [$0.titleKey] + $0.paragraphKeys } + [
        "privacy.online.title", "privacy.online.preview", "privacy.online.policy",
        "privacy.online.guide", "privacy.online.issues", "privacy.online.hint"
    ]
}
