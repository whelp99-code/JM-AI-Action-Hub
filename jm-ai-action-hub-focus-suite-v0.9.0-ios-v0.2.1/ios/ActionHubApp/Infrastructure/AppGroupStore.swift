import ActionHubCore
import Foundation
import WidgetKit

struct AppGroupStore {
  let containerURL: URL

  init(groupIdentifier: String = AppConfiguration.appGroupIdentifier) throws {
    guard
      let url = FileManager.default.containerURL(
        forSecurityApplicationGroupIdentifier: groupIdentifier)
    else {
      throw AppGroupError.unavailable(groupIdentifier)
    }
    containerURL = url
  }

  var captureQueueURL: URL { containerURL.appendingPathComponent("captures/pending.json") }
  var widgetSnapshotURL: URL { containerURL.appendingPathComponent("widget/dashboard.json") }
  var pendingRouteURL: URL { containerURL.appendingPathComponent("navigation/pending-route.txt") }

  func writeWidgetSnapshot(_ snapshot: WidgetSnapshot) throws {
    try FileManager.default.createDirectory(
      at: widgetSnapshotURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    let data = try ActionHubJSON.encoder().encode(snapshot)
    try data.write(
      to: widgetSnapshotURL,
      options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
    )
    WidgetCenter.shared.reloadAllTimelines()
  }

  func writePendingRoute(_ route: String) throws {
    try FileManager.default.createDirectory(
      at: pendingRouteURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    try Data(route.utf8).write(
      to: pendingRouteURL,
      options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
    )
  }

  func consumePendingRoute() -> String? {
    guard
      let value = try? String(contentsOf: pendingRouteURL, encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty
    else { return nil }
    try? FileManager.default.removeItem(at: pendingRouteURL)
    return value
  }

}

enum AppGroupError: LocalizedError {
  case unavailable(String)
  var errorDescription: String? {
    switch self {
    case .unavailable(let group):
      return "App Group \(group)을 열 수 없습니다. Signing & Capabilities를 확인하세요."
    }
  }
}
