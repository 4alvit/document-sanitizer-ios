#if CLEANSEND_SHARE_TRACE
import Foundation
import Darwin

/// Diagnostic-only, numeric phases. Normal builds do not compile this file.
enum ShareTracePhase: Int {
    case exportBegin = 1, workerComplete, mainResume, publicationBegin, publicationEnd
    case controllerBegin, controllerInitialized, viewLoadBegin, viewLoaded, appeared
    case mainPulse, completion, disappeared, deadline
}

/// Thread-safe timestamps only; no URL, document, label, error or arbitrary text input.
final class ShareTraceRecorder: @unchecked Sendable {
    typealias Event = [UInt64]
    private let lock = NSLock()
    private let clock: @Sendable () -> Double
    private let sink: @Sendable (Event) -> Void
    private var started: Double?
    private var previous: Double = 0
    private var active = false
    private var count = 0
    static let maximumEvents = 128
    static let maximumDuration: Double = 60

    init(clock: @escaping @Sendable () -> Double,
         sink: @escaping @Sendable (Event) -> Void) {
        self.clock = clock
        self.sink = sink
    }

    @discardableResult
    func begin() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard started == nil else { return false }
        let now = clock()
        guard valid(now) else { return false }
        started = now; previous = now; active = true
        emit(.exportBegin, at: now, lateness: 0)
        return true
    }

    func record(_ phase: ShareTracePhase, lateness: Double = 0) {
        lock.lock(); defer { lock.unlock() }
        guard active, let started else { return }
        let now = clock()
        guard valid(now), now >= previous, valid(lateness), count < Self.maximumEvents else {
            active = false
            return
        }
        let actual = now - started >= Self.maximumDuration || count == Self.maximumEvents - 1
            ? ShareTracePhase.deadline : phase
        emit(actual, at: now, lateness: lateness)
        if actual == .completion || actual == .disappeared || actual == .deadline {
            active = false
        }
    }

    var isActive: Bool {
        lock.lock(); defer { lock.unlock() }
        return active
    }

    private func valid(_ value: Double) -> Bool {
        value.isFinite && value >= 0 && value < Double(UInt64.max / 1_000_000)
    }

    private func emit(_ phase: ShareTracePhase, at now: Double, lateness: Double) {
        count += 1; previous = now
        // Serial submission under the lock preserves cross-thread event order.
        sink([1, UInt64(phase.rawValue), UInt64(now * 1_000_000), UInt64(lateness * 1_000_000)])
    }
}

/// I/O never runs on the UI thread. Existing files and symlinks are not overwritten.
final class ShareTraceFileSink: @unchecked Sendable {
    private let queue = DispatchQueue(label: "io.github.4alvit.cleansend.share-phase-trace")
    private let url: URL
    private var descriptor: Int32 = -1
    private var attempted = false
    private var bytes = 0
    static let maximumBytes = 16 * 1024

    init(url: URL) { self.url = url }

    func append(_ event: ShareTraceRecorder.Event) {
        guard event.count == 4, event[0] == 1,
              (1...UInt64(ShareTracePhase.deadline.rawValue)).contains(event[1]) else { return }
        queue.async { [self] in
            if !attempted {
                attempted = true
                descriptor = Darwin.open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW,
                                         S_IRUSR | S_IWUSR)
            }
            guard descriptor >= 0 else { return }
            let raw = Array(("[" + event.map(String.init).joined(separator: ",") + "]\n").utf8)
            guard raw.count <= Self.maximumBytes - bytes else { close(); return }
            let written = raw.withUnsafeBytes { buffer -> Bool in
                guard let base = buffer.baseAddress else { return false }
                var offset = 0
                while offset < raw.count {
                    let n = Darwin.write(descriptor, base.advanced(by: offset), raw.count - offset)
                    if n < 0 && errno == EINTR { continue }
                    guard n > 0 else { return false }
                    offset += n
                }
                return true
            }
            guard written else { close(); return }
            bytes += raw.count
            if event[1] >= UInt64(ShareTracePhase.completion.rawValue) { close() }
        }
    }

    /// Test/collector barrier only; application recording never waits for I/O.
    func drain() { queue.sync {} }

    private func close() {
        if descriptor >= 0 { Darwin.close(descriptor); descriptor = -1 }
    }

    deinit { if descriptor >= 0 { Darwin.close(descriptor) } }
}

enum SharePhaseTrace {
    static func enabled(_ environment: [String: String]) -> Bool {
        environment["CLEANSEND_SHARE_TRACE"] == "1"
    }

    #if targetEnvironment(simulator)
    private static let recorder: ShareTraceRecorder? = {
        guard enabled(ProcessInfo.processInfo.environment),
              let directory = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else {
            return nil
        }
        let sink = ShareTraceFileSink(url: directory.appendingPathComponent("cleansend-share-phase-trace-v1.jsonl"))
        return ShareTraceRecorder(clock: { ProcessInfo.processInfo.systemUptime }, sink: { sink.append($0) })
    }()

    static func begin() {
        guard let recorder, recorder.begin() else { return }
        pulse(recorder, remaining: 60)
    }

    static func record(_ phase: ShareTracePhase) { recorder?.record(phase) }

    private static func pulse(_ recorder: ShareTraceRecorder, remaining: Int) {
        guard remaining > 0, recorder.isActive else { return }
        let expected = ProcessInfo.processInfo.systemUptime + 1
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
            guard recorder.isActive else { return }
            recorder.record(.mainPulse, lateness: max(0, ProcessInfo.processInfo.systemUptime - expected))
            if remaining == 1 { recorder.record(.deadline) }
            else { pulse(recorder, remaining: remaining - 1) }
        }
    }
    #endif
}
#endif
