import Foundation
import SanitizerCore
import XCTest
@testable import CleanSend

@MainActor
final class MaskPresetStoreTests: XCTestCase {
    private var directories: [URL] = []
    private let rect = NormalizedRect(x: 0.1, y: 0.2, width: 0.3, height: 0.4)

    override func tearDown() async throws {
        for directory in directories { try? FileManager.default.removeItem(at: directory) }
        directories.removeAll()
        try await super.tearDown()
    }

    func testRoundTripStoresOnlyVersionedNamedGeometry() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let saved = try store.create(name: "  Address areas  ", rectangles: [rect], currentIsPro: { true })
        XCTAssertEqual(saved.name, "Address areas")
        XCTAssertNil(store.loadError)

        let relaunched = MaskPresetStore(directory: directory)
        XCTAssertEqual(relaunched.presets, [saved])
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: file(in: directory))) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["version", "presets"])
        XCTAssertEqual(json["version"] as? Int, 1)
        let records = try XCTUnwrap(json["presets"] as? [[String: Any]])
        XCTAssertEqual(Set(try XCTUnwrap(records.first).keys), ["id", "name", "rectangles"])
        let rectangles = try XCTUnwrap(records[0]["rectangles"] as? [[String: Any]])
        XCTAssertEqual(Set(try XCTUnwrap(rectangles.first).keys), ["x", "y", "width", "height"])
    }

    func testCreationReadsLiveEntitlementAndDeletionRemainsAvailable() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        var isPro = true
        var checks = 0
        let currentIsPro = { checks += 1; return isPro }
        let saved = try store.create(name: "First", rectangles: [rect], currentIsPro: currentIsPro)
        let before = try Data(contentsOf: file(in: directory))
        isPro = false
        XCTAssertThrowsError(try store.create(name: "Entered before refund", rectangles: [rect], currentIsPro: currentIsPro)) {
            XCTAssertEqual($0 as? MaskPresetError, .requiresPro)
        }
        XCTAssertEqual(checks, 2)
        XCTAssertEqual(store.presets, [saved])
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
        try store.delete(id: saved.id)
        XCTAssertTrue(store.presets.isEmpty)
        XCTAssertTrue(MaskPresetStore(directory: directory).presets.isEmpty)
    }

    func testPartialStagingWriteFailurePreservesFileAndMemoryForEveryMutation() throws {
        let directory = temporaryDirectory()
        let writer = FailingPresetWriter()
        let store = MaskPresetStore(directory: directory, writeStaging: writer.write)
        let first = try store.create(name: "First", rectangles: [rect], currentIsPro: { true })
        let before = try Data(contentsOf: file(in: directory))
        writer.fail = true
        let mutations: [() throws -> Void] = [
            { _ = try store.create(name: "Second", rectangles: [self.rect], currentIsPro: { true }) },
            { try store.delete(id: first.id) },
            { try store.reset() }
        ]
        for mutation in mutations {
            XCTAssertThrowsError(try mutation()) { XCTAssertEqual($0 as? MaskPresetError, .writeFailed) }
            XCTAssertEqual(store.presets, [first])
            XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
            XCTAssertNil(store.loadError)
            let files = try FileManager.default.contentsOfDirectory(atPath: directory.path)
            XCTAssertEqual(files, ["library.json"], "Failed staging files must be removed.")
        }
    }

    func testMalformedLibraryBlocksMutationAndExplicitResetRecovers() throws {
        let directory = temporaryDirectory()
        let writer = FailingPresetWriter()
        let store = MaskPresetStore(directory: directory, writeStaging: writer.write)
        let saved = try store.create(name: "First", rectangles: [rect], currentIsPro: { true })
        let damaged = Data("{broken json".utf8)
        try damaged.write(to: file(in: directory))
        store.reload()
        let error = try XCTUnwrap(store.loadError)
        XCTAssertEqual(store.presets, [saved], "A failed reload must not destroy the in-memory library.")
        XCTAssertThrowsError(try store.create(name: "Second", rectangles: [rect], currentIsPro: { true })) {
            XCTAssertEqual($0 as? MaskPresetError, .libraryUnavailable)
        }
        XCTAssertThrowsError(try store.delete(id: saved.id)) {
            XCTAssertEqual($0 as? MaskPresetError, .libraryUnavailable)
        }
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), damaged)

        writer.fail = true
        XCTAssertThrowsError(try store.reset())
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), damaged)
        XCTAssertEqual(store.presets, [saved])
        XCTAssertEqual(store.loadError, error)
        writer.fail = false
        try store.reset()
        XCTAssertTrue(store.presets.isEmpty)
        XCTAssertNil(store.loadError)
        XCTAssertTrue(MaskPresetStore(directory: directory).presets.isEmpty)
    }

    func testUnsupportedVersionIsPreservedUntilExplicitReset() throws {
        let directory = temporaryDirectory()
        let future = try writeLibrary([], version: 99, directory: directory)
        let store = MaskPresetStore(directory: directory)
        XCTAssertEqual(store.loadError, MaskPresetError.unsupportedVersion.localizedDescription)
        XCTAssertThrowsError(try store.create(name: "New", rectangles: [rect], currentIsPro: { true }))
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), future)
        try store.reset()
        let reloaded = MaskPresetStore(directory: directory)
        XCTAssertNil(reloaded.loadError)
        XCTAssertTrue(reloaded.presets.isEmpty)
    }

    func testRetryReloadRecoversWithoutResetAfterFileIsRepaired() throws {
        let directory = temporaryDirectory()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("damaged".utf8).write(to: file(in: directory))
        let store = MaskPresetStore(directory: directory)
        XCTAssertNotNil(store.loadError)
        let saved = MaskPreset(name: "Recovered", rectangles: [rect])
        let repaired = try writeLibrary([saved], directory: directory)
        store.reload()
        XCTAssertNil(store.loadError)
        XCTAssertEqual(store.presets, [saved])
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), repaired)
    }

    func testMissingLibraryIsEmptyAndCanBeCreated() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        XCTAssertNil(store.loadError)
        XCTAssertTrue(store.presets.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: file(in: directory).path))
        let saved = try store.create(name: "First", rectangles: [rect], currentIsPro: { true })
        XCTAssertEqual(MaskPresetStore(directory: directory).presets, [saved])
    }

    func testReplacedLibrarySymlinkFailsClosedUntilExplicitReset() throws {
        for targetExists in [false, true] {
            let directory = temporaryDirectory()
            let store = MaskPresetStore(directory: directory)
            let saved = try store.create(name: "Original", rectangles: [rect], currentIsPro: { true })
            store.reload() // Also exercise any metadata retained by an earlier successful read.
            let destination = file(in: directory)
            let target = directory.appendingPathComponent("target.json")
            let targetData = try Data(contentsOf: destination)
            if targetExists { try targetData.write(to: target) }
            try FileManager.default.removeItem(at: destination)
            try FileManager.default.createSymbolicLink(at: destination, withDestinationURL: target)

            store.reload()
            XCTAssertEqual(store.loadError, MaskPresetError.invalidLibrary.localizedDescription)
            XCTAssertEqual(store.presets, [saved])
            XCTAssertThrowsError(try store.create(name: "New", rectangles: [rect], currentIsPro: { true })) {
                XCTAssertEqual($0 as? MaskPresetError, .libraryUnavailable)
            }
            XCTAssertThrowsError(try store.delete(id: saved.id)) {
                XCTAssertEqual($0 as? MaskPresetError, .libraryUnavailable)
            }
            XCTAssertEqual(try FileManager.default.destinationOfSymbolicLink(atPath: destination.path), target.path)

            // Reset replaces the link itself only after explicit user consent.
            try store.reset()
            XCTAssertNil(store.loadError)
            XCTAssertTrue(store.presets.isEmpty)
            XCTAssertEqual(try FileManager.default.attributesOfItem(atPath: destination.path)[.type] as? FileAttributeType, .typeRegular)
            XCTAssertTrue(MaskPresetStore(directory: directory).presets.isEmpty)
            if targetExists { XCTAssertEqual(try Data(contentsOf: target), targetData) }
            else { XCTAssertFalse(FileManager.default.fileExists(atPath: target.path)) }
        }
    }

    func testReplacedLibraryDirectorySymlinkDoesNotReadOrWriteItsTarget() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let saved = try store.create(name: "Original", rectangles: [rect], currentIsPro: { true })
        store.reload()
        let originalData = try Data(contentsOf: file(in: directory))
        let preserved = temporaryDirectory()
        try FileManager.default.moveItem(at: directory, to: preserved)
        let target = temporaryDirectory()
        let targetStore = MaskPresetStore(directory: target)
        _ = try targetStore.create(name: "Target", rectangles: [rect], currentIsPro: { true })
        let targetData = try Data(contentsOf: file(in: target))
        try FileManager.default.createSymbolicLink(at: directory, withDestinationURL: target)

        store.reload()
        XCTAssertEqual(store.loadError, MaskPresetError.invalidLibrary.localizedDescription)
        XCTAssertEqual(store.presets, [saved])
        XCTAssertThrowsError(try store.create(name: "New", rectangles: [rect], currentIsPro: { true }))
        XCTAssertThrowsError(try store.delete(id: saved.id))
        XCTAssertThrowsError(try store.reset()) { XCTAssertEqual($0 as? MaskPresetError, .writeFailed) }
        XCTAssertEqual(try FileManager.default.destinationOfSymbolicLink(atPath: directory.path), target.path)
        XCTAssertEqual(try Data(contentsOf: file(in: target)), targetData)
        XCTAssertEqual(try Data(contentsOf: file(in: preserved)), originalData)
        XCTAssertEqual(store.presets, [saved])
    }

    func testPositiveExtentsLostToFloatingPointRoundingAreRejectedOnCreateAndReload() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let saved = try store.create(name: "Original", rectangles: [rect], currentIsPro: { true })
        let before = try Data(contentsOf: file(in: directory))
        let invalid = [
            NormalizedRect(x: 1, y: 0, width: .leastNonzeroMagnitude, height: 0.1),
            NormalizedRect(x: 0, y: 1, width: 0.1, height: .leastNonzeroMagnitude),
            NormalizedRect(x: 0.5, y: 0, width: .leastNonzeroMagnitude, height: 0.1),
            NormalizedRect(x: 0, y: 0.5, width: 0.1, height: .leastNonzeroMagnitude)
        ]
        for geometry in invalid {
            XCTAssertThrowsError(try store.create(name: "Collapsed", rectangles: [geometry], currentIsPro: { true })) {
                XCTAssertEqual($0 as? MaskPresetError, .invalidGeometry)
            }
            XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
            XCTAssertEqual(store.presets, [saved])
        }
        for geometry in invalid {
            let malformed = try writeLibrary([MaskPreset(name: "Collapsed", rectangles: [geometry])], directory: directory)
            store.reload()
            XCTAssertEqual(store.loadError, MaskPresetError.invalidGeometry.localizedDescription)
            XCTAssertEqual(store.presets, [saved])
            XCTAssertEqual(try Data(contentsOf: file(in: directory)), malformed)
        }
    }

    func testRepresentableTinyExtentsRemainPersistable() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let increment = Double(0.5).nextUp - 0.5
        let rectangles = [
            NormalizedRect(x: 0.5, y: 0.5, width: increment, height: increment),
            NormalizedRect(x: 0, y: 0, width: .leastNonzeroMagnitude, height: .leastNonzeroMagnitude)
        ]
        let saved = try store.create(name: "Tiny but nonempty", rectangles: rectangles, currentIsPro: { true })
        let reloaded = MaskPresetStore(directory: directory)
        XCTAssertNil(reloaded.loadError)
        XCTAssertEqual(reloaded.presets, [saved])
        XCTAssertEqual(reloaded.presets.first?.rectangles, rectangles)
    }

    func testInvalidGeometryIsRejectedAtCreationAndDecode() throws {
        let invalid = [
            NormalizedRect(x: .nan, y: 0, width: 0.1, height: 0.1),
            NormalizedRect(x: 0, y: .infinity, width: 0.1, height: 0.1),
            NormalizedRect(x: -0.1, y: 0, width: 0.1, height: 0.1),
            NormalizedRect(x: 0, y: 0, width: 0, height: 0.1),
            NormalizedRect(x: 0.9, y: 0, width: 0.2, height: 0.1),
            NormalizedRect(x: 0, y: 0.9, width: 0.1, height: 0.2)
        ]
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let original = try store.create(name: "Valid", rectangles: [rect], currentIsPro: { true })
        let before = try Data(contentsOf: file(in: directory))
        for geometry in invalid {
            XCTAssertFalse(geometry.isValid)
            XCTAssertThrowsError(try store.create(name: "Invalid", rectangles: [geometry], currentIsPro: { true })) {
                XCTAssertEqual($0 as? MaskPresetError, .invalidGeometry)
            }
        }
        XCTAssertEqual(store.presets, [original])
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
        let malformed = try writeLibrary([MaskPreset(name: "Invalid", rectangles: [invalid[2]])], directory: directory)
        store.reload()
        XCTAssertNotNil(store.loadError)
        XCTAssertEqual(store.presets, [original])
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), malformed)
    }

    func testNameAndRectangleLimitsRejectWithoutChangingLibrary() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let original = try store.create(name: "Résumé", rectangles: [rect], currentIsPro: { true })
        let before = try Data(contentsOf: file(in: directory))
        let attempts: [(String, [NormalizedRect], MaskPresetError)] = [
            ("  resume  ", [rect], .duplicateName),
            ("\n\t ", [rect], .invalidName),
            ("Line\nBreak", [rect], .invalidName),
            (String(repeating: "a", count: 81), [rect], .invalidName),
            ("Empty", [], .emptyPreset),
            ("Too many", Array(repeating: rect, count: 201), .tooManyRectangles)
        ]
        for (name, rectangles, error) in attempts {
            XCTAssertThrowsError(try store.create(name: name, rectangles: rectangles, currentIsPro: { true })) {
                XCTAssertEqual($0 as? MaskPresetError, error)
            }
            XCTAssertEqual(store.presets, [original])
            XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
        }
        let boundary = try store.create(name: String(repeating: "b", count: 80), rectangles: Array(repeating: rect, count: 200), currentIsPro: { true })
        XCTAssertEqual(boundary.rectangles.count, 200)
    }

    func testLibraryCountLimitAndDuplicateIdentitiesAreValidatedOnLoad() throws {
        let directory = temporaryDirectory()
        let fifty = (0..<50).map { MaskPreset(name: "Preset \($0)", rectangles: [rect]) }
        let before = try writeLibrary(fifty, directory: directory)
        let store = MaskPresetStore(directory: directory)
        XCTAssertEqual(store.presets.count, 50)
        XCTAssertThrowsError(try store.create(name: "Preset 51", rectangles: [rect], currentIsPro: { true })) {
            XCTAssertEqual($0 as? MaskPresetError, .libraryFull)
        }
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
        let duplicate = MaskPreset(id: fifty[0].id, name: "Other", rectangles: [rect])
        let damaged = try writeLibrary([fifty[0], duplicate], directory: directory)
        store.reload()
        XCTAssertNotNil(store.loadError)
        XCTAssertEqual(store.presets, fifty)
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), damaged)
    }

    func testOversizedFileIsPreservedAndCannotBeOverwrittenByCreate() throws {
        let directory = temporaryDirectory()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let oversized = Data(repeating: 0x20, count: MaskPresetStore.maximumFileBytes + 1)
        try oversized.write(to: file(in: directory))
        let store = MaskPresetStore(directory: directory)
        XCTAssertEqual(store.loadError, MaskPresetError.libraryTooLarge.localizedDescription)
        XCTAssertThrowsError(try store.create(name: "New", rectangles: [rect], currentIsPro: { true }))
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), oversized)
    }

    func testOversizedEncodedNameDoesNotBypassCharacterLimitOrChangeFile() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        let original = try store.create(name: "Original", rectangles: [rect], currentIsPro: { true })
        let before = try Data(contentsOf: file(in: directory))
        let oversized = "x" + String(repeating: "\u{0301}", count: MaskPresetStore.maximumFileBytes / 2)
        XCTAssertEqual(oversized.count, 1)
        XCTAssertThrowsError(try store.create(name: oversized, rectangles: [rect], currentIsPro: { true })) {
            XCTAssertEqual($0 as? MaskPresetError, .libraryTooLarge)
        }
        XCTAssertEqual(store.presets, [original])
        XCTAssertEqual(try Data(contentsOf: file(in: directory)), before)
    }

    func testPersistedLibraryAndDirectoryAreExcludedFromBackup() throws {
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        _ = try store.create(name: "Protected", rectangles: [rect], currentIsPro: { true })
        for url in [directory, file(in: directory)] {
            XCTAssertEqual(try url.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
        }
    }

    func testPhysicalDeviceRecordsCompleteFileProtection() throws {
        #if targetEnvironment(simulator)
        // Apple DTS reproduced the missing complete-protection attribute in
        // Simulator: https://developer.apple.com/forums/thread/780632.
        // Simulator results do not establish iOS lock-state enforcement.
        throw XCTSkip("Complete file protection requires a physical iOS device; Simulator does not expose this protection class reliably.")
        #else
        let directory = temporaryDirectory()
        let store = MaskPresetStore(directory: directory)
        _ = try store.create(name: "Protected", rectangles: [rect], currentIsPro: { true })
        for var url in [directory, file(in: directory)] {
            url.removeAllCachedResourceValues()
            XCTAssertEqual(try url.resourceValues(forKeys: [.fileProtectionKey]).fileProtection, .complete)
        }
        // This verifies recorded metadata only. Release acceptance must also
        // check access while a passcode-protected physical device is locked,
        // then confirm that unlock/reload recovers the same library.
        #endif
    }

    func testStrictValidityAcceptsEdgesAndSubpixelAreasWithoutClamping() {
        XCTAssertTrue(NormalizedRect(x: 0, y: 0, width: 1, height: 1).isValid)
        XCTAssertTrue(NormalizedRect(x: 0.5, y: 0.5, width: 0.5, height: 0.5).isValid)
        XCTAssertTrue(NormalizedRect(x: 0, y: 0, width: 0.00001, height: 0.00001).isValid)
        XCTAssertFalse(NormalizedRect(x: 1, y: 0, width: 0.00001, height: 0.1).isValid)
    }

    private func temporaryDirectory() -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("MaskPresetTests-\(UUID().uuidString)", isDirectory: true)
        directories.append(directory)
        return directory
    }

    private func file(in directory: URL) -> URL { directory.appendingPathComponent("library.json") }

    @discardableResult
    private func writeLibrary(_ presets: [MaskPreset], version: Int = 1, directory: URL) throws -> Data {
        struct Fixture: Encodable { let version: Int; let presets: [MaskPreset] }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(Fixture(version: version, presets: presets))
        try data.write(to: file(in: directory))
        return data
    }
}

@MainActor
private final class FailingPresetWriter {
    var fail = false
    func write(_ data: Data, to url: URL) throws {
        if fail {
            // An actual partial staging file verifies that destination atomicity
            // is owned by MaskPresetStore, not assumed of an injected writer.
            try Data("partial".utf8).write(to: url)
            throw CocoaError(.fileWriteOutOfSpace)
        }
        try data.write(to: url)
    }
}
