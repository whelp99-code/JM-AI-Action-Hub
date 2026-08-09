import Foundation

public struct MobileDeviceInfo: Sendable, Equatable {
  public let name: String
  public let hardwareModel: String?
  public let osVersion: String?
  public let appVersion: String?
  public let pushEnvironment: String

  public init(
    name: String,
    hardwareModel: String? = nil,
    osVersion: String? = nil,
    appVersion: String? = nil,
    pushEnvironment: String = "sandbox"
  ) {
    self.name = name
    self.hardwareModel = hardwareModel
    self.osVersion = osVersion
    self.appVersion = appVersion
    self.pushEnvironment = pushEnvironment
  }
}

public actor MobileSession {
  private let store: any CredentialStore
  private let transport: any HTTPTransport
  private var stored: StoredMobileSession?
  private var refreshTask: Task<StoredMobileSession, Error>?

  public init(
    store: any CredentialStore,
    transport: (any HTTPTransport)? = nil,
    appVersion: String? = nil
  ) {
    self.store = store
    self.transport = transport ?? URLSessionTransport(appVersion: appVersion)
  }

  public var isConnected: Bool { stored != nil }
  public var device: MobileDevice? { stored?.device }
  public var serverURL: URL? { stored?.serverURL }

  @discardableResult
  public func restore() async throws -> StoredMobileSession? {
    let value = try await store.load()
    if let value, value.refreshTokenExpiresAt <= Date() {
      try await store.delete()
      stored = nil
      throw ActionHubAPIError.revoked
    }
    stored = value
    return value
  }

  @discardableResult
  public func pair(payload: PairingPayload, deviceInfo: MobileDeviceInfo) async throws
    -> MobileDevice
  {
    let client = try ActionHubAPIClient(baseURL: payload.server, transport: transport)
    let capabilities = try await client.capabilities()
    guard capabilities.service == "JM-AI Action Hub" else {
      throw ActionHubAPIError.unexpectedService(capabilities.service)
    }
    guard capabilities.mobileEnabled, capabilities.pairingSupported else {
      throw ActionHubAPIError.mobileDisabled
    }
    guard capabilities.mobileApiVersion == "1" else {
      throw ActionHubAPIError.unsupportedMobileAPIVersion(capabilities.mobileApiVersion)
    }
    if let appVersion = deviceInfo.appVersion,
      SemanticVersion.requiresUpdate(
        current: appVersion, minimum: capabilities.minimumIosAppVersion)
    {
      throw ActionHubAPIError.updateRequired(
        minimumVersion: capabilities.minimumIosAppVersion)
    }
    let response = try await client.claimPairing(
      PairingClaimRequest(
        pairingID: payload.pairingId,
        code: payload.code,
        deviceName: deviceInfo.name,
        hardwareModel: deviceInfo.hardwareModel,
        osVersion: deviceInfo.osVersion,
        appVersion: deviceInfo.appVersion,
        pushEnvironment: deviceInfo.pushEnvironment
      )
    )
    let newSession = StoredMobileSession(serverURL: payload.server, response: response)
    try await store.save(newSession)
    stored = newSession
    return response.device
  }

  public func disconnect(revokeServer: Bool = true) async throws {
    var revokeError: Error?
    if revokeServer, stored != nil {
      do {
        try await perform { client, token in try await client.revokeDevice(accessToken: token) }
      } catch ActionHubAPIError.unauthorized {
        // The session is already invalid on the server.
      } catch ActionHubAPIError.revoked {
        // The device has already been revoked on the server.
      } catch {
        // Local credentials must still be removed even if the server is temporarily unreachable.
        // Administrators can revoke the stale device from the server device list later.
        revokeError = error
      }
    }

    stored = nil
    refreshTask?.cancel()
    refreshTask = nil
    do {
      try await store.delete()
    } catch {
      if revokeError == nil { revokeError = error }
    }

    if let revokeError { throw revokeError }
  }

  public func dashboard(currentAppVersion: String? = nil) async throws -> MobileDashboard {
    let value: MobileDashboard = try await perform { client, token in
      try await client.dashboard(accessToken: token)
    }
    if let currentAppVersion,
      SemanticVersion.requiresUpdate(
        current: currentAppVersion, minimum: value.minimumIosAppVersion)
    {
      throw ActionHubAPIError.updateRequired(minimumVersion: value.minimumIosAppVersion)
    }
    return value
  }

  public func refreshSnapshot(currentAppVersion: String? = nil) async throws -> MobileRefreshSnapshot {
    async let dashboardRequest = dashboard(currentAppVersion: currentAppVersion)
    async let reviewRequest = reviewPlans(limit: 50)
    async let activityRequest = activity(limit: 50)
    async let triageRequest = focusTriage(limit: 100)
    async let matrixRequest = focusMatrix(limitPerQuadrant: 100)
    async let big3Request = big3()
    async let activeFocusRequest = activeFocusSession()
    return try await MobileRefreshSnapshot(
      dashboard: dashboardRequest,
      review: reviewRequest,
      activity: activityRequest,
      triage: triageRequest,
      matrix: matrixRequest,
      big3: big3Request,
      activeFocus: activeFocusRequest
    )
  }

  public func reviewPlans(limit: Int = 50) async throws -> [ActionPlan] {
    try await perform { client, token in
      try await client.reviewPlans(accessToken: token, limit: limit)
    }
  }

  public func plan(id: String) async throws -> ActionPlan {
    try await perform { client, token in try await client.plan(id: id, accessToken: token) }
  }

  public func activity(limit: Int = 50) async throws -> [ActivityItem] {
    try await perform { client, token in try await client.activity(accessToken: token, limit: limit)
    }
  }

  public func resolveFollowup(
    id: String,
    request: FollowUpResolveRequest
  ) async throws -> FollowUp {
    try await perform { client, token in
      try await client.resolveFollowup(id: id, request: request, accessToken: token)
    }
  }

  public func changes(cursor: String? = nil, limit: Int? = nil) async throws -> ChangesResponse {
    try await perform { client, token in
      try await client.changes(accessToken: token, cursor: cursor, limit: limit)
    }
  }

  public func uploadCaptures(_ captures: [CaptureInput]) async throws -> CaptureBatchResponse {
    try await perform { client, token in
      try await client.uploadCaptures(captures, accessToken: token)
    }
  }

  public func updateItem(planId: String, itemId: String, patch: ActionItemPatch) async throws
    -> ActionPlan
  {
    try await perform { client, token in
      try await client.updateItem(planId: planId, itemId: itemId, patch: patch, accessToken: token)
    }
  }

  public func approve(planId: String, request: PlanApprovalRequest) async throws -> ActionPlan {
    try await perform { client, token in
      try await client.approve(planId: planId, request: request, accessToken: token)
    }
  }

  public func reject(planId: String, request: PlanRejectRequest) async throws -> ActionPlan {
    try await perform { client, token in
      try await client.reject(planId: planId, request: request, accessToken: token)
    }
  }

  public func execute(planId: String, request: PlanExecuteRequest) async throws -> ExecutionSummary
  {
    try await perform { client, token in
      try await client.execute(planId: planId, request: request, accessToken: token)
    }
  }

  public func focusTriage(limit: Int = 50) async throws -> TriageResponse {
    try await perform { client, token in
      try await client.focusTriage(accessToken: token, limit: limit)
    }
  }

  public func classifyFocusAction(itemId: String, request: ClassifyActionRequest) async throws
    -> FocusActionSummary
  {
    try await perform { client, token in
      try await client.classifyFocusAction(itemId: itemId, request: request, accessToken: token)
    }
  }

  public func focusMatrix(limitPerQuadrant: Int = 100) async throws -> MatrixResponse {
    try await perform { client, token in
      try await client.focusMatrix(accessToken: token, limitPerQuadrant: limitPerQuadrant)
    }
  }

  public func big3(targetDate: String? = nil) async throws -> DualBig3Response {
    try await perform { client, token in
      try await client.big3(accessToken: token, targetDate: targetDate)
    }
  }

  public func setBig3(_ request: DualBig3Request) async throws -> DualBig3Response {
    try await perform { client, token in
      try await client.setBig3(request, accessToken: token)
    }
  }

  public func decomposeFocusAction(
    itemId: String,
    request: DecomposeActionRequest = .init()
  ) async throws -> [MicroStep] {
    try await perform { client, token in
      try await client.decomposeFocusAction(itemId: itemId, request: request, accessToken: token)
    }
  }

  public func updateMicroStep(stepId: String, request: MicroStepUpdateRequest) async throws
    -> MicroStep
  {
    try await perform { client, token in
      try await client.updateMicroStep(stepId: stepId, request: request, accessToken: token)
    }
  }

  public func activeFocusSession() async throws -> FocusSession? {
    try await perform { client, token in
      try await client.activeFocusSession(accessToken: token)
    }
  }

  public func startFocusSession(_ request: FocusSessionStartRequest) async throws -> FocusSession {
    try await perform { client, token in
      try await client.startFocusSession(request, accessToken: token)
    }
  }

  public func updateFocusSession(id: String, request: FocusSessionUpdateRequest) async throws
    -> FocusSession
  {
    try await perform { client, token in
      try await client.updateFocusSession(id: id, request: request, accessToken: token)
    }
  }

  public func closeFocusDay(_ request: DayCloseRequest) async throws -> DayCloseResponse {
    try await perform { client, token in
      try await client.closeFocusDay(request, accessToken: token)
    }
  }

  public func focusWeeklyReport(endDate: String? = nil) async throws -> FocusWeeklyReport {
    try await perform { client, token in
      try await client.focusWeeklyReport(accessToken: token, endDate: endDate)
    }
  }

  @discardableResult
  public func registerPushToken(_ token: String, environment: String) async throws -> MobileDevice {
    let updated: MobileDevice = try await perform { client, access in
      try await client.registerPushToken(
        .init(token: token, environment: environment), accessToken: access)
    }
    try await updateStoredDevice(updated)
    return updated
  }

  @discardableResult
  public func updateNotificationPreferences(_ preferences: NotificationPreferences) async throws
    -> MobileDevice
  {
    let updated: MobileDevice = try await perform { client, access in
      try await client.updateNotificationPreferences(preferences, accessToken: access)
    }
    try await updateStoredDevice(updated)
    return updated
  }

  private func updateStoredDevice(_ device: MobileDevice) async throws {
    guard var value = stored else { throw ActionHubAPIError.noStoredSession }
    value.device = device
    stored = value
    try await store.save(value)
  }

  private func perform<T: Sendable>(
    _ operation: @Sendable (ActionHubAPIClient, String) async throws -> T
  ) async throws -> T {
    var current = try await validSession()
    let client = try ActionHubAPIClient(baseURL: current.serverURL, transport: transport)
    do {
      return try await operation(client, current.accessToken)
    } catch ActionHubAPIError.unauthorized {
      current = try await refreshSession(force: true)
      let retryClient = try ActionHubAPIClient(baseURL: current.serverURL, transport: transport)
      return try await operation(retryClient, current.accessToken)
    }
  }

  private func validSession() async throws -> StoredMobileSession {
    if stored == nil { stored = try await store.load() }
    guard let value = stored else { throw ActionHubAPIError.noStoredSession }
    if value.refreshTokenExpiresAt <= Date() {
      try await store.delete()
      stored = nil
      throw ActionHubAPIError.revoked
    }
    if value.accessTokenExpiresAt <= Date().addingTimeInterval(45) {
      return try await refreshSession(force: false)
    }
    return value
  }

  private func refreshSession(force: Bool) async throws -> StoredMobileSession {
    if let task = refreshTask { return try await task.value }
    let loaded: StoredMobileSession?
    if let stored { loaded = stored } else { loaded = try await store.load() }
    guard let existing = loaded else {
      throw ActionHubAPIError.noStoredSession
    }
    if !force, existing.accessTokenExpiresAt > Date().addingTimeInterval(45) { return existing }

    let store = self.store
    let transport = self.transport
    let task = Task<StoredMobileSession, Error> {
      let client = try ActionHubAPIClient(baseURL: existing.serverURL, transport: transport)
      let response = try await client.refresh(
        RefreshTokenRequest(
          refreshToken: existing.refreshToken,
          appVersion: existing.device.appVersion,
          osVersion: existing.device.osVersion
        )
      )
      let refreshed = StoredMobileSession(serverURL: existing.serverURL, response: response)
      try await store.save(refreshed)
      return refreshed
    }
    refreshTask = task
    do {
      let refreshed = try await task.value
      stored = refreshed
      refreshTask = nil
      return refreshed
    } catch {
      refreshTask = nil
      if case ActionHubAPIError.unauthorized = error {
        stored = nil
        try? await store.delete()
        throw ActionHubAPIError.revoked
      }
      throw error
    }
  }
}
