import XCTest

@testable import ActionHubCore

final class PairingPayloadTests: XCTestCase {
  private let pairingId = "11111111-1111-4111-8111-111111111111"
  private let code = "ABCD-EFGH-JKLM-NPQR"

  func testParsesJSONPayload() throws {
    let raw =
      #"{"type":"jm-ai-action-hub-pairing","version":1,"server":"https://hub.example.com","pairing_id":"11111111-1111-4111-8111-111111111111","code":"ABCD-EFGH-JKLM-NPQR"}"#
    let payload = try PairingPayload.parse(raw)
    XCTAssertEqual(payload.server.absoluteString, "https://hub.example.com")
    XCTAssertEqual(payload.pairingId, pairingId)
  }

  func testParsesPreferredCustomSchemePayload() throws {
    let raw =
      "jmactionhub://pair?server=https%3A%2F%2Fhub.example.com&pairing_id=\(pairingId)&code=\(code)"
    let payload = try PairingPayload.parse(raw)
    XCTAssertEqual(payload.code, code)
  }

  func testParsesLegacySchemeOnlyForPastedCompatibility() throws {
    let raw =
      "actionhub://pair?server=https%3A%2F%2Fhub.example.com&pairing_id=\(pairingId)&code=\(code)"
    XCTAssertNoThrow(try PairingPayload.parse(raw))
  }

  func testRejectsWrongCustomURLHost() {
    let raw =
      "jmactionhub://capture?server=https%3A%2F%2Fhub.example.com&pairing_id=\(pairingId)&code=\(code)"
    XCTAssertThrowsError(try PairingPayload.parse(raw))
  }

  func testRejectsDuplicateQueryParameterWithoutCrashing() {
    let raw =
      "jmactionhub://pair?server=https%3A%2F%2Fhub.example.com&server=https%3A%2F%2Fevil.example.com&pairing_id=\(pairingId)&code=\(code)"
    XCTAssertThrowsError(try PairingPayload.parse(raw))
  }

  func testRejectsUnexpectedQueryParameter() {
    let raw =
      "jmactionhub://pair?server=https%3A%2F%2Fhub.example.com&pairing_id=\(pairingId)&code=\(code)&redirect=https%3A%2F%2Fevil.example.com"
    XCTAssertThrowsError(try PairingPayload.parse(raw))
  }

  func testRejectsWrongJSONTypeAndVersion() {
    let wrongType =
      #"{"type":"other","version":1,"server":"https://hub.example.com","pairing_id":"11111111-1111-4111-8111-111111111111","code":"ABCD-EFGH-JKLM-NPQR"}"#
    let wrongVersion =
      #"{"type":"jm-ai-action-hub-pairing","version":2,"server":"https://hub.example.com","pairing_id":"11111111-1111-4111-8111-111111111111","code":"ABCD-EFGH-JKLM-NPQR"}"#
    XCTAssertThrowsError(try PairingPayload.parse(wrongType))
    XCTAssertThrowsError(try PairingPayload.parse(wrongVersion))
  }

  func testRejectsMalformedCode() {
    let raw =
      #"{"type":"jm-ai-action-hub-pairing","version":1,"server":"https://hub.example.com","pairing_id":"11111111-1111-4111-8111-111111111111","code":"AAAA-BBBB-CCCC-0000"}"#
    XCTAssertThrowsError(try PairingPayload.parse(raw))
  }

  func testRejectsInsecureRemoteServer() {
    let raw =
      #"{"type":"jm-ai-action-hub-pairing","version":1,"server":"http://hub.example.com","pairing_id":"11111111-1111-4111-8111-111111111111","code":"ABCD-EFGH-JKLM-NPQR"}"#
    XCTAssertThrowsError(try PairingPayload.parse(raw))
  }

  func testAllowsHTTPOnlyForLoopbackDevelopment() throws {
    let raw =
      #"{"type":"jm-ai-action-hub-pairing","version":1,"server":"http://127.0.0.1:8787","pairing_id":"11111111-1111-4111-8111-111111111111","code":"ABCD-EFGH-JKLM-NPQR"}"#
    XCTAssertNoThrow(try PairingPayload.parse(raw))
    XCTAssertThrowsError(try PairingPayload.parse(raw, allowInsecureLocalhost: false))
  }
}
