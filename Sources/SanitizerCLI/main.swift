import Foundation
import SanitizerCore

// Development-only corpus runner. Never used by the iOS app or its extension.
let arguments = Array(CommandLine.arguments.dropFirst())
do {
    var options: [String: String] = [:]
    let known = Set(["--input", "--output", "--format", "--rect"])
    for index in stride(from: 0, to: arguments.count, by: 2) {
        guard known.contains(arguments[index]), index + 1 < arguments.count,
              options[arguments[index]] == nil else {
            throw NSError(domain: "SanitizerCLI", code: 1, userInfo: [NSLocalizedDescriptionKey: "Every option needs one value; unknown or duplicate options are rejected."])
        }
        options[arguments[index]] = arguments[index + 1]
    }
    guard let input = options["--input"], let output = options["--output"],
          let format = ExportFormat(rawValue: options["--format"] ?? "png") else {
        throw NSError(domain: "SanitizerCLI", code: 1, userInfo: [NSLocalizedDescriptionKey: "Usage: sanitizer-cli --input PATH --output DIRECTORY --format png|jpeg|pdf [--rect x,y,width,height]"])
    }
    var pages = try RasterImporter.load(url: URL(fileURLWithPath: input))
    if let value = options["--rect"] {
        let components = value.split(separator: ",", omittingEmptySubsequences: false)
        let numbers = components.compactMap { Double($0) }
        guard components.count == 4, numbers.count == 4 else { throw NSError(domain: "SanitizerCLI", code: 2, userInfo: [NSLocalizedDescriptionKey: "Rectangle needs exactly four numbers."]) }
        let rect = NormalizedRect(x: numbers[0], y: numbers[1], width: numbers[2], height: numbers[3])
        for index in pages.indices { pages[index].redactions = [Redaction(rect: rect)] }
    }
    let outputDirectory = URL(fileURLWithPath: output, isDirectory: true)
    try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
    let paths = try RasterExporter.export(pages: pages, format: format, to: outputDirectory)
    let result: [String: Any] = ["files": paths.map(\.path), "pages": pages.map { ["width": $0.image.width, "height": $0.image.height] }]
    let encoded = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(encoded)
    FileHandle.standardOutput.write(Data([10]))
} catch {
    // Local development CLI only: an error description is useful to corpus authors.
    FileHandle.standardError.write(Data("sanitizer-cli: \(error.localizedDescription)\n".utf8))
    exit(1)
}

