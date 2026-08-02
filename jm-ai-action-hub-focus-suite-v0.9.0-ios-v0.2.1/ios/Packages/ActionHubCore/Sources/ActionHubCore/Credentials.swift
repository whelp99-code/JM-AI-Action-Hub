import Foundation

public struct StoredMobileSession: Codable, Sendable, Equatable {
  public let serverURL: URL
  public var accessToken: String
  public var accessTokenExpiresAt: Date
  public var refreshToken: String
  public var refreshTokenExpiresAt: Date
  public var device: MobileDevice

  public init(
    serverURL: URL,
    accessToken: String,
    accessTokenExpiresAt: Date,
    refreshToken: String,
    refreshTokenExpiresAt: Date,
    device: MobileDevice
  ) {
    self.serverURL = serverURL
    self.accessToken = accessToken
    self.accessTokenExpiresAt = accessTokenExpiresAt
    self.refreshToken = refreshToken
    self.refreshTokenExpiresAt = refreshTokenExpiresAt
    self.device = device
  }

  public init(serverURL: URL, response: MobileTokenResponse, now: Date = Date()) {
    self.init(
      serverURL: serverURL,
      accessToken: response.accessToken,
      accessTokenExpiresAt: now.addingTimeInterval(TimeInterval(response.expiresIn)),
      refreshToken: response.refreshToken,
      refreshTokenExpiresAt: response.refreshExpiresAt,
      device: response.device
    )
  }
}

public protocol CredentialStore: Sendable {
  func load() async throws -> StoredMobileSession?
  func save(_ session: StoredMobileSession) async throws
  func delete() async throws
}

public actor InMemoryCredentialStore: CredentialStore {
  private var value: StoredMobileSession?

  public init(_ value: StoredMobileSession? = nil) {
    self.value = value
  }

  public func load() async throws -> StoredMobileSession? { value }
  public func save(_ session: StoredMobileSession) async throws { value = session }
  public func delete() async throws { value = nil }
}
