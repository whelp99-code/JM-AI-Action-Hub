import Foundation
import XCTest

@testable import ActionHubCore

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

private actor RequestRecorder {
  var requests: [URLRequest] = []
  func append(_ request: URLRequest) { requests.append(request) }
  func all() -> [URLRequest] { requests }
}

final class APIClientTests: XCTestCase {
  func testDashboardUsesBearerToken() async throws {
    let recorder = RequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let data = Data(Self.dashboardJSON.utf8)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      return (data, response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    let dashboard = try await client.dashboard(accessToken: "access-token")
    XCTAssertEqual(dashboard.serverVersion, "0.9.0")
    let recorded = await recorder.all()
    let request = try XCTUnwrap(recorded.first)
    XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer access-token")
    XCTAssertEqual(request.url?.path, "/api/v1/mobile/dashboard")
  }

  func testResolveFollowupUsesMobileEditRoute() async throws {
    let recorder = RequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let data = Data(Self.followupJSON.utf8)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      return (data, response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    let followup = try await client.resolveFollowup(
      id: "follow/up-1",
      request: FollowUpResolveRequest(state: "response_received", note: "회신 확인"),
      accessToken: "access-token")
    XCTAssertEqual(followup.state, "response_received")
    let recorded = await recorder.all()
    let request = try XCTUnwrap(recorded.first)
    XCTAssertEqual(request.httpMethod, "POST")
    XCTAssertTrue(request.url?.absoluteString.contains("follow%2Fup-1/resolve") == true)
    XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer access-token")
    let body = try XCTUnwrap(request.httpBody)
    let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
    XCTAssertEqual(object["state"], "response_received")
    XCTAssertEqual(object["note"], "회신 확인")
  }

  func testDynamicIdentifiersAreEncodedAsSinglePathSegments() async throws {
    let recorder = RequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil)!
      return (Data(#"{"detail":"not found"}"#.utf8), response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    do {
      _ = try await client.plan(id: "unsafe/../id%2Fchild", accessToken: "token")
      XCTFail("Expected not found")
    } catch let error as ActionHubAPIError {
      XCTAssertEqual(error, .notFound)
    }
    let recorded = await recorder.all()
    let request = try XCTUnwrap(recorded.first)
    let absolute = try XCTUnwrap(request.url?.absoluteString)
    XCTAssertTrue(absolute.contains("unsafe%2F..%2Fid%252Fchild"), absolute)
  }

  func testConflictResponseMapsCurrentRevision() async throws {
    let transport = ClosureTransport { request in
      let data = Data(
        #"{"detail":{"code":"revision_conflict","entity":"plan","current_revision":7}}"#.utf8)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 409, httpVersion: nil, headerFields: nil)!
      return (data, response)
    }
    let client = try ActionHubAPIClient(
      baseURL: URL(string: "https://hub.example.com")!, transport: transport)
    do {
      _ = try await client.plan(id: "p1", accessToken: "token")
      XCTFail("Expected a conflict")
    } catch let error as ActionHubAPIError {
      XCTAssertEqual(error, .conflict(code: "revision_conflict", currentRevision: 7))
    }
  }

  static let dashboardJSON = #"""
    {
          "generated_at":"2026-07-31T01:00:00Z",
          "server_version":"0.9.0",
          "minimum_ios_app_version":"0.1.0",
          "review_count":0,"waiting_count":0,"ai_running_count":0,"failed_count":0,
          "brief":{"generated_at":"2026-07-31T01:00:00Z","timezone":"Asia/Seoul","date":"2026-07-31","events":[],"due_tasks":[],"overdue":[],"needs_review":[],"waiting":[],"ai_ready":[],"summary":"none"},
          "decision":{"date":"2026-07-31","generated_at":"2026-07-31T01:00:00Z","available_minutes":480,"buffer_minutes":60,"planned_minutes":0,"overload_minutes":0,"top_items":[],"deferred_items":[],"ai_delegation_candidates":[],"waiting_followups":[],"risks":[],"summary":"none"},
          "recent_activity":[]
        }
    """#

  static let followupJSON = #"""
    {
      "id":"follow-up-1","action_item_id":"item-1","state":"response_received",
      "waiting_for":"협력사","channel":"email","expected_by":null,
      "follow_up_at":"2030-01-02T10:00:00Z","template":null,"reminder_count":0,
      "last_reminded_at":null,"response_received_at":"2030-01-02T10:00:00Z",
      "created_at":"2030-01-01T10:00:00Z","updated_at":"2030-01-02T10:00:00Z",
      "action_title":"견적 회신 확인"
    }
    """#
}

extension APIClientTests {
  func testRejectsInsecureRemoteHTTPServer() {
    XCTAssertThrowsError(
      try ActionHubAPIClient(baseURL: URL(string: "http://hub.example.com")!)
    ) { error in
      XCTAssertEqual(error as? ActionHubAPIError, .invalidBaseURL)
    }
  }

  func testAllowsHTTPOnlyForLoopbackDevelopment() throws {
    _ = try ActionHubAPIClient(baseURL: URL(string: "http://127.0.0.1:8787")!)
    _ = try ActionHubAPIClient(baseURL: URL(string: "http://localhost:8787")!)
  }
}
