import SwiftUI
import SanitizerCore

struct PresetLibraryView: View {
    @EnvironmentObject private var workspace: Workspace
    @EnvironmentObject private var library: MaskPresetStore
    @Environment(\.dismiss) private var dismiss
    @State private var showingCreate = false
    @State private var creationPageID: UUID?
    @State private var deleting: MaskPreset?
    @State private var showingReset = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Group {
                if let preview = workspace.presetPreview {
                    PresetPlacementView(preview: preview) {
                        if workspace.commitPresetApplication(preview) { dismiss() }
                    }
                } else {
                    libraryContents
                }
            }
            .navigationTitle(workspace.presetPreview == nil ? L10n.text("Saved areas") : L10n.text("Check placement"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if showingCreate {
                        EmptyView()
                    } else if workspace.presetPreview != nil {
                        Button(L10n.text("Cancel")) { workspace.cancelPresetApplication() }
                            .accessibilityIdentifier("cancel-preset-preview")
                    } else {
                        Button(L10n.text("Done")) { dismiss() }.disabled(workspace.isBusy)
                            .accessibilityIdentifier("close-saved-areas")
                    }
                }
            }
            .navigationDestination(isPresented: $showingCreate) {
                if let pageID = creationPageID { SavePresetView(pageID: pageID) }
            }
            .interactiveDismissDisabled(workspace.isBusy)
            .overlay {
                if workspace.isBusy {
                    ZStack {
                        Color.black.opacity(0.2).ignoresSafeArea()
                        VStack(spacing: 18) {
                            ProgressView()
                            Text(L10n.text("Preparing placement preview…")).multilineTextAlignment(.center)
                            Button(L10n.text("Cancel preview")) { workspace.cancelPresetApplication() }
                                .buttonStyle(.bordered).accessibilityIdentifier("cancel-preset-render")
                        }.padding(24).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18)).padding()
                    }.accessibilityAddTraits(.isModal)
                }
            }
            .alert(L10n.text("Saved areas"), isPresented: Binding(get: {
                errorMessage != nil || workspace.errorMessage != nil
            }, set: { if !$0 { errorMessage = nil; workspace.errorMessage = nil } })) {
                Button(L10n.text("OK"), role: .cancel) { errorMessage = nil; workspace.errorMessage = nil }
            } message: { Text(errorMessage ?? workspace.errorMessage ?? "") }
            .confirmationDialog(L10n.text("Delete this preset?"), isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
                Button(L10n.text("Delete preset"), role: .destructive) {
                    guard let preset = deleting else { return }
                    do { try library.delete(id: preset.id) } catch { errorMessage = error.localizedDescription }
                    deleting = nil
                }.accessibilityIdentifier("confirm-delete-preset")
                Button(L10n.text("Cancel"), role: .cancel) { deleting = nil }
            } message: { Text(L10n.text("The saved preset will be removed. Areas already applied to your pages stay unchanged.")) }
            .confirmationDialog(L10n.text("Reset the saved-area library?"), isPresented: $showingReset, titleVisibility: .visible) {
                Button(L10n.text("Delete all presets"), role: .destructive) {
                    do { try library.reset() } catch { errorMessage = error.localizedDescription }
                }.accessibilityIdentifier("confirm-reset-presets")
                Button(L10n.text("Cancel"), role: .cancel) {}
            } message: { Text(L10n.text("All saved presets on this device will be deleted. Current documents and their applied areas stay unchanged. This cannot be undone.")) }
        }
    }

    private var libraryContents: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Text(L10n.text("Reuse areas, then check their placement")).font(.title2.bold())
                Text(L10n.text("Presets keep a name and relative rectangle positions on this device. They stay saved when the temporary workspace is cleared."))
                    .foregroundStyle(.secondary)
                if let loadError = library.loadError {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(L10n.text("Library unavailable"), systemImage: "exclamationmark.triangle").font(.headline)
                        Text(loadError)
                        Button(L10n.text("Retry loading presets")) { library.reload() }
                            .accessibilityIdentifier("reload-presets")
                    }.padding().background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
                }
                Button {
                    creationPageID = workspace.selectedPage?.id
                    showingCreate = creationPageID != nil
                } label: {
                    Label(L10n.text("Save current page areas"), systemImage: "plus.square.on.square")
                        .frame(maxWidth: .infinity).fixedSize(horizontal: false, vertical: true)
                }.buttonStyle(.bordered)
                    .disabled(workspace.selectedPage?.redactions.isEmpty != false || library.loadError != nil || workspace.isBusy)
                    .accessibilityIdentifier("create-preset-button")
                Text(L10n.text("Creating a preset requires Pro and at least one hidden area on the selected page. Applying and deleting existing presets remain available without Pro."))
                    .font(.footnote).foregroundStyle(.secondary)
                if let page = workspace.selectedPage, let index = workspace.pages.firstIndex(where: { $0.id == page.id }) {
                    Text(L10n.format("Apply to page %@ only", L10n.number(index + 1))).font(.headline).accessibilityIdentifier("preset-target-page")
                    Text(L10n.text("A different layout or aspect ratio can put these areas over different content. You will see the actual page before applying."))
                        .font(.subheadline).foregroundStyle(.secondary)
                } else {
                    Text(L10n.text("Open a document to preview a preset on its selected page.")).foregroundStyle(.secondary)
                }
                if library.presets.isEmpty && library.loadError == nil {
                    Text(L10n.text("No saved presets yet")).foregroundStyle(.secondary).accessibilityIdentifier("empty-preset-library")
                }
                ForEach(library.presets) { preset in
                    VStack(alignment: .leading, spacing: 12) {
                        Text(preset.name).font(.headline).fixedSize(horizontal: false, vertical: true)
                        Text(L10n.count("count.savedAreas", preset.rectangles.count))
                            .font(.caption).foregroundStyle(.secondary)
                        Button {
                            guard let pageID = workspace.selectedPage?.id else { return }
                            workspace.preparePresetApplication(preset, pageID: pageID)
                        } label: {
                            Label(L10n.text("Preview on selected page"), systemImage: "doc.text.viewfinder")
                                .frame(maxWidth: .infinity).fixedSize(horizontal: false, vertical: true)
                        }.buttonStyle(.borderedProminent)
                            .disabled(workspace.selectedPage == nil || library.loadError != nil || workspace.isBusy)
                            .accessibilityIdentifier("preview-preset-\(preset.id.uuidString)")
                        Button(role: .destructive) { deleting = preset } label: {
                            Text(L10n.text("Delete preset")).frame(maxWidth: .infinity).fixedSize(horizontal: false, vertical: true)
                        }.buttonStyle(.bordered).disabled(library.loadError != nil || workspace.isBusy)
                            .accessibilityIdentifier("delete-preset-\(preset.id.uuidString)")
                    }.padding().background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
                }
                if library.loadError != nil || !library.presets.isEmpty {
                    Button(L10n.text("Reset saved-area library"), role: .destructive) { showingReset = true }
                        .disabled(workspace.isBusy).accessibilityIdentifier("reset-presets")
                }
            }.padding().frame(maxWidth: 700).frame(maxWidth: .infinity)
        }.accessibilityIdentifier("preset-library-scroll")
    }
}

private struct SavePresetView: View {
    @EnvironmentObject private var workspace: Workspace
    @EnvironmentObject private var store: ProStore
    @EnvironmentObject private var library: MaskPresetStore
    @Environment(\.dismiss) private var dismiss
    let pageID: UUID
    @State private var name = ""
    @State private var errorMessage: String?
    @State private var showingPro = false
    @FocusState private var nameFocused: Bool

    private var page: RasterPage? { workspace.pages.first { $0.id == pageID } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(L10n.text("Name these areas")).font(.title2.bold())
                Text(L10n.text("Use a generic name without private document details. Only this name and the relative positions of the current page's areas are saved."))
                    .foregroundStyle(.secondary)
                TextField(L10n.text("Preset name"), text: $name).textFieldStyle(.roundedBorder)
                    .accessibilityLabel(L10n.text("Preset name")).accessibilityIdentifier("preset-name")
                    .autocorrectionDisabled().submitLabel(.done).focused($nameFocused)
                    .onSubmit { nameFocused = false }
                if let page {
                    Text(L10n.count("count.pageAreas", page.redactions.count))
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if !store.isPro {
                    Text(L10n.text("Creating presets requires Pro. You can still use or delete your existing presets."))
                        .accessibilityIdentifier("preset-requires-pro")
                    Button(L10n.text("See RedactLeaf Pro")) { showingPro = true }
                        .buttonStyle(.bordered).accessibilityIdentifier("preset-pro-button")
                }
                Button {
                    guard let page else { errorMessage = L10n.text("This page is no longer in the workspace."); return }
                    do {
                        try library.create(name: name, rectangles: page.redactions.map(\.rect), currentIsPro: { store.isPro })
                        dismiss()
                    } catch { errorMessage = error.localizedDescription }
                } label: {
                    Text(L10n.text("Save preset")).font(.headline).frame(maxWidth: .infinity)
                        .fixedSize(horizontal: false, vertical: true)
                }.buttonStyle(.borderedProminent)
                    .disabled(!store.isPro || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || page?.redactions.isEmpty != false || library.loadError != nil)
                    .accessibilityIdentifier("save-preset-button")
                if let errorMessage { Text(errorMessage).foregroundStyle(.red).accessibilityIdentifier("save-preset-error") }
            }.padding().frame(maxWidth: 700).frame(maxWidth: .infinity)
        }.accessibilityIdentifier("save-preset-scroll")
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(L10n.text("Save preset")).navigationBarTitleDisplayMode(.inline)
            .navigationBarBackButtonHidden()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.text("Cancel")) { dismiss() }.accessibilityIdentifier("cancel-create-preset")
                }
            }
            .sheet(isPresented: $showingPro) { ProView().modifier(UITestContentSize()) }
    }
}

private struct PresetPlacementView: View {
    let preview: PresetApplicationPreview
    let apply: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(preview.presetName).font(.title2.bold()).fixedSize(horizontal: false, vertical: true)
                Text(L10n.format("Page %@ · %@", L10n.number(preview.targetPageNumber), L10n.count("count.newAreas", preview.addedAreaCount)))
                    .font(.headline).accessibilityIdentifier("preset-preview-summary")
                Text(L10n.text("Check the black areas on this page. Different layouts and aspect ratios can place them over different content. Pinch to inspect the preview."))
                    .foregroundStyle(.secondary)
                PresetZoomImage(image: preview.image).frame(height: 430)
                    .background(Color(uiColor: .secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .accessibilityIdentifier("preset-placement-image")
                    .accessibilityLabel(L10n.format("Proposed hidden areas on page %@", L10n.number(preview.targetPageNumber)))
                Text(preview.addedAreaCount == 0
                     ? L10n.text("All saved areas are already on this page. Applying will leave its areas unchanged.")
                     : L10n.text("Applying adds these areas to this page and keeps its existing areas. Check every page again in the final preview before export."))
                    .font(.subheadline).foregroundStyle(.secondary)
                Button(action: apply) {
                    Text(L10n.format("Apply to page %@", L10n.number(preview.targetPageNumber))).font(.headline).frame(maxWidth: .infinity)
                        .fixedSize(horizontal: false, vertical: true)
                }.buttonStyle(.borderedProminent).accessibilityIdentifier("apply-preset-button")
                Text(L10n.text("This placement preview does not mark any page as checked for export."))
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding().frame(maxWidth: 700).frame(maxWidth: .infinity)
        }.accessibilityIdentifier("preset-preview-scroll")
    }
}

private struct PresetZoomImage: UIViewRepresentable {
    let image: CGImage
    func makeUIView(context: Context) -> PresetImageScrollView { PresetImageScrollView() }
    func updateUIView(_ view: PresetImageScrollView, context: Context) { view.setImage(image) }
}

private final class PresetImageScrollView: UIScrollView, UIScrollViewDelegate {
    private let imageView = UIImageView()
    private var currentImage: CGImage?
    private var lastSize = CGSize.zero

    init() {
        super.init(frame: .zero)
        minimumZoomScale = 1; maximumZoomScale = 8; delegate = self
        imageView.contentMode = .scaleAspectFit
        addSubview(imageView)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }
    func setImage(_ image: CGImage) {
        guard currentImage !== image else { return }
        currentImage = image; imageView.image = UIImage(cgImage: image)
        setZoomScale(1, animated: false); setNeedsLayout()
    }
    override func layoutSubviews() {
        super.layoutSubviews()
        if bounds.size != lastSize {
            lastSize = bounds.size; setZoomScale(1, animated: false)
            imageView.frame = CGRect(origin: .zero, size: bounds.size)
            contentSize = bounds.size
        }
    }
    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }
}
