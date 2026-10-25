import SwiftUI

@main
struct CleanSendApp: App {
    var body: some Scene {
        WindowGroup {
            #if DEBUG
            // Hosted unit tests load XCTest in the application process. Keep
            // their host inert so SKTestSession can initialize before any
            // StoreKit listener/request, and each test owns its workspace.
            // UI tests load XCTest in a separate runner, leaving this app intact.
            if NSClassFromString("XCTestCase") != nil {
                EmptyView()
            } else {
                CleanSendRootView()
            }
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
