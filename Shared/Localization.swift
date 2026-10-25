import Foundation
import LocalizationSupport

/// Compiled into both executables, so each resolves its own localized resources.
enum L10n {
    static var catalog: LocalizedCatalog { LocalizedCatalog(bundle: .main) }
    static func text(_ key: String) -> String { catalog.text(key) }
    static func format(_ key: String, _ arguments: String...) -> String { catalog.format(key, arguments: arguments) }
    static func count(_ key: String, _ value: Int) -> String { catalog.count(key, value) }
    static func number(_ value: Int) -> String { catalog.number(value) }
    static func number(_ value: Double) -> String { catalog.number(value) }
    static func percent(_ value: Double) -> String { catalog.percent(value) }
    static func currency(_ value: Double, code: String) -> String { catalog.currency(value, code: code) }
}
