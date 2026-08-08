#if canImport(ActivityKit) && os(iOS)
  import ActivityKit
  import Foundation

  public struct FocusActivityAttributes: ActivityAttributes, Sendable {
    public struct ContentState: Codable, Hashable, Sendable {
      public let state: String
      public let trafficState: String
      public let remainingSeconds: Int
      public let elapsedSeconds: Int
      public let progress: Double
      public let updatedAt: Date

      public init(
        state: String,
        trafficState: String,
        remainingSeconds: Int,
        elapsedSeconds: Int,
        progress: Double,
        updatedAt: Date = Date()
      ) {
        self.state = state
        self.trafficState = trafficState
        self.remainingSeconds = remainingSeconds
        self.elapsedSeconds = elapsedSeconds
        self.progress = progress
        self.updatedAt = updatedAt
      }
    }

    public let actionItemId: String
    public let title: String
    public let plannedMinutes: Int

    public init(actionItemId: String, title: String, plannedMinutes: Int) {
      self.actionItemId = actionItemId
      self.title = title
      self.plannedMinutes = plannedMinutes
    }
  }
#endif
