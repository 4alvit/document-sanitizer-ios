import Foundation

/// Opt-in observation of the synthetic simulator export. Never changes export
/// readiness, privacy decisions, or the native sheet's acceptance deadline.
final class ShareTiming: @unchecked Sendable {
    enum Phase: String {
        case exportStarted, filesReady, mainActorResumed, packetPublished
        case controllerStarted, controllerInitialized, controllerViewReady, controllerReturned
        case sheetAppeared, activityCompleted, sheetDisappeared, cleanupStarted, cleanupFinished
    }

    static func requestedTrace(synthetic: Bool, environment: [String: String]) -> UUID? {
        guard synthetic, environment["REDACT_SHARE_TIMING"] == "1",
              let value = environment["REDACT_SHARE_TRACE"],
              let id = UUID(uuidString: value), id.uuidString.lowercased() == value else { return nil }
        return id
    }

    static func start(synthetic: Bool, operation: UUID) -> ShareTiming? {
        #if targetEnvironment(simulator)
        guard let trace = requestedTrace(synthetic: synthetic, environment: ProcessInfo.processInfo.environment),
              let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else { return nil }
        return ShareTiming(trace: trace, operation: operation, cacheRoot: cache)
        #else
        return nil
        #endif
    }

    // The same small app-owned file pattern as the local StoreKit diagnostic,
    // but available in Release simulators. No URLs or document data are logged.
    let queue = DispatchQueue(label: "CleanSend.synthetic-share-timing", qos: .utility)
    let url: URL
    private let trace: UUID
    private let operation: UUID
    private let lock = NSLock()
    private var sequence = 0
    // Accessed only by queue; record() bounds submissions before enqueueing.
    private var handle: FileHandle?
    private var written = 0
    private var disabled = false

    init(trace: UUID, operation: UUID, cacheRoot: URL) {
        self.trace = trace
        self.operation = operation
        url = cacheRoot.appendingPathComponent("ShareTiming", isDirectory: true)
            .appendingPathComponent(trace.uuidString.lowercased() + ".jsonl")
    }

    deinit { try? handle?.close() }

    func record(_ phase: Phase, packet: UUID? = nil) {
        lock.lock()
        defer { lock.unlock() }
        guard sequence < 32 else { return }
        sequence += 1
        // Capture event time before asynchronous I/O, including worker-to-main
        // handoff. Queue order cannot turn file-write delay into export delay.
        var row: [String: Any] = ["trace": trace.uuidString.lowercased(),
                                 "operation": operation.uuidString.lowercased(),
                                 "sequence": sequence, "phase": phase.rawValue,
                                 "uptime": ProcessInfo.processInfo.systemUptime,
                                 "time": Date().timeIntervalSince1970]
        if let packet { row["packet"] = packet.uuidString.lowercased() }
        guard var data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) else { return }
        data.append(0x0A)
        let payload = data
        queue.async { self.append(payload) }
    }

    private func append(_ data: Data) {
        guard !disabled else { return }
        do {
            guard written + data.count <= 16 * 1024 else { disabled = true; return }
            if handle == nil {
                let directory = url.deletingLastPathComponent()
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                        attributes: [.posixPermissions: 0o700])
                guard try directory.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else {
                    disabled = true; return
                }
                // Refuse an old trace rather than truncate or append to it.
                try Data().write(to: url, options: [.withoutOverwriting])
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
                handle = try FileHandle(forWritingTo: url)
            }
            try handle?.write(contentsOf: data)
            written += data.count
        } catch {
            disabled = true
            try? handle?.close()
            handle = nil
        }
    }
}
