// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "ActionHubCore",
  platforms: [
    .iOS(.v18),
    .macOS(.v14),
  ],
  products: [
    .library(name: "ActionHubCore", targets: ["ActionHubCore"]),
    .executable(name: "action-hub-mobile-smoke", targets: ["ActionHubMobileSmoke"]),
  ],
  targets: [
    .target(name: "ActionHubCore"),
    .executableTarget(name: "ActionHubMobileSmoke", dependencies: ["ActionHubCore"]),
    .testTarget(name: "ActionHubCoreTests", dependencies: ["ActionHubCore"]),
  ]
)
