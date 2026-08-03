import Foundation
import XCTest
@testable import ActionHubCore

private final class RequestRecordingURLProtocol: URLProtocol, @unchecked Sendable {
  nonisolated(unsafe) static var capturedRequest: URLRequest?

  override class func canInit(with request: URLRequest) -> Bool {
    true
  }

  override class func canonicalRequest(for request: URLRequest) -> URLRequest {
    request
  }

  override func startLoading() {
    Self.capturedRequest = request
    let response = HTTPURLResponse(
      url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
    client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
    client?.urlProtocolDidFinishLoading(self)
  }

  override func stopLoading() {}
}

final class HTTPTransportTests: XCTestCase {
  func testUserAgentUsesSemanticAppVersion() {
    XCTAssertEqual(
      URLSessionTransport.userAgent(appVersion: "0.9.0"),
      "JM-AI-Action-Hub-iOS/0.9.0"
    )
  }

  func testUserAgentUsesUnknownForMissingOrInvalidAppVersions() {
    for version in [nil, "", " 0.9.0", "0.9.0 ", "0.9.0\n", "0.9.0\r", "0.9.0\u{0001}", "0.9", "v0.9.0"] {
      XCTAssertEqual(
        URLSessionTransport.userAgent(appVersion: version),
        "JM-AI-Action-Hub-iOS/unknown",
        "version=\(String(describing: version))"
      )
    }
  }

  func testURLSessionTransportAddsSemanticVersionUserAgentHeader() async throws {
    let userAgent = try await requestUserAgent(appVersion: "0.9.0")

    XCTAssertEqual(userAgent, "JM-AI-Action-Hub-iOS/0.9.0")
  }

  func testURLSessionTransportRejectsControlCharacterVersionInUserAgentHeader() async throws {
    let userAgent = try await requestUserAgent(appVersion: "0.9.0\n")

    XCTAssertEqual(userAgent, "JM-AI-Action-Hub-iOS/unknown")
  }

  private func requestUserAgent(appVersion: String?) async throws -> String? {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.protocolClasses = [RequestRecordingURLProtocol.self]
    RequestRecordingURLProtocol.capturedRequest = nil
    let transport = URLSessionTransport(configuration: configuration, appVersion: appVersion)
    _ = try await transport.data(for: URLRequest(url: URL(string: "https://example.test/agent")!))
    return RequestRecordingURLProtocol.capturedRequest?.value(forHTTPHeaderField: "User-Agent")
  }
}
