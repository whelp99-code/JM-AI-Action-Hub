import BackgroundTasks
import Foundation

@MainActor
final class BackgroundSyncManager {
  static let shared = BackgroundSyncManager()
  weak var model: AppModel?

  func register(model: AppModel) {
    self.model = model
    BGTaskScheduler.shared.register(
      forTaskWithIdentifier: AppConfiguration.refreshTaskIdentifier,
      using: nil
    ) { [weak self] task in
      guard let refreshTask = task as? BGAppRefreshTask else { return }
      Task { @MainActor in self?.handle(refreshTask) }
    }
  }

  func schedule() {
    let request = BGAppRefreshTaskRequest(identifier: AppConfiguration.refreshTaskIdentifier)
    request.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
    try? BGTaskScheduler.shared.submit(request)
  }

  private func handle(_ task: BGAppRefreshTask) {
    schedule()
    let work = Task { @MainActor [weak self] in
      await self?.model?.flushCaptures()
      await self?.model?.refreshAll()
    }
    task.expirationHandler = { work.cancel() }
    Task {
      _ = await work.result
      task.setTaskCompleted(success: !work.isCancelled)
    }
  }
}
