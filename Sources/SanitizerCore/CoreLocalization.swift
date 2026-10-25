import Foundation
import LocalizationSupport

enum CoreL10n {
    static func text(_ key: String) -> String { LocalizedCatalog(bundle: .module).text(key) }
}
