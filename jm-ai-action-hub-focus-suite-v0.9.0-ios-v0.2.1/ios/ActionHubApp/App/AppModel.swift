import ActionHubCore
import Foundation
import UIKit

@MainActor
final class AppModel: ObservableObject {
  enum ConnectionState: Equatable {
    case loading
    case disconnected
    case connected(deviceName: String)
    case failed(String)
  }

  @Published private(set) var connectionState: ConnectionState = .loading
  @Published private(set) var dashboard: MobileDashboard?
  @Published private(set) var reviewPlans: [ActionPlan] = []
  @Published private(set) var activity: [ActivityItem] = []
  @Published private(set) var triage: TriageResponse?
  @Published private(set) var matrix: MatrixResponse?
  @Published private(set) var big3: DualBig3Response?
  @Published private(set) var activeFocus: FocusSession?
  @Published private(set) var focusWeeklyReport: FocusWeeklyReport?
  @Published private(set) var pendingCaptureCount = 0
  @Published private(set) var deadLetterCaptureCount = 0
  @Published private(set) var deadLetters: [OfflineCaptureDeadLetter] = []
  @Published var notificationPreferences = NotificationPreferences()
  @Published var isRefreshing = false
  @Published var lastError: String?
  @Published var selectedTab: AppTab = .today
  @Published var focusRequestedSection: String?
  @Published var presentedPlanId: String?
  @Published var reviewNavigationPath: [String] = []
  @Published var isCapturePresented = false
  @Published private(set) var pendingPairingPayload: String?

  let biometricLock = BiometricLock()
  private let credentialStore = KeychainCredentialStore()
  private lazy var session = MobileSession(store: credentialStore, appVersion: AppConfiguration.appVersion)
  private var appGroupStore: AppGroupStore?
  private var captureQueue: OfflineCaptureQueue?
  private let liveActivity = FocusLiveActivityManager()

  init() {
    do {
      let group = try AppGroupStore()
      appGroupStore = group
      captureQueue = OfflineCaptureQueue(fileURL: group.captureQueueURL)
    } catch {
      lastError = error.localizedDescription
    }
  }

  func start() async {
    do {
      let restored = try await session.restore()
      guard let restored else {
        connectionState = .disconnected
        await updatePendingCount()
        return
      }
      connectionState = .connected(deviceName: restored.device.deviceName)
      notificationPreferences = NotificationPreferences(
        dictionary: restored.device.notificationPreferences)
      NotificationManager.shared.registerIfAuthorized()
      await refreshAll()
      handlePendingSystemRoute()
      await flushCaptures()
    } catch ActionHubAPIError.revoked {
      connectionState = .disconnected
      lastError = nil
    } catch {
      connectionState = .failed(error.localizedDescription)
    }
    await updatePendingCount()
  }

  func pair(using rawPayload: String) async {
    isRefreshing = true
    defer { isRefreshing = false }
    do {
      let payload = try PairingPayload.parse(rawPayload)
      let device = try await session.pair(
        payload: payload,
        deviceInfo: MobileDeviceInfo(
          name: UIDevice.current.name,
          hardwareModel: Self.hardwareModel,
          osVersion: UIDevice.current.systemVersion,
          appVersion: AppConfiguration.appVersion,
          pushEnvironment: AppConfiguration.pushEnvironment
        )
      )
      connectionState = .connected(deviceName: device.deviceName)
      notificationPreferences = NotificationPreferences(dictionary: device.notificationPreferences)
      lastError = nil
      await flushCaptures()
      await refreshAll()
      NotificationManager.shared.requestAuthorizationAndRegister()
    } catch {
      lastError = error.localizedDescription
      connectionState = .disconnected
    }
  }

  func resetConnection() {
    connectionState = .disconnected
    lastError = nil
  }

  func consumePendingPairingPayload() -> String? {
    defer { pendingPairingPayload = nil }
    return pendingPairingPayload
  }

  func prioritizeReviewPlan(_ planId: String) {
    guard let index = reviewPlans.firstIndex(where: { $0.id == planId }), index != 0 else { return }
    let plan = reviewPlans.remove(at: index)
    reviewPlans.insert(plan, at: 0)
  }

  func updateNotificationPreferences(_ preferences: NotificationPreferences) async throws
    -> MobileDevice
  {
    let device = try await session.updateNotificationPreferences(preferences)
    notificationPreferences = NotificationPreferences(dictionary: device.notificationPreferences)
    return device
  }

  func disconnect() async {
    do { try await session.disconnect(revokeServer: true) } catch {
      lastError = error.localizedDescription
    }
    dashboard = nil
    reviewPlans = []
    activity = []
    triage = nil
    matrix = nil
    big3 = nil
    activeFocus = nil
    focusWeeklyReport = nil
    await liveActivity.end()
    connectionState = .disconnected
  }

  func refreshAll() async {
    guard case .connected = connectionState else { return }
    isRefreshing = true
    defer { isRefreshing = false }
    do {
      let snapshot = try await session.refreshSnapshot(
        currentAppVersion: AppConfiguration.appVersion)
      dashboard = snapshot.dashboard
      reviewPlans = snapshot.review
      activity = snapshot.activity
      triage = snapshot.triage
      matrix = snapshot.matrix
      big3 = snapshot.big3
      activeFocus = snapshot.activeFocus
      if let activeFocus = snapshot.activeFocus {
        await liveActivity.update(session: activeFocus)
      } else {
        await liveActivity.end()
      }
      try appGroupStore?.writeWidgetSnapshot(WidgetSnapshot(dashboard: snapshot.dashboard))
      lastError = nil
    } catch {
      handle(error)
    }
  }

  @discardableResult
  func capture(text: String, source: String = "ios-app") async -> Bool {
    guard let captureQueue else {
      lastError = "App Group 오프라인 큐를 사용할 수 없습니다."
      return false
    }
    do {
      _ = try await captureQueue.enqueue(
        text: text,
        source: source,
        metadata: ["app_version": .string(AppConfiguration.appVersion)]
      )
      await updatePendingCount()
      if case .connected = connectionState { await flushCaptures() }
      return true
    } catch {
      lastError = error.localizedDescription
      return false
    }
  }

  func flushCaptures() async {
    guard case .connected = connectionState, let captureQueue else {
      await updatePendingCount()
      return
    }
    do {
      while let response = try await captureQueue.flush(using: session, batchSize: 25) {
        if response.processed + response.duplicate == 0 { break }
      }
      await updatePendingCount()
      reviewPlans = try await session.reviewPlans(limit: 50)
      dashboard = try await session.dashboard(currentAppVersion: AppConfiguration.appVersion)
      if let dashboard {
        try appGroupStore?.writeWidgetSnapshot(WidgetSnapshot(dashboard: dashboard))
      }
    } catch {
      lastError = error.localizedDescription
      await updatePendingCount()
    }
  }

  func refreshDeadLetters() async {
    guard let captureQueue else {
      deadLetterCaptureCount = 0
      deadLetters = []
      return
    }
    do {
      deadLetters = try await captureQueue.deadLetters(limit: 100)
      deadLetterCaptureCount = try await captureQueue.deadLetterCount()
    } catch {
      lastError = error.localizedDescription
    }
  }

  func restoreAllDeadLetters() async {
    guard let captureQueue else {
      lastError = "App Group 오프라인 큐를 사용할 수 없습니다."
      return
    }
    do {
      var previousCount = try await captureQueue.deadLetterCount()
      while previousCount > 0 {
        let page = try await captureQueue.deadLetters(limit: 100)
        guard !page.isEmpty else {
          throw ActionHubAPIError.encoding("dead-letter 목록을 다시 읽을 수 없습니다")
        }
        for deadLetter in page {
          try await captureQueue.restoreDeadLetter(clientCaptureId: deadLetter.id)
        }
        let currentCount = try await captureQueue.deadLetterCount()
        guard currentCount < previousCount else {
          throw ActionHubAPIError.encoding("dead-letter 복원이 진행되지 않았습니다")
        }
        previousCount = currentCount
      }
      lastError = nil
    } catch {
      lastError = error.localizedDescription
    }
    await updatePendingCount()
    await refreshDeadLetters()
  }

  func purgeAllDeadLetters(confirmed: Bool) async {
    guard confirmed else { return }
    guard let captureQueue else {
      lastError = "App Group 오프라인 큐를 사용할 수 없습니다."
      return
    }
    do {
      var previousCount = try await captureQueue.deadLetterCount()
      while previousCount > 0 {
        let page = try await captureQueue.deadLetters(limit: 100)
        guard !page.isEmpty else {
          throw ActionHubAPIError.encoding("dead-letter 목록을 다시 읽을 수 없습니다")
        }
        for deadLetter in page {
          try await captureQueue.purgeDeadLetter(clientCaptureId: deadLetter.id)
        }
        let currentCount = try await captureQueue.deadLetterCount()
        guard currentCount < previousCount else {
          throw ActionHubAPIError.encoding("dead-letter 삭제가 진행되지 않았습니다")
        }
        previousCount = currentCount
      }
      lastError = nil
    } catch {
      lastError = error.localizedDescription
    }
    await updatePendingCount()
    await refreshDeadLetters()
  }

  func loadPlan(_ id: String) async throws -> ActionPlan {
    try await session.plan(id: id)
  }

  func updateItem(planId: String, itemId: String, patch: ActionItemPatch) async throws -> ActionPlan
  {
    let updated = try await session.updateItem(planId: planId, itemId: itemId, patch: patch)
    replacePlan(updated)
    return updated
  }

  func approve(plan: ActionPlan, itemIds: [String]? = nil) async throws -> ActionPlan {
    let updated = try await session.approve(
      planId: plan.id,
      request: PlanApprovalRequest(
        itemIds: itemIds,
        forceReviewItems: true,
        expectedPlanRevision: plan.revision
      )
    )
    replacePlan(updated)
    await refreshAll()
    return updated
  }

  func reject(plan: ActionPlan, itemIds: [String]? = nil, reason: String = "iOS에서 제외") async throws
    -> ActionPlan
  {
    let updated = try await session.reject(
      planId: plan.id,
      request: PlanRejectRequest(
        itemIds: itemIds, reason: reason, expectedPlanRevision: plan.revision)
    )
    replacePlan(updated)
    await refreshAll()
    return updated
  }

  func execute(plan: ActionPlan, itemIds: [String]? = nil) async throws -> ExecutionSummary {
    let summary = try await session.execute(
      planId: plan.id,
      request: PlanExecuteRequest(itemIds: itemIds, expectedPlanRevision: plan.revision)
    )
    reviewPlans.removeAll { $0.id == plan.id }
    await refreshAll()
    return summary
  }

  func classify(_ item: FocusActionSummary, as quadrant: Quadrant) async throws {
    _ = try await session.classifyFocusAction(
      itemId: item.id,
      request: ClassifyActionRequest(
        quadrant: quadrant,
        reason: "iOS Swipe Triage"
      )
    )
    try await refreshFocus()
  }

  func configureBig3(
    humanItemIds: [String],
    aiItemIds: [String],
    availableMinutes: Int?
  ) async throws {
    big3 = try await session.setBig3(
      DualBig3Request(
        humanItemIds: Array(humanItemIds.prefix(3)),
        aiItemIds: Array(aiItemIds.prefix(3)),
        availableMinutes: availableMinutes
      ))
    try await refreshFocus()
  }

  @discardableResult
  func decompose(_ item: FocusActionSummary) async throws -> [MicroStep] {
    let steps = try await session.decomposeFocusAction(itemId: item.id)
    try await refreshFocus()
    return steps
  }

  @discardableResult
  func updateMicroStep(_ step: MicroStep, state: String) async throws -> MicroStep {
    let updated = try await session.updateMicroStep(
      stepId: step.id,
      request: MicroStepUpdateRequest(state: state)
    )
    try await refreshFocus()
    return updated
  }

  @discardableResult
  func startFocus(on item: FocusActionSummary, minutes: Int) async throws -> FocusSession {
    let started = try await session.startFocusSession(
      FocusSessionStartRequest(actionItemId: item.id, plannedMinutes: minutes))
    activeFocus = started
    await liveActivity.start(session: started)
    try await refreshFocus()
    return started
  }

  @discardableResult
  func updateFocus(
    action: String,
    extensionMinutes: Int? = nil,
    completionNote: String? = nil,
    markActionCompleted: Bool = false
  ) async throws -> FocusSession {
    guard let current = activeFocus else { throw ActionHubAPIError.notFound }
    let updated = try await session.updateFocusSession(
      id: current.id,
      request: FocusSessionUpdateRequest(
        action: action,
        expectedRevision: current.revision,
        extensionMinutes: extensionMinutes,
        completionNote: completionNote,
        markActionCompleted: markActionCompleted
      ))
    activeFocus = ["completed", "abandoned"].contains(updated.state.rawValue) ? nil : updated
    if let activeFocus {
      await liveActivity.update(session: activeFocus)
    } else {
      await liveActivity.end(finalSession: updated)
    }
    try await refreshFocus()
    return updated
  }

  @discardableResult
  func closeDay(_ decisions: [DayCloseDecisionInput]) async throws -> DayCloseResponse {
    let response = try await session.closeFocusDay(DayCloseRequest(decisions: decisions))
    try await refreshFocus()
    return response
  }

  func loadFocusWeeklyReport() async {
    do { focusWeeklyReport = try await session.focusWeeklyReport() } catch { handle(error) }
  }

  private func refreshFocus() async throws {
    async let triageRequest = session.focusTriage(limit: 100)
    async let matrixRequest = session.focusMatrix(limitPerQuadrant: 100)
    async let big3Request = session.big3()
    async let activeRequest = session.activeFocusSession()
    let (newTriage, newMatrix, newBig3, newActive) = try await (
      triageRequest, matrixRequest, big3Request, activeRequest
    )
    triage = newTriage
    matrix = newMatrix
    big3 = newBig3
    activeFocus = newActive
    dashboard = try await session.dashboard(currentAppVersion: AppConfiguration.appVersion)
    if let dashboard {
      try appGroupStore?.writeWidgetSnapshot(WidgetSnapshot(dashboard: dashboard))
    }
  }

  func registerPushToken(_ data: Data) async {
    guard case .connected = connectionState else { return }
    let token = data.map { String(format: "%02x", $0) }.joined()
    do {
      _ = try await session.registerPushToken(token, environment: AppConfiguration.pushEnvironment)
    } catch {
      lastError = "푸시 토큰 등록 실패: \(error.localizedDescription)"
    }
  }

  func handlePendingSystemRoute() {
    guard let route = appGroupStore?.consumePendingRoute() else { return }
    switch route {
    case "focus", "triage", "matrix", "big3", "day-close":
      selectedTab = .focus
      focusRequestedSection = route
    case "review": selectedTab = .review
    case "activity": selectedTab = .activity
    default: selectedTab = .today
    }
  }

  func handleDeepLink(_ url: URL) {
    guard url.scheme == "jmactionhub" else { return }
    switch url.host {
    case "pair":
      guard case .connected = connectionState else {
        // A custom URL can be opened by another app or a web page. Do not claim
        // credentials without a visible user confirmation in PairingView.
        pendingPairingPayload = url.absoluteString
        connectionState = .disconnected
        return
      }
      lastError = "새 서버에 연결하려면 현재 iPhone 연결을 먼저 해제하세요."
    case "capture":
      isCapturePresented = true
    case "review":
      selectedTab = .review
      presentedPlanId =
        URLComponents(url: url, resolvingAgainstBaseURL: false)?
        .queryItems?.first(where: { $0.name == "plan_id" })?.value
      if let presentedPlanId { reviewNavigationPath = [presentedPlanId] }
    case "activity": selectedTab = .activity
    case "focus", "triage", "matrix", "big3", "day-close":
      selectedTab = .focus
      focusRequestedSection = url.host
    case "today": selectedTab = .today
    default: break
    }
  }

  private func replacePlan(_ plan: ActionPlan) {
    if let index = reviewPlans.firstIndex(where: { $0.id == plan.id }) {
      reviewPlans[index] = plan
    } else {
      reviewPlans.insert(plan, at: 0)
    }
  }

  private func updatePendingCount() async {
    guard let captureQueue else {
      pendingCaptureCount = 0
      deadLetterCaptureCount = 0
      deadLetters = []
      return
    }
    pendingCaptureCount = (try? await captureQueue.count()) ?? 0
    deadLetterCaptureCount = (try? await captureQueue.deadLetterCount()) ?? 0
    deadLetters = (try? await captureQueue.deadLetters(limit: 100)) ?? []
  }

  private func handle(_ error: Error) {
    if case ActionHubAPIError.revoked = error {
      connectionState = .disconnected
    }
    lastError = error.localizedDescription
  }

  private static var hardwareModel: String {
    var systemInfo = utsname()
    uname(&systemInfo)
    return withUnsafePointer(to: &systemInfo.machine) {
      $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
    }
  }
}

enum AppTab: Hashable {
  case today, focus, review, activity, settings
}
