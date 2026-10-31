import Combine
import Darwin
import Foundation
import SanitizerCore

/// Presets contain placement only. Images, source names, OCR and document
/// identities never enter the persistent library.
struct MaskPreset: Identifiable, Codable, Equatable, Sendable {
    let id: UUID
    let name: String
    let rectangles: [NormalizedRect]

    init(id: UUID = UUID(), name: String, rectangles: [NormalizedRect]) {
        self.id = id
        self.name = name
        self.rectangles = rectangles
    }
}

enum MaskPresetError: Error, LocalizedError, Equatable {
    case requiresPro, invalidName, duplicateName, emptyPreset, invalidGeometry
    case tooManyRectangles, libraryFull, libraryUnavailable, invalidLibrary
    case unsupportedVersion, libraryTooLarge, readFailed, writeFailed

    var errorDescription: String? {
        switch self {
        case .requiresPro: return L10n.text("Creating a preset requires Pro. Your current page and saved presets are unchanged.")
        case .invalidName: return L10n.text("Use a preset name between 1 and 80 characters without control characters.")
        case .duplicateName: return L10n.text("A preset with this name already exists. Choose another name.")
        case .emptyPreset: return L10n.text("Add at least one redaction area before saving a preset.")
        case .invalidGeometry: return L10n.text("A preset contains invalid redaction coordinates. No changes were saved.")
        case .tooManyRectangles: return L10n.text("A preset can contain at most 200 redaction areas.")
        case .libraryFull: return L10n.text("You can save up to 50 presets. Delete a preset before creating another.")
        case .libraryUnavailable: return L10n.text("The preset library could not be loaded. Retry loading it or explicitly reset the library.")
        case .invalidLibrary: return L10n.text("The saved preset library is damaged. Retry loading it or explicitly reset the library.")
        case .unsupportedVersion: return L10n.text("This preset library uses an unsupported version. It has not been changed.")
        case .libraryTooLarge: return L10n.text("The preset library exceeds its 1 MiB size limit. No changes were saved.")
        case .readFailed: return L10n.text("The preset library could not be read. Retry when device storage is available.")
        case .writeFailed: return L10n.text("The preset library could not be saved. Its previous contents are unchanged.")
        }
    }
}

@MainActor
final class MaskPresetStore: ObservableObject {
    static let maximumPresets = 50
    static let maximumNameLength = 80
    static let maximumRectangles = 200
    static let maximumFileBytes = 1_024 * 1_024

    @Published private(set) var presets: [MaskPreset] = []
    @Published private(set) var loadError: String?

    private struct Library: Codable {
        let version: Int
        let presets: [MaskPreset]
    }

    private let directory: URL
    private let fileURL: URL
    private let writeStaging: (Data, URL) throws -> Void
    private var loadedSuccessfully = false

    /// Injection controls only writing a temporary staging file, never the
    /// destination replacement. This keeps failure atomicity under test.
    init(directory: URL? = nil, writeStaging: ((Data, URL) throws -> Void)? = nil) {
        let directory = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("RedactLeaf", isDirectory: true)
            .appendingPathComponent("Presets", isDirectory: true)
        self.directory = directory
        fileURL = directory.appendingPathComponent("library.json")
        self.writeStaging = writeStaging ?? { data, url in
            try data.write(to: url, options: .completeFileProtection)
        }
        reload()
    }

    /// Failure preserves both the existing file and any already loaded values.
    /// Creation/deletion stay disabled until a successful reload or explicit reset.
    func reload() {
        do {
            try prepareDirectory()
            let values: [MaskPreset]
            if let attributes = try attributesIfPresent(at: fileURL) {
                guard attributes[.type] as? FileAttributeType == .typeRegular else {
                    throw MaskPresetError.invalidLibrary
                }
                let handle = try FileHandle(forReadingFrom: fileURL)
                defer { try? handle.close() }
                let data = try handle.read(upToCount: Self.maximumFileBytes + 1) ?? Data()
                guard data.count <= Self.maximumFileBytes else { throw MaskPresetError.libraryTooLarge }
                let library: Library
                do { library = try JSONDecoder().decode(Library.self, from: data) }
                catch { throw MaskPresetError.invalidLibrary }
                guard library.version == 1 else { throw MaskPresetError.unsupportedVersion }
                try Self.validate(library.presets)
                values = library.presets
            } else {
                values = []
            }
            presets = values
            loadedSuccessfully = true
            loadError = nil
        } catch {
            loadedSuccessfully = false
            loadError = (error as? MaskPresetError ?? .readFailed).localizedDescription
        }
    }

    @discardableResult
    func create(name: String, rectangles: [NormalizedRect], currentIsPro: @MainActor () -> Bool) throws -> MaskPreset {
        guard loadedSuccessfully else { throw MaskPresetError.libraryUnavailable }
        let preset = MaskPreset(name: name.trimmingCharacters(in: .whitespacesAndNewlines), rectangles: rectangles)
        let proposed = presets + [preset]
        let data = try encoded(proposed)
        // No suspension between live authorization and the atomic commit.
        guard currentIsPro() else { throw MaskPresetError.requiresPro }
        try persist(data)
        presets = proposed
        return preset
    }

    /// Removing a preset never changes masks already applied to a document.
    func delete(id: UUID) throws {
        guard loadedSuccessfully else { throw MaskPresetError.libraryUnavailable }
        guard presets.contains(where: { $0.id == id }) else { return }
        let proposed = presets.filter { $0.id != id }
        try persist(encoded(proposed))
        presets = proposed
    }

    /// Only call after the person explicitly confirms losing the saved library.
    /// A damaged/unsupported library is never reset automatically.
    func reset() throws {
        try persist(encoded([]))
        presets = []
        loadedSuccessfully = true
        loadError = nil
    }

    private func encoded(_ values: [MaskPreset]) throws -> Data {
        try Self.validate(values)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let data = try encoder.encode(Library(version: 1, presets: values))
        guard data.count <= Self.maximumFileBytes else { throw MaskPresetError.libraryTooLarge }
        return data
    }

    private static func validate(_ values: [MaskPreset]) throws {
        guard values.count <= maximumPresets else { throw MaskPresetError.libraryFull }
        var ids: Set<UUID> = []
        var names: Set<String> = []
        var nameBytes = 0
        for preset in values {
            // Character count alone does not bound a long combining-mark
            // sequence. Reject impossible-to-fit input before JSON encoding.
            nameBytes += preset.name.utf8.count
            guard nameBytes <= maximumFileBytes else { throw MaskPresetError.libraryTooLarge }
            guard ids.insert(preset.id).inserted else { throw MaskPresetError.invalidLibrary }
            let trimmed = preset.name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty, trimmed == preset.name, trimmed.count <= maximumNameLength,
                  trimmed.rangeOfCharacter(from: .controlCharacters) == nil else { throw MaskPresetError.invalidName }
            let nameKey = trimmed.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive],
                                          locale: Locale(identifier: "en_US_POSIX"))
            guard names.insert(nameKey).inserted else { throw MaskPresetError.duplicateName }
            guard !preset.rectangles.isEmpty else { throw MaskPresetError.emptyPreset }
            guard preset.rectangles.count <= maximumRectangles else { throw MaskPresetError.tooManyRectangles }
            guard preset.rectangles.allSatisfy(\.isValid) else { throw MaskPresetError.invalidGeometry }
        }
    }

    private func prepareDirectory() throws {
        guard directory.isFileURL else { throw MaskPresetError.invalidLibrary }
        if try attributesIfPresent(at: directory) == nil {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.protectionKey: FileProtectionType.complete])
        }
        guard try attributesIfPresent(at: directory)?[.type] as? FileAttributeType == .typeDirectory else {
            throw MaskPresetError.invalidLibrary
        }
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: directory.path)
        var protectedDirectory = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try protectedDirectory.setResourceValues(values)
    }

    /// Read fresh filesystem metadata without following a final symbolic link.
    /// URL resource values may be cached across reloads, while fileExists follows
    /// links and incorrectly treats a dangling library link as a new library.
    private func attributesIfPresent(at url: URL) throws -> [FileAttributeKey: Any]? {
        do {
            return try FileManager.default.attributesOfItem(atPath: url.path)
        } catch let error as CocoaError where error.code == .fileNoSuchFile || error.code == .fileReadNoSuchFile {
            return nil
        }
    }

    private func persist(_ data: Data) throws {
        let staging = directory.appendingPathComponent(".preset-write-\(UUID().uuidString).tmp")
        defer { try? FileManager.default.removeItem(at: staging) }
        do {
            try prepareDirectory()
            try writeStaging(data, staging)
            try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: staging.path)
            var protectedFile = staging
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try protectedFile.setResourceValues(values)
            // Both paths share a directory/filesystem. Rename either replaces
            // the full prior file atomically or leaves it untouched on failure.
            guard rename(staging.path, fileURL.path) == 0 else { throw MaskPresetError.writeFailed }
        } catch {
            throw MaskPresetError.writeFailed
        }
    }
}
