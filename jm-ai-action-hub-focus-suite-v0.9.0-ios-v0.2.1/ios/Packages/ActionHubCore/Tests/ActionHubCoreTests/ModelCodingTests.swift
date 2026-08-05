import XCTest

@testable import ActionHubCore

final class ModelCodingTests: XCTestCase {
  func testCapabilitiesDecodesSnakeCaseAcronyms() throws {
    let data = Data(
      #"{"service":"JM-AI Action Hub","server_version":"0.8.0","mobile_api_version":"1","mobile_enabled":true,"minimum_ios_app_version":"0.1.0","pairing_supported":true,"push_supported":false,"features":["secure-pairing"]}"#
        .utf8)
    let value = try ActionHubJSON.decoder().decode(MobileCapabilities.self, from: data)
    XCTAssertEqual(value.mobileApiVersion, "1")
    XCTAssertEqual(value.minimumIosAppVersion, "0.1.0")
  }

  func testCaptureEncodesIdempotencyIdentifier() throws {
    let capture = CaptureInput(clientCaptureId: "capture-1", text: "내일 오전 10시 고객 미팅")
    let data = try ActionHubJSON.encoder().encode(CaptureBatchRequest(captures: [capture]))
    let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    let captures = try XCTUnwrap(json["captures"] as? [[String: Any]])
    XCTAssertEqual(captures.first?["client_capture_id"] as? String, "capture-1")
  }

  func testActionItemPatchDistinguishesOmittedValueAndExplicitNull() throws {
    var patch = ActionItemPatch(expectedRevision: 7)
    patch.title = "수정된 제목"
    patch.repository = nil
    patch.estimatedMinutes = nil

    let data = try ActionHubJSON.encoder().encode(patch)
    let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])

    XCTAssertEqual(json["expected_revision"] as? Int, 7)
    XCTAssertEqual(json["title"] as? String, "수정된 제목")
    XCTAssertTrue(json["repository"] is NSNull)
    XCTAssertTrue(json["estimated_minutes"] is NSNull)
    XCTAssertNil(json["destination"])
    XCTAssertNil(json["project"])
  }

  func testDateDecoderAcceptsFractionalAndWholeSeconds() throws {
    struct Box: Decodable { let date: Date }
    let fractional = try ActionHubJSON.decoder().decode(
      Box.self, from: Data(#"{"date":"2026-07-31T01:02:03.123Z"}"#.utf8))
    let whole = try ActionHubJSON.decoder().decode(
      Box.self, from: Data(#"{"date":"2026-07-31T01:02:03Z"}"#.utf8))
    XCTAssertEqual(
      Int(fractional.date.timeIntervalSince1970), Int(whole.date.timeIntervalSince1970))
  }

  /// RV-01: the review screen looked like a no-op when the server silently blocked an
  /// item that still needed review. `blocked_item_ids` on the approve response is how
  /// the app learns that happened, so it must decode into the plan.
  func testActionPlanDecodesBlockedItemIds() throws {
    let data = Data(
      #"{"id":"plan-1","inbox_id":"inbox-1","status":"draft","parser_name":"rules-v2","summary":"","reference_time":"2026-08-05T01:00:00Z","revision":1,"created_at":"2026-08-05T01:00:00Z","updated_at":"2026-08-05T01:00:00Z","items":[],"inbox":null,"blocked_item_ids":["item-1","item-2"]}"#
        .utf8)
    let plan = try ActionHubJSON.decoder().decode(ActionPlan.self, from: data)
    XCTAssertEqual(plan.blockedItemIds, ["item-1", "item-2"])
  }

  /// Older or unrelated PlanRead responses (get/patch/execute) never populate
  /// `blocked_item_ids`; decoding must default to empty rather than fail.
  func testActionPlanDefaultsBlockedItemIdsWhenFieldIsAbsent() throws {
    let data = Data(
      #"{"id":"plan-1","inbox_id":"inbox-1","status":"draft","parser_name":"rules-v2","summary":"","reference_time":"2026-08-05T01:00:00Z","revision":1,"created_at":"2026-08-05T01:00:00Z","updated_at":"2026-08-05T01:00:00Z","items":[],"inbox":null}"#
        .utf8)
    let plan = try ActionHubJSON.decoder().decode(ActionPlan.self, from: data)
    XCTAssertEqual(plan.blockedItemIds, [])
  }

  /// A stored session must survive the encode/decode round trip used by the Keychain store.
  /// `convertToSnakeCase` and `convertFromSnakeCase` are not inverses for acronym-suffixed
  /// names, which silently broke session restore on every cold launch.
  func testStoredMobileSessionSurvivesKeychainRoundTrip() throws {
    let deviceData = Data(
      #"{"id":"33333333-3333-4333-8333-333333333333","device_name":"iPhone","platform":"ios","hardware_model":"iPhone17,1","os_version":"26.5.2","app_version":"0.2.1","status":"active","scopes":["brief:read"],"token_version":1,"push_environment":"sandbox","notification_preferences":{},"last_seen_at":null,"revoked_at":null,"created_at":"2026-08-05T01:00:00Z","updated_at":"2026-08-05T01:00:00Z","push_registered":false}"#
        .utf8)
    let device = try ActionHubJSON.decoder().decode(MobileDevice.self, from: deviceData)
    let session = StoredMobileSession(
      serverURL: URL(string: "https://jm-acloud.example.ts.net")!,
      accessToken: "access",
      accessTokenExpiresAt: Date(timeIntervalSince1970: 1_800_000_000),
      refreshToken: "refresh",
      refreshTokenExpiresAt: Date(timeIntervalSince1970: 1_800_086_400),
      device: device
    )
    let encoded = try ActionHubJSON.encoder().encode(session)
    let json = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
    XCTAssertNotNil(json["server_url"], "on-disk key must stay server_url for existing sessions")
    let decoded = try ActionHubJSON.decoder().decode(StoredMobileSession.self, from: encoded)
    XCTAssertEqual(decoded, session)
  }
}
