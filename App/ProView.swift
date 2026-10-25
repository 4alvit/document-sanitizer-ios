import SwiftUI

struct ProView: View {
    @EnvironmentObject private var store: ProStore
    @Environment(\.dismiss) private var dismiss
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
                    Link(L10n.text("Privacy policy"), destination: URL(string: "https://github.com/4alvit/document-sanitizer-ios/blob/main/docs/PRIVACY.md")!)
                    Link(L10n.text("Support"), destination: URL(string: "https://github.com/4alvit/document-sanitizer-ios/issues")!)
                }.padding(24)
            }.navigationTitle(L10n.text("RedactLeaf Pro")).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(L10n.text("Done")) { dismiss() } } }
        }
    }
}

struct InformationView: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                Section(L10n.text("Your files")) {
                    Text(L10n.text("RedactLeaf processes imported documents locally. It has no document server, analytics service, mandatory account or cloud sync."))
                    Text(L10n.text("Original files stay unchanged. Imported working pages live in memory. Restarting the app clears the workspace. Temporary export files are removed after sharing or when the app next starts."))
                    Text(L10n.format("Share Sheet copies are stored in a protected local queue excluded from backups. Each batch is removed after successful import or when you discard it. Copies older than %@ hours are removed when the main app next checks the queue.", L10n.number(24)))
                }
                Section(L10n.text("Check before sharing")) {
                    Text(L10n.text("Text recognition only suggests areas to hide. It can miss text, handwriting, faces, signatures and other private content. Add manual areas and check every page in the final preview."))
                    Text(L10n.text("Export creates image-only copies. Visible page and annotation appearances are flattened into pixels. Original interactive objects, hidden text layers, attachments and source metadata are not copied. Selectable text and accessibility structure are lost; image resolution may be reduced."))
                    Text(L10n.text("Export files use neutral filenames without the source filename. Check every page before sharing."))
                }
                Section(L10n.text("Saved areas")) {
                    Text(L10n.text("Area presets keep the name you enter and relative rectangle positions on this device across app restarts. Their protected local library is excluded from backups. Presets contain no document images, thumbnails, recognized text or source filenames."))
                    Text(L10n.text("Choose a generic preset name without private document details. Delete individual presets or reset the library in Saved areas. Clearing the temporary workspace does not delete presets; deleting a preset does not remove areas already applied to a page."))
                    Text(L10n.text("Presets apply to the selected page only. A different layout, rotation or aspect ratio can place areas over different content. Preview the placement and check every page in the final preview; presets do not recognize documents or align fields automatically."))
                }
                Section(L10n.text("More information")) {
                    Link(L10n.text("Privacy policy"), destination: URL(string: "https://github.com/4alvit/document-sanitizer-ios/blob/main/docs/PRIVACY.md")!)
                    Link(L10n.text("Support and issue tracker"), destination: URL(string: "https://github.com/4alvit/document-sanitizer-ios/issues")!)
                    Text(L10n.text("Do not attach private documents to public support issues. Use a synthetic example.")).font(.footnote).foregroundStyle(.secondary)
                }
            }.navigationTitle(L10n.text("Privacy and support")).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(L10n.text("Done")) { dismiss() } } }
        }
    }
}
