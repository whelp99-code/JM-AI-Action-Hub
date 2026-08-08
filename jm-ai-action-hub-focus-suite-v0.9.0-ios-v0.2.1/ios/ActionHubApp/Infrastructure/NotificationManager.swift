import Foundation
import UIKit
import UserNotifications

@MainActor
final class NotificationManager: NSObject, @preconcurrency UNUserNotificationCenterDelegate {
  static let shared = NotificationManager()
  weak var model: AppModel?

  func configure(model: AppModel) {
    self.model = model
    UNUserNotificationCenter.current().delegate = self
  }

  func requestAuthorizationAndRegister() {
    UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) {
      granted, _ in
      guard granted else { return }
      DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
    }
  }

  /// `requestAuthorization` silently no-ops once the user has already denied the system
  /// prompt -- iOS only asks once. Callers use this to detect that case and offer a path to
  /// Settings instead of a button that visibly does nothing.
  func currentAuthorizationStatus() async -> UNAuthorizationStatus {
    await withCheckedContinuation { continuation in
      UNUserNotificationCenter.current().getNotificationSettings { settings in
        continuation.resume(returning: settings.authorizationStatus)
      }
    }
  }

  /// APNs device tokens can change. Register again on every connected app launch
  /// without re-prompting users who have not granted notification permission.
  func registerIfAuthorized() {
    UNUserNotificationCenter.current().getNotificationSettings { settings in
      switch settings.authorizationStatus {
      case .authorized, .provisional, .ephemeral:
        DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
      default:
        return
      }
    }
  }

  func didRegister(deviceToken: Data) {
    Task { @MainActor [weak self] in await self?.model?.registerPushToken(deviceToken) }
  }

  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    willPresent notification: UNNotification,
    withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
  ) {
    completionHandler([.banner, .badge, .sound])
  }

  func userNotificationCenter(
    _ center: UNUserNotificationCenter,
    didReceive response: UNNotificationResponse,
    withCompletionHandler completionHandler: @escaping () -> Void
  ) {
    let info = response.notification.request.content.userInfo
    let event = info["event"] as? String
    let entityId = info["entity_id"] as? String
    Task { @MainActor [weak self] in
      guard let model = self?.model else { return }
      if event == "review_required" {
        model.selectedTab = .review
        model.presentedPlanId = entityId
        if let entityId { model.reviewNavigationPath = [entityId] }
      } else {
        model.selectedTab = .activity
      }
      await model.refreshAll()
    }
    completionHandler()
  }
}
