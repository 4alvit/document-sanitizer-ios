import SwiftUI
import SanitizerCore

struct ReviewView: View {
    @EnvironmentObject private var workspace: Workspace
    @Environment(\.dismiss) private var dismiss
    let packet: ReviewPacket
    @State private var pageIndex = 0
    @State private var checked = Set<UUID>()
    @State private var format: ExportFormat = .pdf

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Label(L10n.text("Check what you are about to share"), systemImage: "checkmark.shield").font(.title2.bold())
                    Text(L10n.text("These are the pixels used for export. Zoom in and check every page, including any private details the text search missed."))
                        .foregroundStyle(.secondary)
                    let page = packet.pages[pageIndex]
                    HStack {
                        Button { pageIndex -= 1 } label: { Image(systemName: "chevron.left") }
                            .disabled(pageIndex == 0).accessibilityLabel(L10n.text("Previous page"))
                        Spacer()
                        Text(L10n.format("Page %@ of %@", L10n.number(pageIndex + 1), L10n.number(packet.pages.count))).font(.headline)
                        Spacer()
                        Button { pageIndex += 1 } label: { Image(systemName: "chevron.right") }
                            .disabled(pageIndex + 1 == packet.pages.count).accessibilityLabel(L10n.text("Next page"))
                    }
                    ZoomableImage(image: page.image).frame(height: 450).background(Color(uiColor: .secondarySystemBackground))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .accessibilityIdentifier("preview-image")
                        .accessibilityLabel(L10n.format("Rasterized clean copy of page %@", L10n.number(pageIndex + 1)))
                        .accessibilityHint(L10n.text("Pinch to zoom. The exported copy does not contain selectable text."))
                    Button {
                        // Confirmation should switch to an unambiguous state,
                        // without overlapping old and new button labels.
                        var transaction = SwiftUI.Transaction(animation: nil)
                        transaction.disablesAnimations = true
                        withTransaction(transaction) {
                            checked.insert(page.id)
                            if pageIndex + 1 < packet.pages.count { pageIndex += 1 }
                        }
                    } label: {
                        Label(checked.contains(page.id) ? L10n.text("Page checked") : L10n.text("I checked this page"), systemImage: checked.contains(page.id) ? "checkmark.circle.fill" : "circle")
                            .frame(maxWidth: .infinity)
                    }.buttonStyle(.bordered).accessibilityIdentifier("confirm-page-reviewed")
                    Text(L10n.format("Pages checked: %@ / %@", L10n.number(checked.count), L10n.number(packet.pages.count))).font(.caption).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 10) {
                        Label {
                            Text(L10n.text("About these copies")).accessibilityIdentifier("review-copies-heading")
                        } icon: { Image(systemName: "info.circle") }.font(.headline)
                        Text(L10n.format("Output is rasterized, downsampled imagery (PDF pages up to %@ dpi and %@ pixels on the longest edge). Selectable text, links, forms and accessibility structure are lost. Image files are also normalized. Originals stay unchanged.", L10n.number(144), L10n.number(2400)))
                        Text(L10n.text("Your selected areas are replaced with black pixels. Visible page and annotation appearances are flattened into pixels; original interactive objects, hidden text layers, attachments and source metadata are not copied. This does not automatically detect all private information."))
                    }.font(.footnote).foregroundStyle(.secondary).padding().background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
                    Picker(L10n.text("File format"), selection: $format) {
                        ForEach(ExportFormat.allCases, id: \.rawValue) { value in Text(value.rawValue.uppercased()).tag(value) }
                    }.pickerStyle(.segmented).accessibilityIdentifier("export-format")
                    Text(format == .pdf ? L10n.text("One image-only PDF for this batch.") : L10n.format("One %@ image per page.", format.rawValue.uppercased()))
                        .font(.caption).foregroundStyle(.secondary)
                    Button { workspace.export(packet, format: format) } label: {
                        Label(L10n.text("Export clean copies"), systemImage: "square.and.arrow.up").font(.headline).frame(maxWidth: .infinity)
                    }.buttonStyle(.borderedProminent).disabled(checked.count != packet.pages.count || workspace.isBusy).accessibilityIdentifier("export-button")
                }.padding()
            }
            .accessibilityIdentifier("review-scroll")
            .navigationTitle(L10n.text("Final preview")).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(L10n.text("Back to editing")) { dismiss() }.disabled(workspace.isBusy).accessibilityIdentifier("back-to-editing") } }
            .interactiveDismissDisabled(workspace.isBusy)
            .overlay {
                if workspace.isBusy {
                    ZStack {
                        Color.black.opacity(0.25).ignoresSafeArea()
                        VStack(spacing: 18) {
                            ProgressView(); Text(workspace.busyLabel)
                            Button(L10n.text("Cancel export")) { workspace.cancel() }
                        }.padding(30).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
                    }
                }
            }
            .sheet(item: $workspace.exported) { export in
                ShareSheet(urls: export.urls) { workspace.cleanExport(export) }
                    .onDisappear { workspace.cleanExport(export) }
            }
            .alert(L10n.text("Export could not complete"), isPresented: Binding(get: { workspace.errorMessage != nil }, set: { if !$0 { workspace.errorMessage = nil } })) {
                Button(L10n.text("OK"), role: .cancel) { workspace.errorMessage = nil }
            } message: { Text(workspace.errorMessage ?? "") }
        }
    }
}

struct ShareSheet: UIViewControllerRepresentable {
    let urls: [URL]
    let completion: () -> Void
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: urls, applicationActivities: nil)
        controller.view.accessibilityIdentifier = "export-share-sheet"
        controller.completionWithItemsHandler = { _, _, _, _ in DispatchQueue.main.async { completion() } }
        return controller
    }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

private struct ZoomableImage: UIViewRepresentable {
    let image: CGImage
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIView(context: Context) -> UIScrollView {
        let view = UIScrollView()
        view.minimumZoomScale = 1; view.maximumZoomScale = 8
        view.delegate = context.coordinator
        view.bouncesZoom = true
        let imageView = UIImageView(); imageView.contentMode = .scaleAspectFit
        imageView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(imageView); context.coordinator.imageView = imageView
        return view
    }
    func updateUIView(_ view: UIScrollView, context: Context) {
        guard context.coordinator.currentImage !== image else { return }
        view.setZoomScale(1, animated: false)
        context.coordinator.currentImage = image
        context.coordinator.imageView?.frame = view.bounds
        context.coordinator.imageView?.image = UIImage(cgImage: image)
    }
    final class Coordinator: NSObject, UIScrollViewDelegate {
        var imageView: UIImageView?
        var currentImage: CGImage?
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }
    }
}

struct ProposalView: View {
    @EnvironmentObject private var workspace: Workspace
    @Environment(\.dismiss) private var dismiss
    @State private var selected = Set<UUID>()
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(L10n.text("Choose the recognized lines to cover. An entire matching line will be hidden, not just your search phrase. OCR may miss or misread text; check the final preview."))
                }
                Section(L10n.count("count.suggestedLines", workspace.proposals.count)) {
                    ForEach(workspace.proposals) { proposal in
                        Button {
                            if selected.contains(proposal.id) { selected.remove(proposal.id) } else { selected.insert(proposal.id) }
                        } label: {
                            HStack {
                                Image(systemName: selected.contains(proposal.id) ? "checkmark.circle.fill" : "circle")
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(proposal.match.text).foregroundStyle(.primary)
                                    Text(L10n.format("Page %@", L10n.number(proposal.pageNumber))).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }.accessibilityAddTraits(selected.contains(proposal.id) ? [.isSelected] : [])
                    }
                }
            }.navigationTitle(L10n.text("Confirm text matches")).navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button(L10n.text("Cancel")) { workspace.proposals = []; dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button(L10n.count("count.hideLines", selected.count)) { workspace.acceptProposals(selected); dismiss() }.disabled(selected.isEmpty) }
                }
        }
    }
}
