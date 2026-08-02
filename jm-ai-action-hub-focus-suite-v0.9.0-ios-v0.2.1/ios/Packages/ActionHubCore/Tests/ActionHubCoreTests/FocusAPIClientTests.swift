import Foundation
import XCTest

@testable import ActionHubCore

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

private actor FocusRequestRecorder {
  var requests: [URLRequest] = []
  func append(_ request: URLRequest) { requests.append(request) }
  func all() -> [URLRequest] { requests }
}

final class FocusAPIClientTests: XCTestCase {
  func testStartFocusAcceptsCreatedAndUsesBearerToken() async throws {
    let recorder = FocusRequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 201, httpVersion: nil, headerFields: nil)!
      return (Data(Self.sessionJSON.utf8), response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    let session = try await client.startFocusSession(
      FocusSessionStartRequest(actionItemId: "item/unsafe", plannedMinutes: 25),
      accessToken: "mobile-token")
    XCTAssertEqual(session.state, .running)
    let recorded = await recorder.all()
    let request = try XCTUnwrap(recorded.first)
    XCTAssertEqual(request.httpMethod, "POST")
    XCTAssertEqual(request.url?.path, "/api/v1/mobile/focus-sessions")
    XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer mobile-token")
  }

  func testClassifyEncodesIdentifierAsOnePathSegment() async throws {
    let recorder = FocusRequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      return (Data(Self.actionJSON.utf8), response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    let item = try await client.classifyFocusAction(
      itemId: "owner/unsafe", request: ClassifyActionRequest(quadrant: .q3),
      accessToken: "token")
    XCTAssertEqual(item.assessment?.quadrant, .q3)
    let recorded = await recorder.all()
    let request = try XCTUnwrap(recorded.first)
    XCTAssertTrue(request.url?.absoluteString.contains("owner%2Funsafe/classify") == true)
  }

  static let sessionJSON = FocusModelCodingTests.focusSessionJSON
  static let actionJSON = #"""
    {
      "action_item_id":"owner/unsafe","plan_id":"plan-1","title":"테스트 보강",
      "description":"","project":null,"repository":"owner/repo","priority":3,
      "estimated_minutes":30,"actual_minutes":null,"executor":"ai","preferred_worker":"codex",
      "state":"approved","attention_state":"classified","due_at":null,"deadline_at":null,
      "external_url":null,"assessment":{
        "id":"a1","action_item_id":"owner/unsafe","importance_score":40.0,"urgency_score":80.0,
        "quadrant":"q3","source":"user","confidence":1.0,"reasons_json":["사용자 분류"],
        "user_overridden":true,"created_at":"2026-08-01T01:00:00Z","updated_at":"2026-08-01T01:00:00Z"
      }
    }
    """#
}
