import SwiftUI

struct ProView: View {
    @EnvironmentObject private var store: ProStore
    @Environment(\.dismiss) private var dismiss
    @State private var showingInformation = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    Image(systemName: "square.stack.3d.up.fill").font(.system(size: 48)).foregroundStyle(.tint)
                    Text(store.isPro ? L10n.text("RedactLeaf Pro is unlocked") : L10n.text("More pages. One purchase.")).font(.largeTitle.bold())
                    Text(L10n.format("Prepare larger batches with RedactLeaf Pro. A one-time purchase unlocks up to %@ pages per workspace, subject to the memory safety limit, and lets you save reusable area presets.", L10n.number(30)))
                        .font(.title3).foregroundStyle(.secondary)
                    Label(L10n.text("Save named areas for documents with a similar layout"), systemImage: "square.stack")
                    Text(L10n.text("Presets save relative positions. Preview their placement on each page before applying, then check every page before export. Existing presets remain available to apply or delete if Pro becomes unavailable."))
                        .font(.subheadline).foregroundStyle(.secondary)
                    Label(L10n.text("All processing stays on your device"), systemImage: "iphone")
                    Label(L10n.text("No subscription or required account"), systemImage: "checkmark.seal")
                    Label(L10n.text("Restore on devices using your Apple Account"), systemImage: "arrow.clockwise")
                    Text(L10n.format("Free includes complete editing, text search, preview and export for up to %@ pages. Existing workspace content always remains viewable and exportable, even if Pro becomes unavailable.", L10n.number(3)))
                        .font(.subheadline).foregroundStyle(.secondary)
                    if !store.isPro {
                        Button { Task { await store.purchase() } } label: {
                            Text(store.displayPrice.map { L10n.format("Unlock Pro · %@", $0) } ?? L10n.text("Purchase unavailable"))
                                .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 5)
                        }.buttonStyle(.borderedProminent).disabled(store.isBusy || store.displayPrice == nil)
                        if store.displayPrice == nil {
                            Text(L10n.text("The App Store price could not be loaded. Check your connection and try again. Editing and export remain available."))
                                .font(.footnote).foregroundStyle(.secondary)
                            Button(L10n.text("Reload App Store price")) { Task { await store.load() } }.disabled(store.isBusy)
                        }
                    }
                    Button(L10n.text("Restore purchases")) { Task { await store.restore() } }.disabled(store.isBusy)
                    if store.isBusy { ProgressView(L10n.text("Contacting the App Store…")) }
                    if let message = store.message { Text(message).font(.callout).accessibilityLabel(message) }
                    Text(L10n.text("Purchases are handled by Apple. RedactLeaf receives entitlement information, never your payment details."))
                        .font(.footnote).foregroundStyle(.secondary)
                    Button { showingInformation = true } label: {
                        Text(L10n.text("Privacy and support"))
                            .fixedSize(horizontal: false, vertical: true)
                    }.accessibilityIdentifier("pro-privacy-support")
                }.padding(24)
            }.accessibilityIdentifier("pro-scroll")
                .navigationTitle(L10n.text("RedactLeaf Pro")).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(L10n.text("Done")) { dismiss() } } }
        }
        .sheet(isPresented: $showingInformation) { InformationView().modifier(UITestContentSize()) }
    }
}

struct InformationView: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                ForEach(PrivacySupportContent.sections) { section in
                    Section {
                        ForEach(Array(section.paragraphKeys.enumerated()), id: \.offset) { paragraph in
                            Text(L10n.text(paragraph.element))
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("privacy-text-\(section.id)-\(paragraph.offset)")
                        }
                    } header: {
                        Text(L10n.text(section.titleKey)).accessibilityAddTraits(.isHeader)
                    }
                }
                Section(L10n.text("privacy.online.title")) {
                    Text(L10n.text("privacy.online.preview"))
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("privacy-preview-notice")
                    externalLink("privacy.online.policy", to: PrivacySupportContent.privacyPolicyURL, id: "privacy-policy-link")
                    externalLink("privacy.online.guide", to: PrivacySupportContent.supportGuideURL, id: "support-guide-link")
                    externalLink("privacy.online.issues", to: PrivacySupportContent.issuesURL, id: "public-issues-link")
                }
            }.accessibilityIdentifier("privacy-support-list")
                .navigationTitle(L10n.text("Privacy and support")).navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(L10n.text("Done")) { dismiss() }.accessibilityIdentifier("close-privacy-support")
                    }
                }
        }
    }

    private func externalLink(_ key: String, to destination: URL, id: String) -> some View {
        Link(destination: destination) {
            Text(L10n.text(key)).fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier(id)
        .accessibilityHint(L10n.text("privacy.online.hint"))
    }
}
