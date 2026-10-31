import Foundation
import CoreGraphics
import Vision

public enum TextRecognizer {
    /// Suggestions cover whole recognized lines. They are not a completeness or privacy guarantee.
    /// Callers must obtain human confirmation before turning suggestions into redactions.
    public static func matches(in image: CGImage, query: String) async throws -> [OCRMatch] {
        let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return [] }
        try Task.checkCancellation()
        let work = RecognitionWork()
        let matches: [OCRMatch] = try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .userInitiated).async {
                    do {
                        let handler = VNImageRequestHandler(cgImage: image, options: [:])
                        try handler.perform([work.request])
                        let results = (work.request.results ?? []).compactMap { observation -> OCRMatch? in
                            guard let candidate = observation.topCandidates(1).first,
                                  candidate.string.range(of: needle, options: [.caseInsensitive, .diacriticInsensitive]) != nil else {
                                return nil
                            }
                            let box = observation.boundingBox
                            // Vision's normalized origin is bottom-left. Convert exactly once.
                            let x = min(1, max(0, box.minX))
                            let top = min(1, max(0, 1 - box.maxY))
                            let right = min(1, max(x, box.maxX))
                            let bottom = min(1, max(top, 1 - box.minY))
                            guard right > x, bottom > top else { return nil }
                            return OCRMatch(text: candidate.string,
                                            rect: NormalizedRect(x: x, y: top, width: right - x, height: bottom - top))
                        }
                        continuation.resume(returning: results)
                    } catch { continuation.resume(throwing: error) }
                }
            }
        }, onCancel: {
            work.request.cancel()
        })
        try Task.checkCancellation()
        return matches
    }
}

/// Configuration happens before dispatch; only Vision's cancellation method crosses threads.
private final class RecognitionWork: @unchecked Sendable {
    let request: VNRecognizeTextRequest
    init() {
        request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        // A document can contain either script regardless of the app's UI language.
        request.automaticallyDetectsLanguage = true
        if let supported = try? request.supportedRecognitionLanguages() {
            let languages = ["en-US", "ru-RU"].filter(supported.contains)
            if !languages.isEmpty { request.recognitionLanguages = languages }
        }
    }
}
