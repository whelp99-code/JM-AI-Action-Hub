import Foundation
import XCTest

@testable import ActionHubCore

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

private actor ResponseSequence {
  private var index = 0
  private(set) var requests: [URLRequest] = []

  func response(for request: URLRequest) throws -> (Data, HTTPURLResponse) {
    requests.append(request)
    defer { index += 1 }
    switch index {
    case 0:
      return (
        Data(#"{"detail":"expired"}"#.utf8),
        HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!
      )
    case 1:
      return (
        Data(Self.tokenJSON.utf8),
        HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      )
    default:
      return (
        Data(APIClientTests.dashboardJSON.utf8),
        HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
      )
    }
  }

  static let tokenJSON = #"""
    {
          "token_type":"Bearer","access_token":"new-access","expires_in":900,"refresh_token":"new-refresh","refresh_expires_at":"2026-08-30T01:00:00Z",
          "device":{"id":"22222222-2222-4222-8222-222222222222","device_name":"iPhone","platform":"ios","hardware_model":"iPhone","os_version":"26.0","app_version":"0.1.0","status":"active","scopes":["brief:read"],"token_version":1,"push_environment":"sandbox","notification_preferences":{},"last_seen_at":"2026-07-31T01:00:00Z","revoked_at":null,"created_at":"2026-07-31T01:00:00Z","updated_at":"2026-07-31T01:00:00Z","push_registered":false}
        }
    """#
}

final class MobileSessionTests: XCTestCase {
  func testUnauthorizedRequestRefreshesAndRetries() async throws {
    let deviceData = Data(
      #"{"id":"22222222-2222-4222-8222-222222222222","device_name":"iPhone","platform":"ios","hardware_model":"iPhone","os_version":"26.0","app_version":"0.1.0","status":"active","scopes":["brief:read"],"token_version":1,"push_environment":"sandbox","notification_preferences":{},"last_seen_at":null,"revoked_at":null,"created_at":"2026-07-31T01:00:00Z","updated_at":"2026-07-31T01:00:00Z","push_registered":false}"#
        .utf8)
    let device = try ActionHubJSON.decoder().decode(MobileDevice.self, from: deviceData)
    let stored = StoredMobileSession(
      serverURL: URL(string: "https://hub.example.com")!,
      accessToken: "old-access",
      accessTokenExpiresAt: Date().addingTimeInterval(3600),
      refreshToken: "old-refresh",
      refreshTokenExpiresAt: Date().addingTimeInterval(86400),
      device: device
    )
    let store = InMemoryCredentialStore(stored)
    let sequence = ResponseSequence()
    let transport = ClosureTransport { request in try await sequence.response(for: request) }
    let session = MobileSession(store: store, transport: transport)
    _ = try await session.restore()
    let dashboard = try await session.dashboard()
    XCTAssertEqual(dashboard.serverVersion, "0.9.0")
    let requests = await sequence.requests
    XCTAssertEqual(
      requests.map { $0.url?.path },
      [
        "/api/v1/mobile/dashboard",
        "/api/v1/mobile/token/refresh",
        "/api/v1/mobile/dashboard",
      ])
    XCTAssertEqual(requests.last?.value(forHTTPHeaderField: "Authorization"), "Bearer new-access")
    let saved = try await store.load()
    XCTAssertEqual(saved?.refreshToken, "new-refresh")
  }
}

extension MobileSessionTests {
  func testDisconnectAlwaysDeletesLocalCredentialsWhenServerRevokeFails() async throws {
    let deviceData = Data(
      #"{"id":"22222222-2222-4222-8222-222222222222","device_name":"iPhone","platform":"ios","hardware_model":"iPhone","os_version":"26.0","app_version":"0.1.0","status":"active","scopes":["brief:read"],"token_version":1,"push_environment":"sandbox","notification_preferences":{},"last_seen_at":null,"revoked_at":null,"created_at":"2026-07-31T01:00:00Z","updated_at":"2026-07-31T01:00:00Z","push_registered":false}"#
        .utf8)
    let device = try ActionHubJSON.decoder().decode(MobileDevice.self, from: deviceData)
    let stored = StoredMobileSession(
      serverURL: URL(string: "https://hub.example.com")!,
      accessToken: "access",
      accessTokenExpiresAt: Date().addingTimeInterval(3600),
      refreshToken: "refresh",
      refreshTokenExpiresAt: Date().addingTimeInterval(86400),
      device: device
    )
    let store = InMemoryCredentialStore(stored)
    let transport = ClosureTransport { request in
      let response = HTTPURLResponse(
        url: request.url!, statusCode: 503, httpVersion: nil, headerFields: nil)!
      return (Data(#"{"detail":"unavailable"}"#.utf8), response)
    }
    let session = MobileSession(store: store, transport: transport)
    _ = try await session.restore()

    do {
      try await session.disconnect()
      XCTFail("Expected the remote revoke failure to be surfaced")
    } catch let error as ActionHubAPIError {
      XCTAssertEqual(error, .server(status: 503, message: "unavailable"))
    }

    let saved = try await store.load()
    let connected = await session.isConnected
    XCTAssertNil(saved)
    XCTAssertFalse(connected)
  }
}

extension MobileSessionTests {
  func testPairingPreflightsCapabilitiesBeforeClaim() async throws {
    let recorder = RequestRecorderForPairing()
    let transport = ClosureTransport { request in
      try await recorder.response(for: request)
    }
    let store = InMemoryCredentialStore()
    let session = MobileSession(store: store, transport: transport)
    let payload = try PairingPayload(
      server: URL(string: "https://hub.example.com")!,
      pairingId: "11111111-1111-4111-8111-111111111111",
      code: "ABCD-EFGH-JKLM-NPQR"
    )
    let device = try await session.pair(
      payload: payload,
      deviceInfo: MobileDeviceInfo(name: "iPhone", appVersion: "0.1.0")
    )
    XCTAssertEqual(device.deviceName, "iPhone")
    let paths = await recorder.paths
    XCTAssertEqual(paths, ["/api/v1/mobile/capabilities", "/api/v1/mobile/pairings/claim"])
  }

  func testPairingRejectsAppBelowServerMinimumWithoutClaiming() async throws {
    let recorder = RequestRecorderForPairing(minimumVersion: "0.2.0")
    let transport = ClosureTransport { request in
      try await recorder.response(for: request)
    }
    let session = MobileSession(store: InMemoryCredentialStore(), transport: transport)
    let payload = try PairingPayload(
      server: URL(string: "https://hub.example.com")!,
      pairingId: "11111111-1111-4111-8111-111111111111",
      code: "ABCD-EFGH-JKLM-NPQR"
    )
    do {
      _ = try await session.pair(
        payload: payload,
        deviceInfo: MobileDeviceInfo(name: "iPhone", appVersion: "0.1.0")
      )
      XCTFail("Expected an update requirement")
    } catch let error as ActionHubAPIError {
      XCTAssertEqual(error, .updateRequired(minimumVersion: "0.2.0"))
    }
    let paths = await recorder.paths
    XCTAssertEqual(paths, ["/api/v1/mobile/capabilities"])
  }
}

private actor RequestRecorderForPairing {
  private(set) var paths: [String] = []
  private let minimumVersion: String

  init(minimumVersion: String = "0.1.0") {
    self.minimumVersion = minimumVersion
  }

  func response(for request: URLRequest) throws -> (Data, HTTPURLResponse) {
    let path = request.url!.path
    paths.append(path)
    let response = HTTPURLResponse(
      url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
    if path == "/api/v1/mobile/capabilities" {
      let json = """
        {"service":"JM-AI Action Hub","server_version":"0.8.0","mobile_api_version":"1","mobile_enabled":true,"minimum_ios_app_version":"\(minimumVersion)","pairing_supported":true,"push_supported":false,"features":["secure-pairing"]}
        """
      return (Data(json.utf8), response)
    }
    return (Data(ResponseSequence.tokenJSON.utf8), response)
  }
}
