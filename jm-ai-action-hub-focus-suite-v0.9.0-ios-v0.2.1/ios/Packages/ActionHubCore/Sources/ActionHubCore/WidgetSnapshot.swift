import Foundation

public struct WidgetSnapshot: Codable, Sendable, Equatable {
  public let generatedAt: Date
  public let reviewCount: Int
  public let waitingCount: Int
  public let aiRunningCount: Int
  public let failedCount: Int
  public let overloadMinutes: Int
  public let topTitles: [String]
  public let untriagedCount: Int
  public let humanBig3Titles: [String]
  public let aiBig3Titles: [String]
  public let activeFocusTitle: String?
  public let activeFocusRemainingSeconds: Int?
  public let activeFocusTrafficState: String?

  private enum CodingKeys: String, CodingKey {
    case generatedAt
    case reviewCount
    case waitingCount
    case aiRunningCount
    case failedCount
    case overloadMinutes
    case topTitles
    case untriagedCount
    case humanBig3Titles
    case aiBig3Titles
    case activeFocusTitle
    case activeFocusRemainingSeconds
    case activeFocusTrafficState
  }

  public init(dashboard: MobileDashboard) {
    generatedAt = dashboard.generatedAt
    reviewCount = dashboard.reviewCount
    waitingCount = dashboard.waitingCount
    aiRunningCount = dashboard.aiRunningCount
    failedCount = dashboard.failedCount
    overloadMinutes = dashboard.decision.overloadMinutes
    topTitles = Array(dashboard.decision.topItems.prefix(3).map(\.title))
    untriagedCount = dashboard.focusSummary?.untriagedCount ?? 0
    humanBig3Titles = Array(
      (dashboard.focusSummary?.humanBig3 ?? []).compactMap { $0.action?.title }.prefix(3))
    aiBig3Titles = Array(
      (dashboard.focusSummary?.aiBig3 ?? []).compactMap { $0.action?.title }.prefix(3))
    activeFocusTitle = dashboard.focusSummary?.activeFocus?.action?.title
    activeFocusRemainingSeconds = dashboard.focusSummary?.activeFocus?.remainingSeconds
    activeFocusTrafficState = dashboard.focusSummary?.activeFocus?.trafficState.rawValue
  }

  public init(
    generatedAt: Date = Date(),
    reviewCount: Int = 0,
    waitingCount: Int = 0,
    aiRunningCount: Int = 0,
    failedCount: Int = 0,
    overloadMinutes: Int = 0,
    topTitles: [String] = [],
    untriagedCount: Int = 0,
    humanBig3Titles: [String] = [],
    aiBig3Titles: [String] = [],
    activeFocusTitle: String? = nil,
    activeFocusRemainingSeconds: Int? = nil,
    activeFocusTrafficState: String? = nil
  ) {
    self.generatedAt = generatedAt
    self.reviewCount = reviewCount
    self.waitingCount = waitingCount
    self.aiRunningCount = aiRunningCount
    self.failedCount = failedCount
    self.overloadMinutes = overloadMinutes
    self.topTitles = topTitles
    self.untriagedCount = untriagedCount
    self.humanBig3Titles = humanBig3Titles
    self.aiBig3Titles = aiBig3Titles
    self.activeFocusTitle = activeFocusTitle
    self.activeFocusRemainingSeconds = activeFocusRemainingSeconds
    self.activeFocusTrafficState = activeFocusTrafficState
  }

  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    generatedAt = try container.decodeIfPresent(Date.self, forKey: .generatedAt) ?? Date()
    reviewCount = try container.decodeIfPresent(Int.self, forKey: .reviewCount) ?? 0
    waitingCount = try container.decodeIfPresent(Int.self, forKey: .waitingCount) ?? 0
    aiRunningCount = try container.decodeIfPresent(Int.self, forKey: .aiRunningCount) ?? 0
    failedCount = try container.decodeIfPresent(Int.self, forKey: .failedCount) ?? 0
    overloadMinutes = try container.decodeIfPresent(Int.self, forKey: .overloadMinutes) ?? 0
    topTitles = try container.decodeIfPresent([String].self, forKey: .topTitles) ?? []
    untriagedCount = try container.decodeIfPresent(Int.self, forKey: .untriagedCount) ?? 0
    humanBig3Titles = try container.decodeIfPresent([String].self, forKey: .humanBig3Titles) ?? []
    aiBig3Titles = try container.decodeIfPresent([String].self, forKey: .aiBig3Titles) ?? []
    activeFocusTitle = try container.decodeIfPresent(String.self, forKey: .activeFocusTitle)
    activeFocusRemainingSeconds = try container.decodeIfPresent(
      Int.self, forKey: .activeFocusRemainingSeconds)
    activeFocusTrafficState = try container.decodeIfPresent(
      String.self, forKey: .activeFocusTrafficState)
  }
}
