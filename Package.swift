// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "CleanSend",
    defaultLocalization: "en",
    platforms: [.macOS(.v13), .iOS(.v17)],
    products: [
        .library(name: "SanitizerCore", targets: ["SanitizerCore"]),
        .library(name: "LocalizationSupport", targets: ["LocalizationSupport"]),
        .executable(name: "sanitizer-cli", targets: ["SanitizerCLI"])
    ],
    targets: [
        .target(name: "LocalizationSupport"),
        .target(name: "SanitizerCore", dependencies: ["LocalizationSupport"], resources: [.process("Resources")]),
        .executableTarget(name: "SanitizerCLI", dependencies: ["SanitizerCore"]),
        .testTarget(name: "SanitizerCoreTests", dependencies: ["SanitizerCore"]),
        .testTarget(name: "LocalizationSupportTests", dependencies: ["LocalizationSupport"], resources: [.process("Resources")])
    ],
    swiftLanguageVersions: [.v5]
)
