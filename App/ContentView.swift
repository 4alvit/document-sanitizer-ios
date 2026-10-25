import SwiftUI
import UniformTypeIdentifiers
import SanitizerCore

struct ContentView: View {
    @EnvironmentObject private var workspace: Workspace
    @EnvironmentObject private var store: ProStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var showingImporter = false
    @State private var showingPro = false
    @State private var showingMaskEditor = false
    @State private var showingClear = false
    @State private var showingClearQueue = false
    @State private var showingInformation = false
    @State private var showingPresets = false
    @State private var query = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if workspace.sharedBatchCount > 0 { sharedQueue }
                    if workspace.pages.isEmpty { emptyState } else { editor }
                }
                .padding()
                .frame(maxWidth: 900)
                .frame(maxWidth: .infinity)
            }
            .accessibilityIdentifier("workspace-scroll")
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle(L10n.text("RedactLeaf"))
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showingPro = true } label: { Label(store.isPro ? L10n.text("Pro") : L10n.text("Unlock Pro"), systemImage: "sparkles") }
                        .accessibilityIdentifier("open-pro")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(L10n.text("Import PDF or images"), systemImage: "doc.badge.plus") { showingImporter = true }
                        Button(L10n.text("Saved areas"), systemImage: "square.stack") { showingPresets = true }.accessibilityIdentifier("saved-areas-menu")
                        Button(L10n.text("Clear workspace"), systemImage: "trash", role: .destructive) { showingClear = true }.accessibilityIdentifier("clear-workspace-menu")
                        Button(L10n.text("Privacy and support"), systemImage: "info.circle") { showingInformation = true }
                            .accessibilityIdentifier("privacy-support-menu")
                    } label: { Image(systemName: "ellipsis.circle") }.accessibilityLabel(L10n.text("Workspace actions")).accessibilityIdentifier("workspace-actions")
                    .disabled(workspace.isBusy)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if !workspace.pages.isEmpty {
                    Button { workspace.prepareReview() } label: {
                        Label(L10n.text("Review clean copies"), systemImage: "checkmark.shield")
                            .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 5)
                    }
                    .buttonStyle(.borderedProminent).disabled(workspace.isBusy)
                    .accessibilityIdentifier("review-button")
                    .padding().background(.regularMaterial)
                }
            }
            .overlay { if workspace.isBusy { busyOverlay } }
            .fileImporter(isPresented: $showingImporter, allowedContentTypes: [.pdf, .image], allowsMultipleSelection: true) { result in
                switch result {
                case .success(let urls): workspace.importURLs(urls, currentIsPro: { store.isPro })
                case .failure(let error):
                    if (error as NSError).code != NSUserCancelledError { workspace.errorMessage = L10n.text("Files could not be opened. Try choosing them again.") }
                }
            }
            .sheet(isPresented: $showingPro) { ProView().modifier(UITestContentSize()) }
            .sheet(isPresented: $showingInformation) { InformationView().modifier(UITestContentSize()) }
            .sheet(isPresented: $showingPresets, onDismiss: { workspace.cancelPresetApplication() }) {
                PresetLibraryView().modifier(UITestContentSize())
            }
            .sheet(isPresented: $showingMaskEditor) {
                if let page = workspace.selectedPage {
                    ManualMaskView { workspace.addMask($0, pageID: page.id) }.modifier(UITestContentSize())
                }
            }
            .sheet(item: $workspace.review) { packet in ReviewView(packet: packet).modifier(UITestContentSize()) }
            .sheet(isPresented: Binding(get: { !workspace.proposals.isEmpty }, set: { if !$0 { workspace.proposals = [] } })) { ProposalView().modifier(UITestContentSize()) }
            .alert(L10n.text("RedactLeaf"), isPresented: Binding(get: { !showingPresets && workspace.errorMessage != nil }, set: { if !$0 && !showingPresets { workspace.errorMessage = nil } })) {
                Button(L10n.text("OK"), role: .cancel) { workspace.errorMessage = nil }
            } message: { Text(workspace.errorMessage ?? "") }
            .confirmationDialog(L10n.text("Clear this workspace?"), isPresented: $showingClear, titleVisibility: .visible) {
                Button(L10n.text("Clear workspace"), role: .destructive) { workspace.clear() }.accessibilityIdentifier("confirm-clear-workspace")
                Button(L10n.text("Cancel"), role: .cancel) {}
            } message: { Text(L10n.text("Unexported edits and temporary copies will be removed. Original files and queued shared batches are unchanged.")) }
            .confirmationDialog(L10n.text("Remove all queued shared files?"), isPresented: $showingClearQueue, titleVisibility: .visible) {
                Button(L10n.text("Clear queued files"), role: .destructive) { workspace.clearShared() }
                Button(L10n.text("Cancel"), role: .cancel) {}
            } message: { Text(L10n.text("Only the temporary queue is removed. Original files and current edits are unchanged.")) }
        }
    }

    private var sharedQueue: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(L10n.text("Shared files"), systemImage: "tray.and.arrow.down").font(.headline)
            Text(L10n.format("Import one batch at a time. Copies older than %@ hours are removed when the main app next checks the queue.", L10n.number(24))).font(.caption).foregroundStyle(.secondary)
            ForEach(workspace.sharedBatches) { batch in
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.count("count.files", batch.filenames.count)).font(.subheadline.bold())
                    Text(batch.filenames.joined(separator: ", ")).font(.caption).lineLimit(2).foregroundStyle(.secondary)
                    if dynamicTypeSize.isAccessibilitySize {
                        VStack(spacing: 12) {
                            Button { workspace.importShared(batch, currentIsPro: { store.isPro }) } label: {
                                Text(L10n.text("Import this batch")).frame(maxWidth: .infinity)
                                    .fixedSize(horizontal: false, vertical: true)
                            }.buttonStyle(.borderedProminent)
                            Button(role: .destructive) { workspace.discardShared(batch) } label: {
                                Text(L10n.text("Discard")).frame(maxWidth: .infinity)
                                    .fixedSize(horizontal: false, vertical: true)
                            }.buttonStyle(.bordered)
                        }
                    } else {
                        HStack {
                            Button(L10n.text("Import this batch")) { workspace.importShared(batch, currentIsPro: { store.isPro }) }.buttonStyle(.borderedProminent)
                            Spacer()
                            Button(L10n.text("Discard"), role: .destructive) { workspace.discardShared(batch) }.buttonStyle(.bordered)
                        }
                    }
                }.padding(12).background(.background, in: RoundedRectangle(cornerRadius: 12))
            }
            Button(L10n.text("Clear all queued files"), role: .destructive) { showingClearQueue = true }.font(.caption)
        }.padding().background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 16)).disabled(workspace.isBusy)
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 24) {
            Image(systemName: "doc.text.magnifyingglass").font(.system(size: 56, weight: .light)).foregroundStyle(.tint).padding(.top, 20)
            Text(L10n.text("Send the document.\nKeep the private parts."))
                .font(.largeTitle.bold()).fixedSize(horizontal: false, vertical: true)
            Text(L10n.text("Hide selected details across PDFs and images, check every page, then share fresh copies."))
                .font(.title3).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 16) {
                feature(L10n.number(1), L10n.text("Import"), L10n.text("Your original files stay unchanged."))
                feature(L10n.number(2), L10n.text("Choose what to hide"), L10n.text("Mark areas or confirm text matches."))
                feature(L10n.number(3), L10n.text("Review & share"), L10n.text("Export new image-only copies."))
            }.padding().background(.background, in: RoundedRectangle(cornerRadius: 20))
            Button { showingImporter = true } label: {
                Label(L10n.text("Choose PDF or images"), systemImage: "plus").frame(maxWidth: .infinity).padding(.vertical, 7)
            }.buttonStyle(.borderedProminent)
            Button(L10n.text("Try a synthetic sample")) { workspace.loadDemo() }.frame(maxWidth: .infinity).accessibilityIdentifier("sample-button")
            Text(L10n.format("Local processing. No account. This temporary workspace is cleared when the app restarts; export before you leave. Free supports up to %@ pages per workspace.", L10n.number(3)))
                .font(.footnote).foregroundStyle(.secondary)
            Text(L10n.text("Text recognition can miss private information. You choose and check every hidden area."))
                .font(.footnote).foregroundStyle(.secondary)
        }
    }

    private func feature(_ number: String, _ title: String, _ detail: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Text(number).font(.headline).frame(width: 30, height: 30).background(Color.accentColor.opacity(0.12), in: Circle())
            VStack(alignment: .leading, spacing: 3) { Text(title).font(.headline); Text(detail).foregroundStyle(.secondary) }
        }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(L10n.format("%@ · %@", L10n.count("count.pages", workspace.pages.count), L10n.count("count.hiddenAreas", workspace.redactionCount))).font(.headline).accessibilityIdentifier("workspace-status")
                    Text(workspace.isSynthetic ? L10n.text("Synthetic sample · no real personal data") : L10n.text("Temporary workspace · export to keep your edits"))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { showingImporter = true } label: { Image(systemName: "plus.circle.fill").font(.title2) }
                    .accessibilityLabel(L10n.text("Add PDF or images")).disabled(workspace.isBusy)
            }
            ScrollView(.horizontal) {
                HStack(spacing: 12) {
                    ForEach(Array(workspace.pages.enumerated()), id: \.element.id) { index, page in
                        Button { workspace.selectedPageID = page.id } label: {
                            VStack(spacing: 6) {
                                Image(decorative: page.image, scale: 1).resizable().scaledToFit().frame(width: 65, height: 80)
                                    .padding(5).background(.white)
                                    .overlay(RoundedRectangle(cornerRadius: 6).stroke(workspace.selectedPage?.id == page.id ? Color.accentColor : .clear, lineWidth: 3))
                                Text(L10n.format("Page %@", L10n.number(index + 1))).font(.caption)
                            }
                        }.buttonStyle(.plain).accessibilityLabel(L10n.format("Page %@, %@", L10n.number(index + 1), L10n.count("count.hiddenAreas", page.redactions.count)))
                        .accessibilityAddTraits(workspace.selectedPage?.id == page.id ? [.isSelected] : [])
                    }
                }.padding(4)
            }
            if let page = workspace.selectedPage {
                HStack {
                    Text(page.sourceName).font(.subheadline).lineLimit(2)
                    Spacer()
                    Button(L10n.text("Remove page"), role: .destructive) { workspace.removePage(page.id) }.font(.caption)
                }
                Text(L10n.text("Drag over details to hide. Red marks become solid black in your clean copies."))
                    .font(.subheadline).foregroundStyle(.secondary)
                PageCanvas(page: page) { workspace.addMask($0, pageID: page.id) }
                    .frame(height: 420).background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityIdentifier("document-canvas")
                Button(L10n.text("Add area with accessible controls"), systemImage: "slider.horizontal.3") { showingMaskEditor = true }.font(.subheadline).accessibilityIdentifier("accessible-mask-button")
                Button(L10n.text("Saved areas"), systemImage: "square.stack") { showingPresets = true }
                    .font(.subheadline).disabled(workspace.isBusy).accessibilityIdentifier("saved-areas-button")
                if !page.redactions.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(page.redactions.enumerated()), id: \.element.id) { index, mask in
                            HStack {
                                Text(L10n.format("Area %@", L10n.number(index + 1)))
                                Spacer()
                                Button(L10n.text("Remove"), role: .destructive) { workspace.removeMask(mask.id, pageID: page.id) }
                                    .accessibilityLabel(L10n.format("Remove hidden area %@", L10n.number(index + 1)))
                            }
                        }
                    }.padding().background(.background, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            VStack(alignment: .leading, spacing: 10) {
                Label(L10n.text("Find text in the whole batch"), systemImage: "text.magnifyingglass").font(.headline)
                TextField(L10n.text("Name, email or phrase"), text: $query).textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled().textInputAutocapitalization(.never)
                    .submitLabel(.search).onSubmit { workspace.search(query) }
                Button(L10n.text("Find matching lines")) { workspace.search(query) }
                    .buttonStyle(.bordered).disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || workspace.isBusy)
                Text(L10n.text("Suggestions cover a whole recognized line. Nothing is hidden until you confirm. OCR does not find all private information."))
                    .font(.caption).foregroundStyle(.secondary)
            }.padding().background(.background, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    private var busyOverlay: some View {
        ZStack {
            Color.black.opacity(0.25).ignoresSafeArea()
            VStack(spacing: 18) {
                ProgressView()
                Text(workspace.busyLabel).font(.headline).multilineTextAlignment(.center)
                Button(L10n.text("Cancel operation")) { workspace.cancel() }.buttonStyle(.bordered)
            }.padding(30).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20)).padding(24)
        }.accessibilityAddTraits(.isModal)
    }
}

private struct PageCanvas: View {
    let page: RasterPage
    let onMask: (NormalizedRect) -> Void
    @State private var dragStart: CGPoint?
    @State private var dragEnd: CGPoint?

    var body: some View {
        GeometryReader { geometry in
            let frame = MaskGeometry.fittedFrame(imageSize: CGSize(width: page.image.width, height: page.image.height), in: geometry.size)
            ZStack(alignment: .topLeading) {
                Image(decorative: page.image, scale: 1).resizable()
                    .frame(width: frame.width, height: frame.height).position(x: frame.midX, y: frame.midY)
                ForEach(page.redactions) { mask in
                    Rectangle().fill(Color.red.opacity(0.65))
                        .frame(width: mask.rect.width * frame.width, height: mask.rect.height * frame.height)
                        .position(x: frame.minX + (mask.rect.x + mask.rect.width / 2) * frame.width,
                                  y: frame.minY + (mask.rect.y + mask.rect.height / 2) * frame.height)
                }
                if let start = dragStart, let end = dragEnd {
                    let rect = CGRect(x: min(start.x, end.x), y: min(start.y, end.y), width: abs(end.x - start.x), height: abs(end.y - start.y))
                    Rectangle().fill(Color.red.opacity(0.45)).overlay(Rectangle().stroke(.red, lineWidth: 2))
                        .frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY)
                }
                Color.clear.contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 2)
                        .onChanged { value in
                            guard frame.contains(value.startLocation) else { return }
                            dragStart = clamp(value.startLocation, frame)
                            dragEnd = clamp(value.location, frame)
                        }
                        .onEnded { _ in
                            defer { dragStart = nil; dragEnd = nil }
                            guard let start = dragStart, let end = dragEnd,
                                  let rect = MaskGeometry.normalizedRect(start: start, end: end, in: frame) else { return }
                            onMask(rect)
                        })
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(L10n.format("Document page with %@", L10n.count("count.hiddenAreas", page.redactions.count)))
            .accessibilityHint(L10n.text("Use Add area with accessible controls below this page to position a hidden area."))
        }.onChange(of: page.id) { _, _ in dragStart = nil; dragEnd = nil }
    }

    private func clamp(_ point: CGPoint, _ frame: CGRect) -> CGPoint {
        CGPoint(x: min(max(point.x, frame.minX), frame.maxX), y: min(max(point.y, frame.minY), frame.maxY))
    }
}

private struct ManualMaskView: View {
    @Environment(\.dismiss) private var dismiss
    let add: (NormalizedRect) -> Void
    @State private var x = 0.1
    @State private var y = 0.1
    @State private var width = 0.5
    @State private var height = 0.08

    var body: some View {
        NavigationStack {
            Form {
                Section(L10n.text("Position from top-left of page")) {
                    control("Left", value: $x, range: 0...0.99)
                    control("Top", value: $y, range: 0...0.99)
                    control("Width", value: $width, range: 0.01...1)
                    control("Height", value: $height, range: 0.01...1)
                }
                Section { Text(L10n.text("Areas are clipped at the page edge. Review the resulting clean copy before export.")) }
                Button(L10n.text("Add hidden area")) {
                    add(NormalizedRect(x: x, y: y, width: min(width, 1 - x), height: min(height, 1 - y))); dismiss()
                }.accessibilityIdentifier("add-mask-button")
            }.navigationTitle(L10n.text("Hidden area")).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button(L10n.text("Cancel")) { dismiss() } } }
        }
    }
    private func control(_ label: String, value: Binding<Double>, range: ClosedRange<Double>) -> some View {
        VStack(alignment: .leading) {
            Text(L10n.format("%@: %@", L10n.text(label), L10n.percent(value.wrappedValue)))
                .accessibilityIdentifier("mask-\(label.lowercased())-value")
            Slider(value: value, in: range, step: 0.01).accessibilityLabel(L10n.text(label)).accessibilityValue(L10n.percent(value.wrappedValue))
        }
    }
}
