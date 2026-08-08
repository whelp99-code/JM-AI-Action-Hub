import ActionHubCore
import Foundation
import os

#if canImport(ActivityKit)
  import ActivityKit

  actor FocusLiveActivityManager {
    private let logger = Logger(subsystem: "com.jmactionhub.ios", category: "FocusLiveActivity")

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
        // Live Activity is an optional presentation layer, so this is not surfaced to the user
        // and the server session remains authoritative -- but a silent catch here previously
        // gave no signal at all when the Dynamic Island widget just never showed up.
        logger.error("Activity.request failed: \(String(describing: error))")
      }
    }

    func update(session: FocusSession) async {
      let activities = Activity<FocusActivityAttributes>.activities
      // Match by the item the activity was actually started for. `.first` used to grab
      // whichever activity happened to exist, so an orphaned activity from a previous/different
      // session could get overwritten with this session's timer and title.
      let match = activities.first { $0.attributes.actionItemId == session.actionItemId }
      if let activity = match {
        await activity.update(
          ActivityContent(state: contentState(session), staleDate: Date().addingTimeInterval(60)))
        return
      }
      if !activities.isEmpty {
        // Whatever is currently showing belongs to a different item; clear it before deciding
        // whether this session needs a fresh one.
        await end()
      }
      if session.state == .running || session.state == .paused { await start(session: session) }
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
