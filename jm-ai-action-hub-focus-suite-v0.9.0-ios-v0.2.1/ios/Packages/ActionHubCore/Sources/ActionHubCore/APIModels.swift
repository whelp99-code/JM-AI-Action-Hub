import Foundation

public enum ActionType: String, Codable, Sendable, CaseIterable {
  case event
  case todo
  case projectTask = "project_task"
  case reminder
  case note
}

public enum Destination: String, Codable, Sendable, CaseIterable {
  case todoist
  case github
  case googleCalendar = "google_calendar"
  case localICS = "local_ics"
  case none
}

public enum ExecutorType: String, Codable, Sendable, CaseIterable {
  case human
  case ai
  case hybrid
  case external
}

public struct MobileCapabilities: Codable, Sendable, Equatable {
  public let service: String
  public let serverVersion: String
  public let mobileApiVersion: String
  public let mobileEnabled: Bool
  public let minimumIosAppVersion: String
  public let recommendedIosAppVersion: String?
  public let pairingSupported: Bool
  public let pushSupported: Bool
  public let features: [String]
}

public struct MobileDevice: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public var deviceName: String
  public let platform: String
  public let hardwareModel: String?
  public var osVersion: String?
  public var appVersion: String?
  public let status: String
  public let scopes: [String]
  public let tokenVersion: Int
  public let pushEnvironment: String
  public let notificationPreferences: NotificationPreferences
  public let lastSeenAt: Date?
  public let revokedAt: Date?
  public let createdAt: Date
  public let updatedAt: Date
  public let pushRegistered: Bool
}

public struct MobileTokenResponse: Codable, Sendable, Equatable {
  public let tokenType: String
  public let accessToken: String
  public let expiresIn: Int
  public let refreshToken: String
  public let refreshExpiresAt: Date
  public let device: MobileDevice
}

public struct PairingClaimRequest: Codable, Sendable, Equatable {
  public let pairingID: String
  public let code: String
  public let deviceName: String
  public let platform: String
  public let hardwareModel: String?
  public let osVersion: String?
  public let appVersion: String?
  public let pushEnvironment: String

  public init(
    pairingID: String,
    code: String,
    deviceName: String,
    platform: String = "ios",
    hardwareModel: String? = nil,
    osVersion: String? = nil,
    appVersion: String? = nil,
    pushEnvironment: String = "sandbox"
  ) {
    self.pairingID = pairingID
    self.code = code
    self.deviceName = deviceName
    self.platform = platform
    self.hardwareModel = hardwareModel
    self.osVersion = osVersion
    self.appVersion = appVersion
    self.pushEnvironment = pushEnvironment
  }

  enum CodingKeys: String, CodingKey {
    case pairingID = "pairing_id"
    case code
    case deviceName = "device_name"
    case platform
    case hardwareModel = "hardware_model"
    case osVersion = "os_version"
    case appVersion = "app_version"
    case pushEnvironment = "push_environment"
  }
}

public struct RefreshTokenRequest: Codable, Sendable, Equatable {
  public let refreshToken: String
  public let appVersion: String?
  public let osVersion: String?

  public init(refreshToken: String, appVersion: String? = nil, osVersion: String? = nil) {
    self.refreshToken = refreshToken
    self.appVersion = appVersion
    self.osVersion = osVersion
  }
}

public struct BriefItem: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let title: String
  public let itemType: ActionType
  public let destination: Destination
  public let when: Date?
  public let state: String
  public let externalUrl: String?
  public let estimatedMinutes: Int?
  public let executor: ExecutorType
  public let preferredWorker: String?
}

public struct DailyBrief: Codable, Sendable, Equatable {
  public let generatedAt: Date
  public let timezone: String
  public let date: String
  public let events: [BriefItem]
  public let dueTasks: [BriefItem]
  public let overdue: [BriefItem]
  public let needsReview: [BriefItem]
  public let waiting: [BriefItem]
  public let aiReady: [BriefItem]
  public let summary: String
}

public struct DecisionItem: Codable, Sendable, Equatable, Identifiable {
  public var id: String { actionItemId }
  public let actionItemId: String
  public let title: String
  public let score: Double
  public let estimatedMinutes: Int
  public let executor: ExecutorType
  public let state: String
  public let dueAt: Date?
  public let deadlineAt: Date?
  public let reasons: [String]
  public let externalUrl: String?
  public let preferredWorker: String?
}

public struct FollowUp: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let state: String
  public let waitingFor: String
  public let channel: String?
  public let expectedBy: Date?
  public let followUpAt: Date
  public let template: String?
  public let reminderCount: Int
  public let lastRemindedAt: Date?
  public let responseReceivedAt: Date?
  public let createdAt: Date
  public let updatedAt: Date
  public let actionTitle: String?
}

public struct FollowUpResolveRequest: Codable, Sendable, Equatable {
  public let state: String
  public let actor: String
  public let note: String

  public init(state: String, note: String = "", actor: String = "user") {
    self.state = state
    self.note = note
    self.actor = actor
  }
}

public struct DecisionPlan: Codable, Sendable, Equatable {
  public let date: String
  public let generatedAt: Date
  public let availableMinutes: Int
  public let bufferMinutes: Int
  public let plannedMinutes: Int
  public let overloadMinutes: Int
  public let topItems: [DecisionItem]
  public let deferredItems: [DecisionItem]
  public let aiDelegationCandidates: [DecisionItem]
  public let waitingFollowups: [FollowUp]
  public let risks: [String]
  public let summary: String
}

public struct ActivityItem: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let category: String
  public let title: String
  public let subtitle: String?
  public let state: String
  public let entityType: String?
  public let entityId: String?
  public let externalUrl: String?
  public let occurredAt: Date
}

public struct MobileDashboard: Codable, Sendable, Equatable {
  public let generatedAt: Date
  public let serverVersion: String
  public let minimumIosAppVersion: String
  public let reviewCount: Int
  public let waitingCount: Int
  public let aiRunningCount: Int
  public let failedCount: Int
  public let brief: DailyBrief
  public let decision: DecisionPlan
  public let recentActivity: [ActivityItem]
  public let focusSummary: FocusDashboardSummary?
}

public struct Inbox: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let source: String
  public let rawText: String
  public let timezone: String
  public let fingerprint: String
  public let status: String
  public let metadataJson: [String: JSONValue]
  public let createdAt: Date
  public let updatedAt: Date
}

public struct ExternalState: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let provider: String
  public let externalId: String
  public let externalUrl: String?
  public let state: String
  public let payloadJson: [String: JSONValue]
  public let externalUpdatedAt: Date?
  public let lastSyncedAt: Date
  public let syncError: String?
}

public struct WorkerExecution: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let worker: String
  public let state: String
  public let dispatchId: String?
  public let repository: String?
  public let issueNumber: Int?
  public let pullRequestNumber: Int?
  public let workflowRunId: String?
  public let artifactsJson: [String: JSONValue]
  public let outputSummary: String?
  public let error: String?
  public let startedAt: Date?
  public let completedAt: Date?
  public let createdAt: Date
  public let updatedAt: Date
}

public struct ActionItem: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let planId: String
  public var itemType: ActionType
  public var destination: Destination
  public var title: String
  public var description: String
  public let sourceFragment: String
  public var project: String?
  public var repository: String?
  public var assignee: String?
  public var startAt: Date?
  public var endAt: Date?
  public var dueAt: Date?
  public var deadlineAt: Date?
  public var earliestStartAt: Date?
  public var latestFinishAt: Date?
  public var isAllDay: Bool
  public var priority: Int
  public var labels: [String]
  public let confidence: Double
  public var needsReview: Bool
  public var reviewReason: String?
  public var estimatedMinutes: Int?
  public let actualMinutes: Int?
  public var workMode: String
  public var executor: ExecutorType
  public var preferredWorker: String?
  public var energyLevel: String
  public var waitingFor: String?
  public var followUpAt: Date?
  public var dependsOn: [String]
  public let completionEvidence: String?
  public let rescheduleCount: Int
  public let revision: Int
  public let attentionState: String?
  public let state: String
  public let fingerprint: String
  public let externalId: String?
  public let externalUrl: String?
  public let executionPayload: [String: JSONValue]
  public let executionError: String?
  public let registeredAt: Date?
  public let completedAt: Date?
  public let createdAt: Date
  public let updatedAt: Date
  public let externalStates: [ExternalState]
  public let workerExecutions: [WorkerExecution]
  public let followups: [FollowUp]
}

public struct ActionPlan: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let inboxId: String
  public let status: String
  public let parserName: String
  public let summary: String
  public let referenceTime: Date
  public let revision: Int
  public let createdAt: Date
  public let updatedAt: Date
  public let items: [ActionItem]
  public let inbox: Inbox?
  /// Item ids the server left blocked (still `needs_review`, no force override) on the
  /// approve call that produced this plan. Empty for every response that is not the
  /// result of an approve request. Defaulted so older/partial payloads still decode.
  public let blockedItemIds: [String]

  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    id = try container.decode(String.self, forKey: .id)
    inboxId = try container.decode(String.self, forKey: .inboxId)
    status = try container.decode(String.self, forKey: .status)
    parserName = try container.decode(String.self, forKey: .parserName)
    summary = try container.decode(String.self, forKey: .summary)
    referenceTime = try container.decode(Date.self, forKey: .referenceTime)
    revision = try container.decode(Int.self, forKey: .revision)
    createdAt = try container.decode(Date.self, forKey: .createdAt)
    updatedAt = try container.decode(Date.self, forKey: .updatedAt)
    items = try container.decode([ActionItem].self, forKey: .items)
    inbox = try container.decodeIfPresent(Inbox.self, forKey: .inbox)
    blockedItemIds = try container.decodeIfPresent([String].self, forKey: .blockedItemIds) ?? []
  }

  private enum CodingKeys: String, CodingKey {
    case id, inboxId, status, parserName, summary, referenceTime, revision, createdAt, updatedAt,
      items, inbox, blockedItemIds
  }
}

public struct ActionItemPatch: Encodable, Sendable, Equatable {
  private enum Field<Value: Encodable & Sendable & Equatable>: Sendable, Equatable {
    case omitted
    case value(Value)
    case null

    static func from(_ value: Value?) -> Self {
      value.map(Self.value) ?? .null
    }

    var resolved: Value? {
      switch self {
      case .value(let value): value
      case .omitted, .null: nil
      }
    }
  }

  public let expectedRevision: Int

  private var itemTypeField: Field<ActionType> = .omitted
  private var destinationField: Field<Destination> = .omitted
  private var titleField: Field<String> = .omitted
  private var descriptionField: Field<String> = .omitted
  private var projectField: Field<String> = .omitted
  private var repositoryField: Field<String> = .omitted
  private var assigneeField: Field<String> = .omitted
  private var startAtField: Field<Date> = .omitted
  private var endAtField: Field<Date> = .omitted
  private var dueAtField: Field<Date> = .omitted
  private var deadlineAtField: Field<Date> = .omitted
  private var isAllDayField: Field<Bool> = .omitted
  private var priorityField: Field<Int> = .omitted
  private var labelsField: Field<[String]> = .omitted
  private var needsReviewField: Field<Bool> = .omitted
  private var estimatedMinutesField: Field<Int> = .omitted
  private var workModeField: Field<String> = .omitted
  private var executorField: Field<ExecutorType> = .omitted
  private var preferredWorkerField: Field<String> = .omitted
  private var energyLevelField: Field<String> = .omitted
  private var waitingForField: Field<String> = .omitted
  private var followUpAtField: Field<Date> = .omitted

  public var itemType: ActionType? {
    get { itemTypeField.resolved }
    set { itemTypeField = .from(newValue) }
  }
  public var destination: Destination? {
    get { destinationField.resolved }
    set { destinationField = .from(newValue) }
  }
  public var title: String? {
    get { titleField.resolved }
    set { titleField = .from(newValue) }
  }
  public var description: String? {
    get { descriptionField.resolved }
    set { descriptionField = .from(newValue) }
  }
  public var project: String? {
    get { projectField.resolved }
    set { projectField = .from(newValue) }
  }
  public var repository: String? {
    get { repositoryField.resolved }
    set { repositoryField = .from(newValue) }
  }
  public var assignee: String? {
    get { assigneeField.resolved }
    set { assigneeField = .from(newValue) }
  }
  public var startAt: Date? {
    get { startAtField.resolved }
    set { startAtField = .from(newValue) }
  }
  public var endAt: Date? {
    get { endAtField.resolved }
    set { endAtField = .from(newValue) }
  }
  public var dueAt: Date? {
    get { dueAtField.resolved }
    set { dueAtField = .from(newValue) }
  }
  public var deadlineAt: Date? {
    get { deadlineAtField.resolved }
    set { deadlineAtField = .from(newValue) }
  }
  public var isAllDay: Bool? {
    get { isAllDayField.resolved }
    set { isAllDayField = .from(newValue) }
  }
  public var priority: Int? {
    get { priorityField.resolved }
    set { priorityField = .from(newValue) }
  }
  public var labels: [String]? {
    get { labelsField.resolved }
    set { labelsField = .from(newValue) }
  }
  public var needsReview: Bool? {
    get { needsReviewField.resolved }
    set { needsReviewField = .from(newValue) }
  }
  public var estimatedMinutes: Int? {
    get { estimatedMinutesField.resolved }
    set { estimatedMinutesField = .from(newValue) }
  }
  public var workMode: String? {
    get { workModeField.resolved }
    set { workModeField = .from(newValue) }
  }
  public var executor: ExecutorType? {
    get { executorField.resolved }
    set { executorField = .from(newValue) }
  }
  public var preferredWorker: String? {
    get { preferredWorkerField.resolved }
    set { preferredWorkerField = .from(newValue) }
  }
  public var energyLevel: String? {
    get { energyLevelField.resolved }
    set { energyLevelField = .from(newValue) }
  }
  public var waitingFor: String? {
    get { waitingForField.resolved }
    set { waitingForField = .from(newValue) }
  }
  public var followUpAt: Date? {
    get { followUpAtField.resolved }
    set { followUpAtField = .from(newValue) }
  }

  public init(expectedRevision: Int) {
    self.expectedRevision = expectedRevision
  }

  private enum CodingKeys: String, CodingKey {
    case expectedRevision = "expected_revision"
    case itemType = "item_type"
    case destination
    case title
    case description
    case project
    case repository
    case assignee
    case startAt = "start_at"
    case endAt = "end_at"
    case dueAt = "due_at"
    case deadlineAt = "deadline_at"
    case isAllDay = "is_all_day"
    case priority
    case labels
    case needsReview = "needs_review"
    case estimatedMinutes = "estimated_minutes"
    case workMode = "work_mode"
    case executor
    case preferredWorker = "preferred_worker"
    case energyLevel = "energy_level"
    case waitingFor = "waiting_for"
    case followUpAt = "follow_up_at"
  }

  public func encode(to encoder: Encoder) throws {
    var container = encoder.container(keyedBy: CodingKeys.self)
    try container.encode(expectedRevision, forKey: .expectedRevision)
    try encode(itemTypeField, in: &container, forKey: .itemType)
    try encode(destinationField, in: &container, forKey: .destination)
    try encode(titleField, in: &container, forKey: .title)
    try encode(descriptionField, in: &container, forKey: .description)
    try encode(projectField, in: &container, forKey: .project)
    try encode(repositoryField, in: &container, forKey: .repository)
    try encode(assigneeField, in: &container, forKey: .assignee)
    try encode(startAtField, in: &container, forKey: .startAt)
    try encode(endAtField, in: &container, forKey: .endAt)
    try encode(dueAtField, in: &container, forKey: .dueAt)
    try encode(deadlineAtField, in: &container, forKey: .deadlineAt)
    try encode(isAllDayField, in: &container, forKey: .isAllDay)
    try encode(priorityField, in: &container, forKey: .priority)
    try encode(labelsField, in: &container, forKey: .labels)
    try encode(needsReviewField, in: &container, forKey: .needsReview)
    try encode(estimatedMinutesField, in: &container, forKey: .estimatedMinutes)
    try encode(workModeField, in: &container, forKey: .workMode)
    try encode(executorField, in: &container, forKey: .executor)
    try encode(preferredWorkerField, in: &container, forKey: .preferredWorker)
    try encode(energyLevelField, in: &container, forKey: .energyLevel)
    try encode(waitingForField, in: &container, forKey: .waitingFor)
    try encode(followUpAtField, in: &container, forKey: .followUpAt)
  }

  private func encode<Value: Encodable & Sendable & Equatable>(
    _ field: Field<Value>,
    in container: inout KeyedEncodingContainer<CodingKeys>,
    forKey key: CodingKeys
  ) throws {
    switch field {
    case .omitted:
      break
    case .value(let value):
      try container.encode(value, forKey: key)
    case .null:
      try container.encodeNil(forKey: key)
    }
  }
}

public struct PlanApprovalRequest: Codable, Sendable, Equatable {
  public let itemIds: [String]?
  public let actor: String
  public let forceReviewItems: Bool
  public let expectedPlanRevision: Int?

  public init(
    itemIds: [String]? = nil,
    actor: String = "ios-user",
    forceReviewItems: Bool = false,
    expectedPlanRevision: Int? = nil
  ) {
    self.itemIds = itemIds
    self.actor = actor
    self.forceReviewItems = forceReviewItems
    self.expectedPlanRevision = expectedPlanRevision
  }
}

public struct PlanRejectRequest: Codable, Sendable, Equatable {
  public let itemIds: [String]?
  public let actor: String
  public let reason: String
  public let expectedPlanRevision: Int?

  public init(
    itemIds: [String]? = nil,
    actor: String = "ios-user",
    reason: String = "",
    expectedPlanRevision: Int? = nil
  ) {
    self.itemIds = itemIds
    self.actor = actor
    self.reason = reason
    self.expectedPlanRevision = expectedPlanRevision
  }
}

public struct PlanExecuteRequest: Codable, Sendable, Equatable {
  public let itemIds: [String]?
  public let actor: String
  public let retryFailed: Bool
  public let drainInline: Bool?
  public let expectedPlanRevision: Int?

  public init(
    itemIds: [String]? = nil,
    actor: String = "ios-user",
    retryFailed: Bool = false,
    drainInline: Bool? = nil,
    expectedPlanRevision: Int? = nil
  ) {
    self.itemIds = itemIds
    self.actor = actor
    self.retryFailed = retryFailed
    self.drainInline = drainInline
    self.expectedPlanRevision = expectedPlanRevision
  }
}

public struct ExecutionError: Codable, Sendable, Equatable, Identifiable {
  public var id: String { itemId }
  public let itemId: String
  public let title: String
  public let error: String
  public let attempts: Int
}

public struct ExecutionSummary: Codable, Sendable, Equatable {
  public let planId: String
  public let planStatus: String
  public let completed: Int
  public let registered: Int
  public let actionCompleted: Int
  public let queued: Int
  public let failed: Int
  public let skippedDuplicate: Int
  public let pending: Int
  public let items: [ActionItem]
  /// Queued/executing items that still carry an unresolved execution error (worker retrying
  /// after a transient failure). Absent on older servers; defaults to 0 so a 200 response never
  /// silently reads as fully successful while work is actually still failing in the background.
  public let retrying: Int
  /// Up to 20 items with a recorded execution error. Same backward-compat reasoning as
  /// `retrying`.
  public let errors: [ExecutionError]

  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    planId = try container.decode(String.self, forKey: .planId)
    planStatus = try container.decode(String.self, forKey: .planStatus)
    completed = try container.decode(Int.self, forKey: .completed)
    registered = try container.decode(Int.self, forKey: .registered)
    actionCompleted = try container.decode(Int.self, forKey: .actionCompleted)
    queued = try container.decode(Int.self, forKey: .queued)
    failed = try container.decode(Int.self, forKey: .failed)
    skippedDuplicate = try container.decode(Int.self, forKey: .skippedDuplicate)
    pending = try container.decode(Int.self, forKey: .pending)
    items = try container.decode([ActionItem].self, forKey: .items)
    retrying = try container.decodeIfPresent(Int.self, forKey: .retrying) ?? 0
    errors = try container.decodeIfPresent([ExecutionError].self, forKey: .errors) ?? []
  }

  private enum CodingKeys: String, CodingKey {
    case planId, planStatus, completed, registered, actionCompleted, queued, failed,
      skippedDuplicate, pending, items, retrying, errors
  }
}

public struct CaptureInput: Codable, Sendable, Equatable, Identifiable {
  public var id: String { clientCaptureId }
  public let clientCaptureId: String
  public let text: String
  public let source: String
  public let timezone: String
  public let referenceTime: Date?
  public let metadata: [String: JSONValue]

  public init(
    clientCaptureId: String = UUID().uuidString.lowercased(),
    text: String,
    source: String = "ios",
    timezone: String = TimeZone.current.identifier,
    referenceTime: Date? = Date(),
    metadata: [String: JSONValue] = [:]
  ) {
    self.clientCaptureId = clientCaptureId
    self.text = text
    self.source = source
    self.timezone = timezone
    self.referenceTime = referenceTime
    self.metadata = metadata
  }
}

public struct CaptureBatchRequest: Codable, Sendable, Equatable {
  public let captures: [CaptureInput]
}

public struct CaptureReceipt: Codable, Sendable, Equatable, Identifiable {
  public var id: String { clientCaptureId }
  public let clientCaptureId: String
  public let status: String
  public let planId: String?
  public let error: String?
  public let deduplicated: Bool
}

public struct CaptureBatchResponse: Codable, Sendable, Equatable {
  public let accepted: Int
  public let processed: Int
  public let duplicate: Int
  public let failed: Int
  public let receipts: [CaptureReceipt]
}

public struct MobileChange: Codable, Sendable, Equatable, Identifiable {
  public var id: String { auditId }
  public let auditId: String
  public let entityType: String
  public let entityId: String
  public let eventType: String
  public let actor: String
  public let occurredAt: Date
  public let payload: [String: JSONValue]
}

public struct ChangesResponse: Codable, Sendable, Equatable {
  public let nextCursor: String?
  public let hasMore: Bool
  public let changes: [MobileChange]
  public let deleted: [[String: String]]
}

public struct PushTokenRequest: Codable, Sendable, Equatable {
  public let token: String
  public let environment: String

  public init(token: String, environment: String) {
    self.token = token
    self.environment = environment
  }
}

/// Mirrors the server's 7 notification kinds exactly (`server/action_hub/schemas.py`). Decoded
/// and encoded as a plain struct -- not a `[String: Bool]` dictionary -- because
/// `JSONDecoder.keyDecodingStrategy = .convertFromSnakeCase` rewrites dictionary *values'* keys
/// too, which silently turned every lookup by snake_case key into a permanent miss (P1-1). Only
/// 3 of the 7 kinds are actually published by the server today; the rest round-trip so a save
/// never resets them, but the UI hides the ones nothing ever sends (see SettingsView).
public struct NotificationPreferences: Codable, Sendable, Equatable {
  public var reviewRequired = true
  public var aiStatus = true
  public var followUpDue = true
  public var deadlineRisk = true
  public var connectorFailure = true
  public var focusReady = true
  public var focusOverrun = true

  public init() {}

  // Swift's synthesized `Decodable` init requires every key present regardless of a property's
  // declared default -- it does NOT fall back to the default for a missing key unless the
  // property type is Optional. A device that has never customized preferences (or an older/newer
  // server) can legitimately send `"notification_preferences": {}` or a subset of the 7 fields,
  // so this must decode leniently instead of throwing `keyNotFound`.
  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    reviewRequired = try container.decodeIfPresent(Bool.self, forKey: .reviewRequired) ?? true
    aiStatus = try container.decodeIfPresent(Bool.self, forKey: .aiStatus) ?? true
    followUpDue = try container.decodeIfPresent(Bool.self, forKey: .followUpDue) ?? true
    deadlineRisk = try container.decodeIfPresent(Bool.self, forKey: .deadlineRisk) ?? true
    connectorFailure = try container.decodeIfPresent(Bool.self, forKey: .connectorFailure) ?? true
    focusReady = try container.decodeIfPresent(Bool.self, forKey: .focusReady) ?? true
    focusOverrun = try container.decodeIfPresent(Bool.self, forKey: .focusOverrun) ?? true
  }

  private enum CodingKeys: String, CodingKey {
    case reviewRequired, aiStatus, followUpDue, deadlineRisk, connectorFailure, focusReady,
      focusOverrun
  }
}

public enum JSONValue: Codable, Sendable, Equatable {
  case string(String)
  case number(Double)
  case bool(Bool)
  case object([String: JSONValue])
  case array([JSONValue])
  case null

  public init(from decoder: Decoder) throws {
    let container = try decoder.singleValueContainer()
    if container.decodeNil() {
      self = .null
    } else if let value = try? container.decode(Bool.self) {
      self = .bool(value)
    } else if let value = try? container.decode(Double.self) {
      self = .number(value)
    } else if let value = try? container.decode(String.self) {
      self = .string(value)
    } else if let value = try? container.decode([String: JSONValue].self) {
      self = .object(value)
    } else if let value = try? container.decode([JSONValue].self) {
      self = .array(value)
    } else {
      throw DecodingError.dataCorruptedError(
        in: container, debugDescription: "Unsupported JSON value")
    }
  }

  public func encode(to encoder: Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .string(let value): try container.encode(value)
    case .number(let value): try container.encode(value)
    case .bool(let value): try container.encode(value)
    case .object(let value): try container.encode(value)
    case .array(let value): try container.encode(value)
    case .null: try container.encodeNil()
    }
  }
}
