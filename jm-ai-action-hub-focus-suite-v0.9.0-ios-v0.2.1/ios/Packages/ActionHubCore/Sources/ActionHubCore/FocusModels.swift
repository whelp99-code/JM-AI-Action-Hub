import Foundation

public enum Quadrant: String, Codable, Sendable, CaseIterable, Identifiable {
  case q1, q2, q3, q4
  public var id: String { rawValue }

  public var title: String {
    switch self {
    case .q1: "실행"
    case .q2: "계획"
    case .q3: "위임"
    case .q4: "보류"
    }
  }

  public var subtitle: String {
    switch self {
    case .q1: "중요하고 긴급"
    case .q2: "중요하지만 여유 있음"
    case .q3: "긴급하지만 위임 가능"
    case .q4: "지금 하지 않음"
    }
  }
}

public enum FocusTrafficState: String, Codable, Sendable, CaseIterable {
  case green, yellow, red
}

public enum FocusSessionState: String, Codable, Sendable, CaseIterable {
  case running, paused, completed, abandoned
}

public struct PriorityAssessment: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let importanceScore: Double
  public let urgencyScore: Double
  public let quadrant: Quadrant
  public let source: String
  public let confidence: Double
  public let reasonsJson: [String]
  public let userOverridden: Bool
  public let createdAt: Date
  public let updatedAt: Date
}

public struct FocusActionSummary: Codable, Sendable, Equatable, Identifiable {
  public var id: String { actionItemId }
  public let actionItemId: String
  public let planId: String
  public let title: String
  public let description: String
  public let project: String?
  public let repository: String?
  public let priority: Int
  public let estimatedMinutes: Int
  public let actualMinutes: Int?
  public let executor: ExecutorType
  public let preferredWorker: String?
  public let state: String
  public let attentionState: String
  public let dueAt: Date?
  public let deadlineAt: Date?
  public let externalUrl: String?
  public let assessment: PriorityAssessment?
}

public struct TriageResponse: Codable, Sendable, Equatable {
  public let generatedAt: Date
  public let total: Int
  public let items: [FocusActionSummary]
}

public struct ClassifyActionRequest: Codable, Sendable, Equatable {
  public let quadrant: Quadrant
  public let importanceScore: Double?
  public let urgencyScore: Double?
  public let reason: String?
  public let expectedItemRevision: Int?
  public let actor: String

  public init(
    quadrant: Quadrant,
    importanceScore: Double? = nil,
    urgencyScore: Double? = nil,
    reason: String? = nil,
    expectedItemRevision: Int? = nil,
    actor: String = "user"
  ) {
    self.quadrant = quadrant
    self.importanceScore = importanceScore
    self.urgencyScore = urgencyScore
    self.reason = reason
    self.expectedItemRevision = expectedItemRevision
    self.actor = actor
  }
}

public struct MatrixResponse: Codable, Sendable, Equatable {
  public let generatedAt: Date
  public let counts: [String: Int]
  public let q1: [FocusActionSummary]
  public let q2: [FocusActionSummary]
  public let q3: [FocusActionSummary]
  public let q4: [FocusActionSummary]
  public let untriagedCount: Int

  public func items(for quadrant: Quadrant) -> [FocusActionSummary] {
    switch quadrant {
    case .q1: q1
    case .q2: q2
    case .q3: q3
    case .q4: q4
    }
  }
}

public struct DailyCommitment: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let commitmentDate: String
  public let actionItemId: String
  public let ownerType: String
  public let rank: Int
  public let committedMinutes: Int
  public let state: String
  public let createdAt: Date
  public let updatedAt: Date
  public let action: FocusActionSummary?
}

public struct DualBig3Request: Codable, Sendable, Equatable {
  public let targetDate: String?
  public let humanItemIds: [String]
  public let aiItemIds: [String]
  public let availableMinutes: Int?
  public let actor: String

  public init(
    targetDate: String? = nil,
    humanItemIds: [String] = [],
    aiItemIds: [String] = [],
    availableMinutes: Int? = nil,
    actor: String = "user"
  ) {
    self.targetDate = targetDate
    self.humanItemIds = humanItemIds
    self.aiItemIds = aiItemIds
    self.availableMinutes = availableMinutes
    self.actor = actor
  }
}

public struct DualBig3Response: Codable, Sendable, Equatable {
  public let date: String
  public let availableMinutes: Int
  public let humanCommittedMinutes: Int
  public let aiCommittedMinutes: Int
  public let overloadMinutes: Int
  public let human: [DailyCommitment]
  public let ai: [DailyCommitment]
  public let warnings: [String]
}

public struct MicroStepInput: Codable, Sendable, Equatable {
  public let title: String
  public let executor: ExecutorType
  public let preferredWorker: String?
  public let estimatedMinutes: Int?

  public init(
    title: String,
    executor: ExecutorType = .human,
    preferredWorker: String? = nil,
    estimatedMinutes: Int? = nil
  ) {
    self.title = title
    self.executor = executor
    self.preferredWorker = preferredWorker
    self.estimatedMinutes = estimatedMinutes
  }
}

public struct DecomposeActionRequest: Codable, Sendable, Equatable {
  public let maxSteps: Int
  public let replaceExisting: Bool
  public let steps: [MicroStepInput]?
  public let actor: String

  public init(
    maxSteps: Int = 5,
    replaceExisting: Bool = true,
    steps: [MicroStepInput]? = nil,
    actor: String = "user"
  ) {
    self.maxSteps = maxSteps
    self.replaceExisting = replaceExisting
    self.steps = steps
    self.actor = actor
  }
}

public struct MicroStep: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let position: Int
  public let title: String
  public let executor: ExecutorType
  public let preferredWorker: String?
  public let estimatedMinutes: Int?
  public let state: String
  public let completionNote: String?
  public let createdAt: Date
  public let updatedAt: Date
}

public struct MicroStepUpdateRequest: Codable, Sendable, Equatable {
  public let title: String?
  public let executor: ExecutorType?
  public let preferredWorker: String?
  public let estimatedMinutes: Int?
  public let state: String?
  public let completionNote: String?
  public let actor: String

  public init(
    title: String? = nil,
    executor: ExecutorType? = nil,
    preferredWorker: String? = nil,
    estimatedMinutes: Int? = nil,
    state: String? = nil,
    completionNote: String? = nil,
    actor: String = "user"
  ) {
    self.title = title
    self.executor = executor
    self.preferredWorker = preferredWorker
    self.estimatedMinutes = estimatedMinutes
    self.state = state
    self.completionNote = completionNote
    self.actor = actor
  }
}

public struct FocusSessionStartRequest: Codable, Sendable, Equatable {
  public let actionItemId: String
  public let plannedMinutes: Int
  public let actor: String

  public init(actionItemId: String, plannedMinutes: Int = 25, actor: String = "user") {
    self.actionItemId = actionItemId
    self.plannedMinutes = plannedMinutes
    self.actor = actor
  }
}

public struct FocusSessionUpdateRequest: Codable, Sendable, Equatable {
  public let action: String
  public let expectedRevision: Int?
  public let extensionMinutes: Int?
  public let completionNote: String?
  public let markActionCompleted: Bool
  public let actor: String

  public init(
    action: String,
    expectedRevision: Int? = nil,
    extensionMinutes: Int? = nil,
    completionNote: String? = nil,
    markActionCompleted: Bool = false,
    actor: String = "user"
  ) {
    self.action = action
    self.expectedRevision = expectedRevision
    self.extensionMinutes = extensionMinutes
    self.completionNote = completionNote
    self.markActionCompleted = markActionCompleted
    self.actor = actor
  }
}

public struct FocusSession: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let plannedMinutes: Int
  public let extensionMinutes: Int
  public let totalPlannedMinutes: Int
  public let elapsedSeconds: Int
  public let remainingSeconds: Int
  public let progress: Double
  public let state: FocusSessionState
  public let trafficState: FocusTrafficState
  public let startedAt: Date
  public let pausedAt: Date?
  public let pausedSeconds: Int
  public let pauseCount: Int
  public let endedAt: Date?
  public let actualMinutes: Int?
  public let completionNote: String?
  public let startedBy: String
  public let revision: Int
  public let createdAt: Date
  public let updatedAt: Date
  public let action: FocusActionSummary?
  public let microSteps: [MicroStep]
}

public struct DayCloseDecisionInput: Codable, Sendable, Equatable {
  public let actionItemId: String
  public let decision: String
  public let reason: String
  public let toDate: String?
  public let waitingFor: String?
  public let followUpAt: Date?
  public let executor: ExecutorType?

  public init(
    actionItemId: String,
    decision: String,
    reason: String = "",
    toDate: String? = nil,
    waitingFor: String? = nil,
    followUpAt: Date? = nil,
    executor: ExecutorType? = nil
  ) {
    self.actionItemId = actionItemId
    self.decision = decision
    self.reason = reason
    self.toDate = toDate
    self.waitingFor = waitingFor
    self.followUpAt = followUpAt
    self.executor = executor
  }
}

public struct DayCloseRequest: Codable, Sendable, Equatable {
  public let targetDate: String?
  public let decisions: [DayCloseDecisionInput]
  public let actor: String

  public init(
    targetDate: String? = nil,
    decisions: [DayCloseDecisionInput],
    actor: String = "user"
  ) {
    self.targetDate = targetDate
    self.decisions = decisions
    self.actor = actor
  }
}

public struct CarryOverDecision: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let actionItemId: String
  public let fromDate: String
  public let toDate: String?
  public let decision: String
  public let reason: String
  public let actor: String
  public let resultJson: [String: JSONValue]
  public let createdAt: Date
}

public struct DayCloseResponse: Codable, Sendable, Equatable {
  public let date: String
  public let processed: Int
  public let decisions: [CarryOverDecision]
  public let warnings: [String]
}

public struct FocusWeeklyReport: Codable, Sendable, Equatable {
  public let periodStart: String
  public let periodEnd: String
  public let generatedAt: Date
  public let totalSessions: Int
  public let completedSessions: Int
  public let focusMinutes: Int
  public let humanBig3Total: Int
  public let humanBig3Completed: Int
  public let aiBig3Total: Int
  public let aiBig3Completed: Int
  public let big3CompletionRate: Double
  public let quadrantFocusMinutes: [String: Int]
  public let trafficDistribution: [String: Int]
  public let carryOverCount: Int
  public let averageEstimateAccuracy: Double?
  public let q2InvestmentMinutes: Int
  public let q3DelegatedCount: Int
  public let recommendations: [String]
  public let summary: String
}

public struct FocusDashboardSummary: Codable, Sendable, Equatable {
  public let matrixCounts: [String: Int]
  public let humanBig3: [DailyCommitment]
  public let aiBig3: [DailyCommitment]
  public let activeFocus: FocusSession?
  public let untriagedCount: Int
}
