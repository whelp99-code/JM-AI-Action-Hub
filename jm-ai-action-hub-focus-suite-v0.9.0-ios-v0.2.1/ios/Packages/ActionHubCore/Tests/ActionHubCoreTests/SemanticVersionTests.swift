import XCTest

@testable import ActionHubCore

final class SemanticVersionTests: XCTestCase {
  func testVersionComparisonPadsMissingComponents() throws {
    XCTAssertEqual(try XCTUnwrap(SemanticVersion("1.0")), try XCTUnwrap(SemanticVersion("1.0.0")))
    XCTAssertLessThan(
      try XCTUnwrap(SemanticVersion("0.9.9")), try XCTUnwrap(SemanticVersion("1.0.0")))
    XCTAssertGreaterThan(
      try XCTUnwrap(SemanticVersion("1.10.0")), try XCTUnwrap(SemanticVersion("1.2.0")))
  }

  func testPrereleaseSuffixUsesCoreVersionForMinimumCheck() {
    XCTAssertTrue(SemanticVersion.requiresUpdate(current: "0.1.0-beta.1", minimum: "0.1.0"))
    XCTAssertTrue(SemanticVersion.requiresUpdate(current: "0.1.0", minimum: "0.2.0"))
  }

  func testMalformedVersionFailsClosed() {
    XCTAssertTrue(SemanticVersion.requiresUpdate(current: "development", minimum: "0.1.0"))
  }
}
