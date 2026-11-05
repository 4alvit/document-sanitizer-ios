import XCTest
@testable import CleanSend

final class ShareTimingTests: XCTestCase {
    func testRequiresExplicitSyntheticTrace() {
        let id = UUID().uuidString.lowercased()
        let enabled = ["REDACT_SHARE_TIMING": "1", "REDACT_SHARE_TRACE": id]
        XCTAssertEqual(ShareTiming.requestedTrace(synthetic: true, environment: enabled)?.uuidString.lowercased(), id)
        XCTAssertNil(ShareTiming.requestedTrace(synthetic: false, environment: enabled))
        XCTAssertNil(ShareTiming.requestedTrace(synthetic: true, environment: ["REDACT_SHARE_TRACE": id]))
        for invalid in ["../outside", id.uppercased(), "", id + "/trace"] {
            XCTAssertNil(ShareTiming.requestedTrace(synthetic: true, environment:
                ["REDACT_SHARE_TIMING": "1", "REDACT_SHARE_TRACE": invalid]))
        }
    }

    func testFixedFieldsAndEventBound() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let trace = ShareTiming(trace: UUID(), operation: UUID(), cacheRoot: root)
        for _ in 0..<100 { trace.record(.filesReady) }
        trace.queue.sync {}
        let raw = try Data(contentsOf: trace.url)
        XCTAssertLessThanOrEqual(raw.count, 16 * 1024)
        let rows = raw.split(separator: 0x0A)
        XCTAssertEqual(rows.count, 32)
        var previous: Double = -1
        for (index, data) in rows.enumerated() {
            let row = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(data)) as? [String: Any])
            XCTAssertEqual(Set(row.keys), ["trace", "operation", "sequence", "phase", "uptime", "time"])
            XCTAssertEqual(row["sequence"] as? Int, index + 1)
            XCTAssertEqual(row["phase"] as? String, "filesReady")
            let uptime = try XCTUnwrap(row["uptime"] as? Double)
            XCTAssertGreaterThanOrEqual(uptime, previous)
            previous = uptime
        }
    }

    func testOldTraceAndFileFailureDoNotOverwriteOtherData() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let trace = ShareTiming(trace: UUID(), operation: UUID(), cacheRoot: root)
        try FileManager.default.createDirectory(at: trace.url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let original = Data("existing owned fixture".utf8)
        try original.write(to: trace.url)
        trace.record(.exportStarted)
        trace.queue.sync {}
        XCTAssertEqual(try Data(contentsOf: trace.url), original)

        let blocked = root.appendingPathComponent("not-a-directory")
        try original.write(to: blocked)
        let failed = ShareTiming(trace: UUID(), operation: UUID(), cacheRoot: blocked)
        failed.record(.exportStarted)
        failed.record(.filesReady)
        failed.queue.sync {}
        XCTAssertEqual(try Data(contentsOf: blocked), original)
    }
}
