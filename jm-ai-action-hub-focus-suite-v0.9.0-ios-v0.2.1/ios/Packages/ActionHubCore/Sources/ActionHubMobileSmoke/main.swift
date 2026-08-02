import ActionHubCore
import Foundation

@main
struct ActionHubMobileSmoke {
  static func main() async {
    do {
      let arguments = CommandLine.arguments
      guard arguments.count >= 2 else {
        throw SmokeError.usage("usage: action-hub-mobile-smoke <pairing-payload-file>")
      }
      let payloadText = try String(contentsOfFile: arguments[1], encoding: .utf8)
      let payload = try PairingPayload.parse(payloadText)
      let store = InMemoryCredentialStore()
      let session = MobileSession(store: store)
      let device = try await session.pair(
        payload: payload,
        deviceInfo: MobileDeviceInfo(
          name: "Linux Swift Contract Smoke",
          hardwareModel: "contract-runner",
          osVersion: ProcessInfo.processInfo.operatingSystemVersionString,
          appVersion: "0.2.1",
          pushEnvironment: "sandbox"
        )
      )
      let before = try await session.dashboard()
      let capture = CaptureInput(
        clientCaptureId: UUID().uuidString.lowercased(),
        text: "내일 오전 10시 모바일 계약 검증 미팅, 미팅 전에 API 계약 확인",
        source: "swift-contract-smoke",
        timezone: "Asia/Seoul",
        referenceTime: Date()
      )
      let uploaded = try await session.uploadCaptures([capture])
      guard let receipt = uploaded.receipts.first, let planId = receipt.planId else {
        throw SmokeError.invalidResponse("capture did not produce a plan")
      }
      var plan = try await session.plan(id: planId)
      if let first = plan.items.first {
        var patch = ActionItemPatch(expectedRevision: first.revision)
        patch.title = "모바일 계약 검증: \(first.title)"
        plan = try await session.updateItem(planId: plan.id, itemId: first.id, patch: patch)
      }
      plan = try await session.approve(
        planId: plan.id,
        request: PlanApprovalRequest(
          actor: "swift-contract-smoke",
          forceReviewItems: true,
          expectedPlanRevision: plan.revision
        )
      )
      let executed = try await session.execute(
        planId: plan.id,
        request: PlanExecuteRequest(
          actor: "swift-contract-smoke",
          expectedPlanRevision: plan.revision
        )
      )
      guard let focusItem = plan.items.first else {
        throw SmokeError.invalidResponse("plan did not contain an action item")
      }
      _ = try await session.classifyFocusAction(
        itemId: focusItem.id,
        request: ClassifyActionRequest(quadrant: .q1, reason: "Swift E2E 분류")
      )
      let commitments = try await session.setBig3(
        DualBig3Request(humanItemIds: [focusItem.id], availableMinutes: 240))
      let microSteps = try await session.decomposeFocusAction(itemId: focusItem.id)
      var focus = try await session.startFocusSession(
        FocusSessionStartRequest(actionItemId: focusItem.id, plannedMinutes: 10))
      focus = try await session.updateFocusSession(
        id: focus.id,
        request: FocusSessionUpdateRequest(action: "pause", expectedRevision: focus.revision))
      focus = try await session.updateFocusSession(
        id: focus.id,
        request: FocusSessionUpdateRequest(action: "resume", expectedRevision: focus.revision))
      focus = try await session.updateFocusSession(
        id: focus.id,
        request: FocusSessionUpdateRequest(
          action: "complete", expectedRevision: focus.revision,
          completionNote: "Swift live contract smoke", markActionCompleted: true))
      let matrix = try await session.focusMatrix()
      let focusReport = try await session.focusWeeklyReport()
      let activity = try await session.activity(limit: 10)
      let changes = try await session.changes(limit: 50)
      let after = try await session.dashboard()

      let result: [String: Any] = [
        "device_id": device.id,
        "server_version": before.serverVersion,
        "plan_id": plan.id,
        "capture_status": receipt.status,
        "execution_completed": executed.completed,
        "execution_failed": executed.failed,
        "activity_count": activity.count,
        "change_count": changes.changes.count,
        "review_count_before": before.reviewCount,
        "review_count_after": after.reviewCount,
        "focus_state": focus.state.rawValue,
        "focus_microsteps": microSteps.count,
        "human_big3": commitments.human.count,
        "matrix_q1": matrix.q1.count,
        "focus_report_sessions": focusReport.totalSessions,
      ]
      let data = try JSONSerialization.data(
        withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
      print(String(decoding: data, as: UTF8.self))
    } catch {
      FileHandle.standardError.write(Data("MOBILE_CONTRACT_SMOKE_FAILED: \(error)\n".utf8))
      Foundation.exit(1)
    }
  }
}

enum SmokeError: Error, CustomStringConvertible {
  case usage(String)
  case invalidResponse(String)

  var description: String {
    switch self {
    case .usage(let value), .invalidResponse(let value): value
    }
  }
}
