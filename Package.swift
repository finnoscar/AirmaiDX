// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AirmaiDX",
    defaultLocalization: "zh-Hans",
    platforms: [.macOS(.v15), .iOS(.v17)],
    products: [
        .executable(name: "AirmaiDX", targets: ["AirmaiDX"]),
        .library(name: "AirmaiCore", targets: ["AirmaiCore"]),
        .library(name: "AirmaiEditorPreview", targets: ["AirmaiEditorPreview"]),
        .library(name: "AirmaiTouchKit", targets: ["AirmaiTouchKit"]),
        .library(name: "AirmaiMobileCore", targets: ["AirmaiMobileCore"])
    ],
    targets: [
        .target(name: "AirmaiCore", resources: [.process("Resources")]),
        .target(name: "AirmaiEditorPreview", dependencies: ["AirmaiCore"], plugins: ["SyncEditorPreview"]),
        .target(name: "AirmaiTouchKit"),
        .target(name: "AirmaiMobileCore"),
        .executableTarget(name: "AirmaiDX", dependencies: ["AirmaiCore", "AirmaiEditorPreview"]),
        .testTarget(name: "AirmaiCoreTests", dependencies: ["AirmaiCore", "AirmaiEditorPreview"]),
        .testTarget(name: "AirmaiTouchKitTests", dependencies: ["AirmaiTouchKit", "AirmaiMobileCore"]),
        .plugin(name: "SyncEditorPreview", capability: .buildTool())
    ],
    swiftLanguageModes: [.v5]
)
