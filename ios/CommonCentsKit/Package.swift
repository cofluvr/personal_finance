// swift-tools-version: 6.2
// CommonCentsKit: everything of the phone's app but its screens (D-079, the I1 to I3 slice plan).
import PackageDescription

let package = Package(
    name: "CommonCentsKit",
    platforms: [.iOS(.v26), .macOS(.v26)],
    products: [.library(name: "CommonCentsKit", targets: ["CommonCentsKit"])],
    targets: [
        .target(name: "CommonCentsKit", resources: [.copy("Resources/schema_v1.json")]),
        .testTarget(name: "CommonCentsKitTests", dependencies: ["CommonCentsKit"]),
    ],
    swiftLanguageModes: [.v6]
)
