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
  @Published private(set) var isStarting = false
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
    // Guards the foreground (`scenePhase == .active`) sync path against racing this same sync
    // work on cold launch -- `.task { start() }` and the initial `.active` transition otherwise
    // fire together and double every request. See ActionHubApp.swift.
    isStarting = true
    defer { isStarting = false }
    do {
      let restored = try await session.restore()
      guard let restored else {
        connectionState = .disconnected
        await updatePendingCount()
        return
      }
      connectionState = .connected(deviceName: restored.device.deviceName)
      notificationPreferences = restored.device.notificationPreferences
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
      notificationPreferences = device.notificationPreferences
      lastError = nil
      await flushCaptures()
      await refreshAll()
      NotificationManager.shared.requestAuthorizationAndRegister()
    } catch {
      handle(error)
      connectionState = .disconnected
    }
  }

  func resetConnection() {
    connectionState = .disconnected
    lastError = nil
    // Moving the screen back to pairing was not enough on its own: the stale credential stayed in
    // the Keychain, so the next launch restored it and landed on the same failure. Revoking on the
    // server is pointless here -- this path exists because the server could not be reached.
    Task { try? await session.disconnect(revokeServer: false) }
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
    notificationPreferences = device.notificationPreferences
    return device
  }

  func disconnect() async {
    do { try await session.disconnect(revokeServer: true) } catch {
      handle(error)
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

  /// Entry point for `.refreshable`. SwiftUI cancels the task backing a pull-to-refresh as
  /// soon as the gesture resolves, which cancelled the in-flight URLSession requests and
  /// surfaced as a "cancelled" network error. An unstructured task does not inherit that
  /// cancellation, so the refresh runs to completion either way.
  func refreshAllDetached() async {
    await Task { await self.refreshAll() }.value
  }

  func refreshAll() async {
    guard case .connected = connectionState else { return }
    // Re-entrancy guard: every scenePhase == .active transition (including the one right
    // after a system sheet -- permission dialog, share sheet, camera -- closes) calls this.
    // Without the guard, overlapping calls raced and the response that finished last could
    // overwrite fresher state with stale data.
    guard !isRefreshing else { return }
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
      handle(error)
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
      handle(error)
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
      handle(error)
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
      handle(error)
    }
    // Restoring puts the captures back on the send queue -- without this, "모두 복원" looked
    // like it worked (the dead-letter count dropped) but nothing was actually sent until the
    // next unrelated sync.
    await flushCaptures()
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
      handle(error)
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
    // Every other action (approve/reject/execute/classify/...) refreshes derived state
    // (badges, list filters) after mutating. This one didn't, so turning off "계속 검토
    // 필요" and saving left the review badge and list showing the stale count.
    await refreshAll()
    return updated
  }

  /// `forceReviewItems` defaults to `false` -- the server's structural review gate (e.g. a
  /// calendar item with no start time) exists to stop exactly the kind of silent-failure
  /// approval that shipped before this fix. When the server leaves items blocked
  /// (`blockedItemIds` non-empty on the returned plan), the caller is responsible for showing
  /// the block reason to the user and only retrying with `forceReviewItems: true` after an
  /// explicit user choice -- see PlanDetailView.
  func approve(plan: ActionPlan, itemIds: [String]? = nil, forceReviewItems: Bool = false)
    async throws -> ActionPlan
  {
    let updated = try await session.approve(
      planId: plan.id,
      request: PlanApprovalRequest(
        itemIds: itemIds,
        forceReviewItems: forceReviewItems,
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
      guard !Self.isCancellation(error) else { return }
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

  /// Not private: Views that catch their own errors (PlanDetailView, DayCloseView,
  /// SettingsView, ...) route through this too, so the cancellation filter below actually
  /// applies everywhere instead of only to the call sites inside AppModel itself.
  func handle(_ error: Error) {
    if case ActionHubAPIError.revoked = error {
      connectionState = .disconnected
    }
    // A cancelled request is the result of the user or the system abandoning the work, not a
    // failure worth reporting; showing it reads as "네트워크 오류: cancelled".
    if Self.isCancellation(error) { return }
    lastError = error.localizedDescription
  }

  /// `HTTPTransport` now surfaces cancellation as `ActionHubAPIError.cancelled` (see
  /// HTTPTransport.swift), but structured-concurrency cancellation can still reach a caller
  /// directly as `CancellationError` without ever going through the transport, so both are
  /// checked here.
  static func isCancellation(_ error: Error) -> Bool {
    if error is CancellationError { return true }
    if case ActionHubAPIError.cancelled = error { return true }
    if let urlError = error as? URLError, urlError.code == .cancelled { return true }
    return false
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
