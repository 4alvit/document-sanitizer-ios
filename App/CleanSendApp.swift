import SwiftUI
#if DEBUG && targetEnvironment(simulator)
import Darwin
#endif

@main
struct CleanSendApp: App {
    var body: some Scene {
        WindowGroup {
            #if DEBUG
            // Hosted unit tests load XCTest in the application process. Keep
            // their host inert so SKTestSession can initialize before any
            // StoreKit listener/request, and each test owns its workspace.
            // UI tests load XCTest in a separate runner, leaving this app intact.
            #if targetEnvironment(simulator)
            if NativeUnitTestHost.isInert() {
                EmptyView()
            } else {
                CleanSendRootView()
            }
            #else
            if NSClassFromString("XCTestCase") != nil {
                EmptyView()
            } else {
                CleanSendRootView()
            }
            #endif
            #else
            CleanSendRootView()
            #endif
        }
    }
}

private struct CleanSendRootView: View {
    @StateObject private var workspace = Workspace()
    @StateObject private var store = ProStore()
    @StateObject private var presetStore = MaskPresetStore()
    @StateObject private var privacyShield = PrivacyShield()
    @Environment(\.scenePhase) private var scenePhase

    @MainActor
    init() {
        #if DEBUG && targetEnvironment(simulator)
        NativeUnitTestHost.recordRootConstruction()
        #endif
    }

    var body: some View {
        ContentView()
            .modifier(UITestContentSize())
            .environmentObject(workspace)
            .environmentObject(store)
            .environmentObject(presetStore)
            .onAppear { _ = privacyShield }
            .task {
                #if DEBUG && targetEnvironment(simulator)
                workspace.importCommitDiagnostic = { [weak store] added, total, liveIsPro in
                    store?.recordImportCommit(addedPages: added, totalPages: total, liveIsPro: liveIsPro)
                }
                #endif
                workspace.checkSharedImports()
                await store.load()
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active {
                    workspace.checkSharedImports()
                    presetStore.reload()
                    Task { await store.load() }
                }
            }
    }
}

/// Debug-only layout scenario. It changes text size, never data or entitlements.
/// Apply at each presentation root because sheet environments are independent.
struct UITestContentSize: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--uitest-largest-type") {
            content.dynamicTypeSize(.accessibility5)
        } else {
            content
        }
        #else
        content
        #endif
    }
}

#if DEBUG && targetEnvironment(simulator)
/// Only the separately bound hosted-unit invocation sets this marker. It changes
/// host startup, never entitlements or production StoreKit behavior in the cases.
@MainActor
enum NativeUnitTestHost {
    static let explicit = ProcessInfo.processInfo.environment["REDACT_NATIVE_UNIT_TEST_HOST"] == "1"
    private static var sequence = 0
    private static var roots = 0
    private static var stores = 0
    private static var firstSession: Bool?

    static func isInert() -> Bool {
        let detected = NSClassFromString("XCTestCase") != nil
        emit("host.classification", detected: detected)
        return explicit || detected
    }

    static func recordRootConstruction() { roots += 1; emit("root.constructed") }
    static func recordStoreConstruction() { stores += 1; emit("store.constructed") }

    static func firstSessionIsInert() -> Bool {
        if firstSession == nil {
            firstSession = explicit && roots == 0 && stores == 0
            emit("first.session")
        }
        return firstSession == true
    }

    private static func emit(_ event: StaticString, detected: Bool = NSClassFromString("XCTestCase") != nil) {
        guard explicit && sequence < 32 else { return }
        sequence += 1
        let value: [String: Any] = ["event": String(describing: event), "sequence": sequence,
            "explicitUnitHost": explicit, "xctestLoaded": detected, "rootConstructions": roots,
            "storeConstructions": stores, "firstSessionInert": firstSession.map { $0 as Any } ?? NSNull()]
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else { return }
        var line = Data("NATIVE_STOREKIT_HOST ".utf8); line.append(data); line.append(10)
        guard line.count <= 512 else { return }
        _ = line.withUnsafeBytes { fwrite($0.baseAddress, 1, $0.count, stdout) }
        _ = fflush(stdout)
    }
}
#endif
