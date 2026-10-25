import UIKit
import UniformTypeIdentifiers

/// A bounded, local queue only. The containing app validates and rasterizes every input.
@MainActor
final class ShareViewController: UIViewController {
    private let status = UILabel()
    private let saveButton = UIButton(type: .system)
    private let cancelButton = UIButton(type: .system)
    private let spinner = UIActivityIndicatorView(style: .medium)
    private var task: Task<Void, Never>?
    private var stage: URL?
    private let gate = CopyGate()
    private var didSave = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        let title = UILabel(); title.text = L10n.text("Send to RedactLeaf"); title.font = .preferredFont(forTextStyle: .title1); title.numberOfLines = 0
        title.adjustsFontForContentSizeCategory = true
        status.text = L10n.text("Queue PDF and image copies for RedactLeaf, then open the app to choose what to hide. Originals stay unchanged. Copies older than 24 hours are removed when the main app next checks the queue.")
        status.font = .preferredFont(forTextStyle: .body); status.numberOfLines = 0; status.adjustsFontForContentSizeCategory = true
        configure(saveButton, title: L10n.text("Save to RedactLeaf"), textStyle: .headline)
        saveButton.addTarget(self, action: #selector(save), for: .touchUpInside)
        configure(cancelButton, title: L10n.text("Cancel"), textStyle: .body)
        cancelButton.addTarget(self, action: #selector(cancel), for: .touchUpInside)
        let stack = UIStackView(arrangedSubviews: [title, status, spinner, saveButton, cancelButton]); stack.axis = .vertical; stack.spacing = 24
        let scroll = UIScrollView(); scroll.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(scroll)
        stack.translatesAutoresizingMaskIntoConstraints = false; scroll.addSubview(stack)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor), scroll.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor), scroll.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor, constant: 24), stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 32), stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -32),
            stack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor, constant: -48),
            saveButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 44), cancelButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 44)
        ])
    }

    private func configure(_ button: UIButton, title: String, textStyle: UIFont.TextStyle) {
        var configuration = UIButton.Configuration.plain()
        configuration.title = title
        configuration.titleLineBreakMode = .byWordWrapping
        configuration.titleAlignment = .center
        configuration.titleTextAttributesTransformer = UIConfigurationTextAttributesTransformer { attributes in
            var result = attributes
            result.font = .preferredFont(forTextStyle: textStyle)
            return result
        }
        button.configuration = configuration
        button.titleLabel?.adjustsFontForContentSizeCategory = true
        button.setContentCompressionResistancePriority(.required, for: .vertical)
    }

    @objc private func save() {
        if didSave { extensionContext?.completeRequest(returningItems: nil); return }
        guard task == nil else { return }
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.io.github.4alvit.cleansend") else {
            status.text = L10n.text("The shared container is unavailable. Open RedactLeaf and import using Files instead."); return
        }
        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        let allProviders = items.flatMap { $0.attachments ?? [] }
        let providers = allProviders.compactMap { provider -> (NSItemProvider, String)? in
            if provider.hasItemConformingToTypeIdentifier(UTType.pdf.identifier) { return (provider, UTType.pdf.identifier) }
            guard let identifier = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .image) == true }) else { return nil }
            return (provider, identifier)
        }
        guard !providers.isEmpty, providers.count <= 20 else { status.text = L10n.text("Choose between 1 and 20 PDF or image files."); return }
        let sharedRoot = container.appendingPathComponent("SharedInbox", isDirectory: true)
        let name = UUID().uuidString
        let staging = sharedRoot.appendingPathComponent(name + ".incomplete", isDirectory: true)
        stage = staging
        saveButton.isEnabled = false; spinner.startAnimating(); status.text = L10n.text("Copying files locally…")
        task = Task {
            do {
                try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true, attributes: [.protectionKey: FileProtectionType.complete])
                var protectedRoot = sharedRoot
                var values = URLResourceValues(); values.isExcludedFromBackup = true
                try protectedRoot.setResourceValues(values)
                // Workspace owns expiry cleanup and knows which ready batches
                // it is reading. Never prune another process's files here.
                let queued = (try? FileManager.default.contentsOfDirectory(at: sharedRoot, includingPropertiesForKeys: nil)) ?? []
                guard queued.filter({ $0.pathExtension == "ready" }).count < 5 else {
                    throw ShareError.message(L10n.text("The import queue is full. Open RedactLeaf to import or clear earlier files."))
                }
                var totalBytes = 0
                for (index, item) in providers.enumerated() {
                    try Task.checkCancellation()
                    let ext = UTType(item.1)?.preferredFilenameExtension ?? "dat"
                    let sourceName = item.0.suggestedName.map { URL(fileURLWithPath: $0).deletingPathExtension().lastPathComponent } ?? "Shared file"
                    let safeName = String(sourceName.unicodeScalars.map { CharacterSet.alphanumerics.contains($0) || $0 == " " || $0 == "-" ? String($0) : "_" }.joined().prefix(64))
                    let destination = staging.appendingPathComponent("\(index + 1)-\(safeName)").appendingPathExtension(ext)
                    let bytes = try await Self.copy(item.0, type: item.1, to: destination, gate: gate)
                    totalBytes += bytes
                    guard totalBytes <= 50 * 1024 * 1024 else { throw ShareError.message(L10n.text("Choose a smaller batch, up to 50 MB total.")) }
                }
                try Task.checkCancellation()
                try FileManager.default.moveItem(at: staging, to: sharedRoot.appendingPathComponent(name + ".ready", isDirectory: true))
                stage = nil; didSave = true
                status.text = L10n.text("Files are queued. Open RedactLeaf and import a queued batch to review and hide details. Queuing alone does not remove private information.")
                if providers.count < allProviders.count { status.text? += " " + L10n.text("Unsupported attachments were skipped.") }
                saveButton.configuration?.title = L10n.text("Done"); saveButton.isEnabled = true; cancelButton.isHidden = true
                UIAccessibility.post(notification: .announcement, argument: status.text)
            } catch {
                try? FileManager.default.removeItem(at: staging); stage = nil
                if !(error is CancellationError) {
                    status.text = (error as? ShareError)?.errorDescription ?? L10n.text("Files could not be copied. Check available storage or import them from Files inside RedactLeaf.")
                }
                saveButton.configuration?.title = L10n.text("Close"); saveButton.isEnabled = true; didSave = true
            }
            spinner.stopAnimating(); task = nil
        }
    }

    @objc private func cancel() {
        gate.cancel()
        task?.cancel()
        if let stage { try? FileManager.default.removeItem(at: stage) }
        extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
    }

    private nonisolated static func copy(_ provider: NSItemProvider, type: String, to destination: URL, gate: CopyGate) async throws -> Int {
        try await withCheckedThrowingContinuation { continuation in
            provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
                do {
                    let bytes = try gate.perform {
                        guard let url else { throw error ?? ShareError.message(L10n.text("An attachment could not be read.")) }
                        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
                        guard values.isRegularFile == true, values.isSymbolicLink != true, let bytes = values.fileSize, bytes <= 50 * 1024 * 1024 else {
                            throw ShareError.message(L10n.text("Each attachment must be a regular file no larger than 50 MB."))
                        }
                        // Provider URLs are only valid during this callback.
                        try FileManager.default.copyItem(at: url, to: destination)
                        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: destination.path)
                        return bytes
                    }
                    continuation.resume(returning: bytes)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
}

private final class CopyGate: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    func cancel() { lock.lock(); cancelled = true; lock.unlock() }
    func perform<T>(_ body: () throws -> T) throws -> T {
        lock.lock(); defer { lock.unlock() }
        guard !cancelled else { throw CancellationError() }
        return try body()
    }
}

private enum ShareError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { return value }; return nil }
}
