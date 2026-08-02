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
}
