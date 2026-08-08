import Foundation

public struct MobileRefreshSnapshot: Sendable, Equatable {
  public let dashboard: MobileDashboard
  public let review: [ActionPlan]
  public let activity: [ActivityItem]
  public let triage: TriageResponse
  public let matrix: MatrixResponse
  public let big3: DualBig3Response
  public let activeFocus: FocusSession?

  public init(
    dashboard: MobileDashboard,
    review: [ActionPlan],
    activity: [ActivityItem],
    triage: TriageResponse,
    matrix: MatrixResponse,
    big3: DualBig3Response,
    activeFocus: FocusSession?
  ) {
    self.dashboard = dashboard
    self.review = review
    self.activity = activity
    self.triage = triage
    self.matrix = matrix
    self.big3 = big3
    self.activeFocus = activeFocus
  }
}
