import ActionHubCore
import Foundation

#if canImport(ActivityKit)
  import ActivityKit

  actor FocusLiveActivityManager {
    func start(session: FocusSession) async {
      guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
      await end()
      let attributes = FocusActivityAttributes(
        actionItemId: session.actionItemId,
        title: session.action?.title ?? "집중 세션",
        plannedMinutes: session.totalPlannedMinutes)
      let state = contentState(session)
      do {
        _ = try Activity.request(
          attributes: attributes,
          content: ActivityContent(state: state, staleDate: Date().addingTimeInterval(60)),
          pushType: nil)
      } catch {
        // Live Activity is an optional presentation layer. The server session remains authoritative.
      }
    }

    func update(session: FocusSession) async {
      guard let activity = Activity<FocusActivityAttributes>.activities.first else {
        if session.state == .running || session.state == .paused { await start(session: session) }
        return
      }
      await activity.update(
        ActivityContent(state: contentState(session), staleDate: Date().addingTimeInterval(60)))
    }

    func end(finalSession: FocusSession? = nil) async {
      for activity in Activity<FocusActivityAttributes>.activities {
        let state =
          finalSession.map(contentState)
          ?? FocusActivityAttributes.ContentState(
            state: "completed", trafficState: "green", remainingSeconds: 0,
            elapsedSeconds: 0, progress: 1)
        await activity.end(
          ActivityContent(state: state, staleDate: nil), dismissalPolicy: .immediate)
      }
    }

    private func contentState(_ session: FocusSession) -> FocusActivityAttributes.ContentState {
      .init(
        state: session.state.rawValue,
        trafficState: session.trafficState.rawValue,
        remainingSeconds: session.remainingSeconds,
        elapsedSeconds: session.elapsedSeconds,
        progress: session.progress)
    }
  }
#else
  actor FocusLiveActivityManager {
    func start(session: FocusSession) async {}
    func update(session: FocusSession) async {}
    func end(finalSession: FocusSession? = nil) async {}
  }
#endif
