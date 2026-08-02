import XCTest

@testable import ActionHubCore

final class FocusModelCodingTests: XCTestCase {
  func testTriageAndAssessmentDecodeFromServerContract() throws {
    let data = Data(Self.triageJSON.utf8)
    let triage = try ActionHubJSON.decoder().decode(TriageResponse.self, from: data)
    XCTAssertEqual(triage.total, 1)
    let item = try XCTUnwrap(triage.items.first)
    XCTAssertEqual(item.title, "고객 제안서 작성")
    XCTAssertEqual(item.estimatedMinutes, 120)
    XCTAssertEqual(item.assessment?.quadrant, .q2)
    XCTAssertEqual(item.assessment?.reasonsJson, ["핵심 프로젝트", "금요일 마감"])
  }

  func testFocusSessionAndMicrostepsDecode() throws {
    let session = try ActionHubJSON.decoder().decode(
      FocusSession.self, from: Data(Self.focusSessionJSON.utf8))
    XCTAssertEqual(session.state, .running)
    XCTAssertEqual(session.trafficState, .yellow)
    XCTAssertEqual(session.totalPlannedMinutes, 50)
    XCTAssertEqual(session.microSteps.count, 2)
    XCTAssertEqual(session.microSteps.last?.executor, .ai)
  }

  func testFocusRequestsEncodeSnakeCaseFields() throws {
    let request = DualBig3Request(
      humanItemIds: ["human-1"], aiItemIds: ["ai-1"], availableMinutes: 300)
    let data = try ActionHubJSON.encoder().encode(request)
    let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    XCTAssertEqual(json["human_item_ids"] as? [String], ["human-1"])
    XCTAssertEqual(json["ai_item_ids"] as? [String], ["ai-1"])
    XCTAssertEqual(json["available_minutes"] as? Int, 300)

    let update = FocusSessionUpdateRequest(
      action: "complete", expectedRevision: 4, completionNote: "완료 증거 확인",
      markActionCompleted: true)
    let updateData = try ActionHubJSON.encoder().encode(update)
    let updateJSON = try XCTUnwrap(JSONSerialization.jsonObject(with: updateData) as? [String: Any])
    XCTAssertEqual(updateJSON["expected_revision"] as? Int, 4)
    XCTAssertEqual(updateJSON["mark_action_completed"] as? Bool, true)
  }

  func testWidgetSnapshotRemainsBackwardCompatibleWithVersionOneCache() throws {
    let old =
      #"{"generated_at":"2026-07-31T01:00:00Z","review_count":2,"waiting_count":1,"ai_running_count":0,"failed_count":0,"overload_minutes":30,"top_titles":["기존 업무"]}"#
    let snapshot = try ActionHubJSON.decoder().decode(
      WidgetSnapshot.self, from: Data(old.utf8))
    XCTAssertEqual(snapshot.reviewCount, 2)
    XCTAssertEqual(snapshot.untriagedCount, 0)
    XCTAssertEqual(snapshot.humanBig3Titles, [])
    XCTAssertNil(snapshot.activeFocusTitle)
  }

  static let triageJSON = #"""
    {
      "generated_at":"2026-08-01T01:00:00Z",
      "total":1,
      "items":[{
        "action_item_id":"item-1","plan_id":"plan-1","title":"고객 제안서 작성",
        "description":"금요일까지 제안서를 보낸다","project":"HCI","repository":null,
        "priority":4,"estimated_minutes":120,"actual_minutes":null,"executor":"human",
        "preferred_worker":null,"state":"approved","attention_state":"untriaged",
        "due_at":null,"deadline_at":"2026-08-07T14:59:00Z","external_url":null,
        "assessment":{
          "id":"assessment-1","action_item_id":"item-1","importance_score":88.0,
          "urgency_score":45.0,"quadrant":"q2","source":"rule","confidence":0.84,
          "reasons_json":["핵심 프로젝트","금요일 마감"],"user_overridden":false,
          "created_at":"2026-08-01T01:00:00Z","updated_at":"2026-08-01T01:00:00Z"
        }
      }]
    }
    """#

  static let focusSessionJSON = #"""
    {
      "id":"session-1","action_item_id":"item-1","planned_minutes":50,
      "extension_minutes":0,"total_planned_minutes":50,"elapsed_seconds":2410,
      "remaining_seconds":590,"progress":0.8033,"state":"running","traffic_state":"yellow",
      "started_at":"2026-08-01T01:00:00Z","paused_at":null,"paused_seconds":0,
      "pause_count":0,"ended_at":null,"actual_minutes":null,"completion_note":null,
      "started_by":"user","revision":2,"created_at":"2026-08-01T01:00:00Z",
      "updated_at":"2026-08-01T01:40:10Z","action":null,
      "micro_steps":[
        {"id":"step-1","action_item_id":"item-1","position":1,"title":"자료 확인",
         "executor":"human","preferred_worker":null,"estimated_minutes":10,"state":"completed",
         "completion_note":null,"created_at":"2026-08-01T01:00:00Z","updated_at":"2026-08-01T01:10:00Z"},
        {"id":"step-2","action_item_id":"item-1","position":2,"title":"초안 검증",
         "executor":"ai","preferred_worker":"codex","estimated_minutes":20,"state":"pending",
         "completion_note":null,"created_at":"2026-08-01T01:00:00Z","updated_at":"2026-08-01T01:00:00Z"}
      ]
    }
    """#
}
