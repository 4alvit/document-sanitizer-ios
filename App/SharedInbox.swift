import Foundation

/// The share extension prefixes each attachment with its selection position.
/// Read both legacy unpadded names and any future zero-padded names in that order.
enum SharedInbox {
    static func orderedFiles(in directory: URL) -> [URL] {
        ordered((try? FileManager.default.contentsOfDirectory(at: directory,
                                                              includingPropertiesForKeys: nil)) ?? [])
    }

    static func ordered(_ urls: [URL]) -> [URL] {
        urls.enumerated().map { position, url in
            (position: position, url: url, name: url.lastPathComponent,
             number: attachmentNumber(url.lastPathComponent))
        }.sorted { lhs, rhs in
            switch (lhs.number, rhs.number) {
            case let (.some(left), .some(right)) where left != right:
                // Decimal digit count and lexical comparison avoid integer overflow.
                return left.count == right.count ? left < right : left.count < right.count
            case (.some, .none): return true
            case (.none, .some): return false
            default:
                if lhs.name != rhs.name { return lhs.name < rhs.name }
                return lhs.position < rhs.position
            }
        }.map(\.url)
    }

    private static func attachmentNumber(_ name: String) -> String? {
        guard let separator = name.firstIndex(of: "-") else { return nil }
        let digits = name[..<separator].utf8
        guard !digits.isEmpty, digits.allSatisfy({ (48...57).contains($0) }) else { return nil }
        let significant = digits.drop(while: { $0 == 48 })
        return significant.isEmpty ? "0" : String(decoding: significant, as: UTF8.self)
    }
}
