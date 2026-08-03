import Foundation
import XCTest

@testable import ActionHubCore

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

private actor SnapshotRequestRecorder {
  private var paths: [String] = []

  func append(_ request: URLRequest) {
    paths.append(request.url?.path ?? "")
  }

  func allPaths() -> [String] { paths }
}

final class MobileRefreshSnapshotTests: XCTestCase {
  func testRefreshSnapshotUsesCurrentSevenPathsAndNeverChanges() async throws {
    let recorder = SnapshotRequestRecorder()
    let transport = ClosureTransport { request in
      await recorder.append(request)
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      return (Self.responseData(for: request.url!.path), response)
    }
    let session = MobileSession(store: InMemoryCredentialStore(Self.storedSession), transport: transport)
    _ = try await session.restore()

    let snapshot = try await session.refreshSnapshot(currentAppVersion: "0.1.0")

    XCTAssertEqual(snapshot.dashboard.serverVersion, "0.9.0")
    XCTAssertEqual(snapshot.review, [])
    XCTAssertEqual(snapshot.activity, [])
    XCTAssertEqual(snapshot.triage.total, 0)
    XCTAssertEqual(snapshot.matrix.untriagedCount, 0)
    XCTAssertEqual(snapshot.big3.date, "2026-08-03")
    XCTAssertNil(snapshot.activeFocus)

    let paths = await recorder.allPaths()
    XCTAssertEqual(
      paths.sorted(),
      [
        "/api/v1/mobile/activity",
        "/api/v1/mobile/commitments/today",
        "/api/v1/mobile/dashboard",
        "/api/v1/mobile/focus-sessions/active",
        "/api/v1/mobile/matrix",
        "/api/v1/mobile/review",
        "/api/v1/mobile/triage",
      ]
    )
    XCTAssertEqual(paths.filter { $0 == "/api/v1/mobile/changes" }.count, 0)
  }

  private static func responseData(for path: String) -> Data {
    let json: String
    switch path {
    case "/api/v1/mobile/dashboard": json = APIClientTests.dashboardJSON
    case "/api/v1/mobile/review", "/api/v1/mobile/activity": json = "[]"
    case "/api/v1/mobile/triage":
      json = #"{"generated_at":"2026-08-03T01:00:00Z","total":0,"items":[]}"#
    case "/api/v1/mobile/matrix":
      json = #"{"generated_at":"2026-08-03T01:00:00Z","counts":{},"q1":[],"q2":[],"q3":[],"q4":[],"untriaged_count":0}"#
    case "/api/v1/mobile/commitments/today":
      json = #"{"date":"2026-08-03","available_minutes":480,"human_committed_minutes":0,"ai_committed_minutes":0,"overload_minutes":0,"human":[],"ai":[],"warnings":[]}"#
    case "/api/v1/mobile/focus-sessions/active": json = "null"
    default: XCTFail("Unexpected request path: \(path)"); json = "{}"
    }
    return Data(json.utf8)
  }

  private static var storedSession: StoredMobileSession {
    let device = try! ActionHubJSON.decoder().decode(
      MobileDevice.self,
      from: Data(
        #"{"id":"22222222-2222-4222-8222-222222222222","device_name":"iPhone","platform":"ios","hardware_model":"iPhone","os_version":"26.0","app_version":"0.1.0","status":"active","scopes":["brief:read"],"token_version":1,"push_environment":"sandbox","notification_preferences":{},"last_seen_at":null,"revoked_at":null,"created_at":"2026-07-31T01:00:00Z","updated_at":"2026-07-31T01:00:00Z","push_registered":false}"#
          .utf8)
    )
    return StoredMobileSession(
      serverURL: URL(string: "https://hub.example.com")!,
      accessToken: "access-token",
      accessTokenExpiresAt: Date().addingTimeInterval(3600),
      refreshToken: "refresh-token",
      refreshTokenExpiresAt: Date().addingTimeInterval(86400),
      device: device
    )
  }
}
