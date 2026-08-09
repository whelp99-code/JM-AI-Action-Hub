import Foundation

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

public struct ActionHubAPIClient: Sendable {
  public let baseURL: URL
  private let transport: any HTTPTransport
  private let encoder: JSONEncoder
  private let decoder: JSONDecoder

  public init(baseURL: URL, transport: any HTTPTransport = URLSessionTransport()) throws {
    let scheme = baseURL.scheme?.lowercased()
    let host = baseURL.host?.lowercased() ?? ""
    let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
    guard !host.isEmpty, scheme == "https" || (scheme == "http" && loopback) else {
      throw ActionHubAPIError.invalidBaseURL
    }
    self.baseURL = baseURL
    self.transport = transport
    self.encoder = ActionHubJSON.encoder()
    self.decoder = ActionHubJSON.decoder()
  }

  public func capabilities() async throws -> MobileCapabilities {
    try await send(method: "GET", path: "/api/v1/mobile/capabilities")
  }

  public func claimPairing(_ request: PairingClaimRequest) async throws -> MobileTokenResponse {
    try await send(method: "POST", path: "/api/v1/mobile/pairings/claim", body: request)
  }

  public func refresh(_ request: RefreshTokenRequest) async throws -> MobileTokenResponse {
    try await send(method: "POST", path: "/api/v1/mobile/token/refresh", body: request)
  }

  public func dashboard(accessToken: String) async throws -> MobileDashboard {
    try await send(method: "GET", path: "/api/v1/mobile/dashboard", accessToken: accessToken)
  }

  public func reviewPlans(accessToken: String, limit: Int = 50) async throws -> [ActionPlan] {
    try await send(
      method: "GET", path: "/api/v1/mobile/review", query: ["limit": String(limit)],
      accessToken: accessToken)
  }

  public func plan(id: String, accessToken: String) async throws -> ActionPlan {
    try await send(
      method: "GET", path: "/api/v1/mobile/plans/\(pathComponent(id))", accessToken: accessToken)
  }

  public func activity(accessToken: String, limit: Int = 50) async throws -> [ActivityItem] {
    try await send(
      method: "GET", path: "/api/v1/mobile/activity", query: ["limit": String(limit)],
      accessToken: accessToken)
  }

  public func resolveFollowup(
    id: String,
    request: FollowUpResolveRequest,
    accessToken: String
  ) async throws -> FollowUp {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/followups/\(pathComponent(id))/resolve",
      body: request,
      accessToken: accessToken
    )
  }

  public func changes(accessToken: String, cursor: String? = nil, limit: Int? = nil) async throws
    -> ChangesResponse
  {
    var query: [String: String] = [:]
    if let cursor { query["cursor"] = cursor }
    if let limit { query["limit"] = String(limit) }
    return try await send(
      method: "GET", path: "/api/v1/mobile/changes", query: query, accessToken: accessToken)
  }

  public func uploadCaptures(_ captures: [CaptureInput], accessToken: String) async throws
    -> CaptureBatchResponse
  {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/captures/batch",
      body: CaptureBatchRequest(captures: captures),
      accessToken: accessToken
    )
  }

  public func updateItem(
    planId: String,
    itemId: String,
    patch: ActionItemPatch,
    accessToken: String
  ) async throws -> ActionPlan {
    try await send(
      method: "PATCH",
      path: "/api/v1/mobile/plans/\(pathComponent(planId))/items/\(pathComponent(itemId))",
      body: patch,
      accessToken: accessToken
    )
  }

  public func approve(planId: String, request: PlanApprovalRequest, accessToken: String)
    async throws -> ActionPlan
  {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/plans/\(pathComponent(planId))/approve",
      body: request,
      accessToken: accessToken
    )
  }

  public func reject(planId: String, request: PlanRejectRequest, accessToken: String) async throws
    -> ActionPlan
  {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/plans/\(pathComponent(planId))/reject",
      body: request,
      accessToken: accessToken
    )
  }

  public func execute(planId: String, request: PlanExecuteRequest, accessToken: String) async throws
    -> ExecutionSummary
  {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/plans/\(pathComponent(planId))/execute",
      body: request,
      accessToken: accessToken
    )
  }

  public func focusTriage(accessToken: String, limit: Int = 50) async throws -> TriageResponse {
    try await send(
      method: "GET", path: "/api/v1/mobile/triage", query: ["limit": String(limit)],
      accessToken: accessToken)
  }

  public func classifyFocusAction(
    itemId: String,
    request: ClassifyActionRequest,
    accessToken: String
  ) async throws -> FocusActionSummary {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/actions/\(pathComponent(itemId))/classify",
      body: request,
      accessToken: accessToken)
  }

  public func focusMatrix(accessToken: String, limitPerQuadrant: Int = 100) async throws
    -> MatrixResponse
  {
    try await send(
      method: "GET", path: "/api/v1/mobile/matrix",
      query: ["limit_per_quadrant": String(limitPerQuadrant)], accessToken: accessToken)
  }

  public func big3(accessToken: String, targetDate: String? = nil) async throws -> DualBig3Response
  {
    var query: [String: String] = [:]
    if let targetDate { query["target_date"] = targetDate }
    return try await send(
      method: "GET", path: "/api/v1/mobile/commitments/today", query: query,
      accessToken: accessToken)
  }

  public func setBig3(_ request: DualBig3Request, accessToken: String) async throws
    -> DualBig3Response
  {
    try await send(
      method: "POST", path: "/api/v1/mobile/commitments", body: request,
      accessToken: accessToken)
  }

  public func decomposeFocusAction(
    itemId: String,
    request: DecomposeActionRequest = .init(),
    accessToken: String
  ) async throws -> [MicroStep] {
    try await send(
      method: "POST", path: "/api/v1/mobile/actions/\(pathComponent(itemId))/decompose",
      body: request, accessToken: accessToken)
  }

  public func updateMicroStep(
    stepId: String,
    request: MicroStepUpdateRequest,
    accessToken: String
  ) async throws -> MicroStep {
    try await send(
      method: "PATCH", path: "/api/v1/mobile/microsteps/\(pathComponent(stepId))",
      body: request, accessToken: accessToken)
  }

  public func activeFocusSession(accessToken: String) async throws -> FocusSession? {
    try await send(
      method: "GET", path: "/api/v1/mobile/focus-sessions/active", accessToken: accessToken)
  }

  public func startFocusSession(
    _ request: FocusSessionStartRequest,
    accessToken: String
  ) async throws -> FocusSession {
    try await send(
      method: "POST", path: "/api/v1/mobile/focus-sessions", body: request,
      accessToken: accessToken, acceptedStatus: [200, 201])
  }

  public func updateFocusSession(
    id: String,
    request: FocusSessionUpdateRequest,
    accessToken: String
  ) async throws -> FocusSession {
    try await send(
      method: "PATCH", path: "/api/v1/mobile/focus-sessions/\(pathComponent(id))",
      body: request, accessToken: accessToken)
  }

  public func closeFocusDay(_ request: DayCloseRequest, accessToken: String) async throws
    -> DayCloseResponse
  {
    try await send(
      method: "POST", path: "/api/v1/mobile/day-close", body: request,
      accessToken: accessToken)
  }

  public func focusWeeklyReport(accessToken: String, endDate: String? = nil) async throws
    -> FocusWeeklyReport
  {
    var query: [String: String] = [:]
    if let endDate { query["end_date"] = endDate }
    return try await send(
      method: "GET", path: "/api/v1/mobile/reports/focus-weekly", query: query,
      accessToken: accessToken)
  }

  public func registerPushToken(_ request: PushTokenRequest, accessToken: String) async throws
    -> MobileDevice
  {
    try await send(
      method: "POST",
      path: "/api/v1/mobile/devices/me/push-token",
      body: request,
      accessToken: accessToken
    )
  }

  public func updateNotificationPreferences(
    _ preferences: NotificationPreferences,
    accessToken: String
  ) async throws -> MobileDevice {
    try await send(
      method: "PATCH",
      path: "/api/v1/mobile/devices/me/notification-preferences",
      body: preferences,
      accessToken: accessToken
    )
  }

  public func revokeDevice(accessToken: String) async throws {
    let _: EmptyResponse = try await send(
      method: "DELETE",
      path: "/api/v1/mobile/devices/me",
      accessToken: accessToken,
      acceptedStatus: [204]
    )
  }

  private func pathComponent(_ value: String) -> String {
    var allowed = CharacterSet.urlPathAllowed
    allowed.remove(charactersIn: "/?#%")
    return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
  }

  private func makeURL(path: String, query: [String: String]) throws -> URL {
    guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
      throw ActionHubAPIError.invalidBaseURL
    }
    let basePath =
      components.percentEncodedPath.hasSuffix("/")
      ? String(components.percentEncodedPath.dropLast()) : components.percentEncodedPath
    components.percentEncodedPath = basePath + path
    if !query.isEmpty {
      components.queryItems = query.sorted { $0.key < $1.key }.map(URLQueryItem.init)
    }
    guard let url = components.url else { throw ActionHubAPIError.invalidBaseURL }
    return url
  }

  private func send<Response: Decodable>(
    method: String,
    path: String,
    query: [String: String] = [:],
    accessToken: String? = nil,
    acceptedStatus: Set<Int> = [200]
  ) async throws -> Response {
    try await send(
      method: method, path: path, query: query, bodyData: nil, accessToken: accessToken,
      acceptedStatus: acceptedStatus)
  }

  private func send<Body: Encodable, Response: Decodable>(
    method: String,
    path: String,
    query: [String: String] = [:],
    body: Body,
    accessToken: String? = nil,
    acceptedStatus: Set<Int> = [200]
  ) async throws -> Response {
    let bodyData: Data
    do { bodyData = try encoder.encode(body) } catch {
      throw ActionHubAPIError.encoding(error.localizedDescription)
    }
    return try await send(
      method: method, path: path, query: query, bodyData: bodyData, accessToken: accessToken,
      acceptedStatus: acceptedStatus)
  }

  private func send<Response: Decodable>(
    method: String,
    path: String,
    query: [String: String],
    bodyData: Data?,
    accessToken: String?,
    acceptedStatus: Set<Int>
  ) async throws -> Response {
    var request = URLRequest(url: try makeURL(path: path, query: query))
    request.httpMethod = method
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "X-Request-ID")
    if let accessToken {
      request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
    }
    if let bodyData {
      request.httpBody = bodyData
      request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    let data: Data
    let response: HTTPURLResponse
    do { (data, response) = try await transport.data(for: request) } catch let error
      as ActionHubAPIError
    { throw error } catch { throw ActionHubAPIError.transport(error.localizedDescription) }

    guard acceptedStatus.contains(response.statusCode) else {
      throw mapHTTPError(status: response.statusCode, data: data)
    }
    if Response.self == EmptyResponse.self, data.isEmpty {
      return EmptyResponse() as! Response
    }
    do { return try decoder.decode(Response.self, from: data) } catch {
      throw ActionHubAPIError.decoding(error.localizedDescription)
    }
  }

  private func mapHTTPError(status: Int, data: Data) -> ActionHubAPIError {
    let envelope = try? decoder.decode(ErrorEnvelope.self, from: data)
    let detail = envelope?.detail
    if status == 401 { return .unauthorized }
    if status == 403 { return .forbidden }
    if status == 404 { return .notFound }
    if status == 409 {
      var code: String?
      var revision: Int?
      if case .object(let values) = detail {
        if case .string(let value) = values["code"] { code = value }
        if case .number(let value) = values["current_revision"] { revision = Int(value) }
      }
      return .conflict(code: code, currentRevision: revision)
    }
    return .server(
      status: status,
      message: detail?.stringDescription ?? String(data: data, encoding: .utf8) ?? "Unknown error")
  }
}

private struct EmptyResponse: Codable, Sendable {}
