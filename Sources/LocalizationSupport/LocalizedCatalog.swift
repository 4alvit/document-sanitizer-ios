import Foundation

/// Resolves UI language from a resource bundle, independently of regional formatting.
/// Callers supply their own bundle: the application, extension, or Swift package.
public struct LocalizedCatalog {
    public let language: String
    public let formattingLocale: Locale
    private let localizedBundle: Bundle
    private let englishBundle: Bundle

    public init(bundle: Bundle, preferredLanguages: [String]? = nil, formattingLocale: Locale = .current) {
        let available = bundle.localizations.filter { $0 != "Base" }.sorted()
        let preferences = preferredLanguages ?? bundle.preferredLocalizations
        let selected = Bundle.preferredLocalizations(from: available, forPreferences: preferences).first ?? "en"
        language = selected
        self.formattingLocale = formattingLocale
        englishBundle = bundle.path(forResource: "en", ofType: "lproj").flatMap(Bundle.init(path:)) ?? bundle
        localizedBundle = bundle.path(forResource: selected, ofType: "lproj").flatMap(Bundle.init(path:)) ?? englishBundle
    }

    public func text(_ key: String) -> String {
        let translated = localizedBundle.localizedString(forKey: key, value: nil, table: "Localizable")
        if translated != key { return translated }
        return englishBundle.localizedString(forKey: key, value: key, table: "Localizable")
    }

    /// Arguments are already formatted values or literal user content, never lookup keys.
    public func format(_ key: String, _ arguments: String...) -> String {
        format(key, arguments: arguments)
    }

    public func format(_ key: String, arguments: [String]) -> String {
        String(format: text(key), locale: formattingLocale, arguments: arguments.map { $0 as CVarArg })
    }

    /// CLDR cardinal rules for the supported UI languages, for integer counts.
    /// Selecting grammar from the region (for example en_US with a Russian UI)
    /// would incorrectly treat 5 and 21 like English plural counts.
    public func count(_ key: String, _ value: Int) -> String {
        let n = value.magnitude
        let category: String
        if language.split(separator: "-").first == "ru" {
            if n % 10 == 1 && n % 100 != 11 { category = "one" }
            else if (2...4).contains(n % 10) && !(12...14).contains(n % 100) { category = "few" }
            else { category = "many" }
        } else {
            category = n == 1 ? "one" : "other"
        }
        return format(key + "." + category, number(value))
    }

    public func number(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.locale = formattingLocale
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    public func number(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.locale = formattingLocale
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    public func percent(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.locale = formattingLocale
        formatter.numberStyle = .percent
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: value)) ?? number(value * 100)
    }

    public func currency(_ value: Double, code: String) -> String {
        let formatter = NumberFormatter()
        formatter.locale = formattingLocale
        formatter.numberStyle = .currency
        formatter.currencyCode = code
        return formatter.string(from: NSNumber(value: value)) ?? number(value)
    }
}
