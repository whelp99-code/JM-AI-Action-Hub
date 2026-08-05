import Foundation

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

public protocol HTTPTransport: Sendable {
  func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport, @unchecked Sendable {
  private let session: URLSession

  public init(configuration: URLSessionConfiguration = .ephemeral, appVersion: String? = nil) {
    #if !os(Linux)
      configuration.waitsForConnectivity = true
    #endif
    configuration.timeoutIntervalForRequest = 30
    configuration.timeoutIntervalForResource = 60
    configuration.httpAdditionalHeaders = [
      "Accept": "application/json",
      "User-Agent": Self.userAgent(appVersion: appVersion),
    ]
    self.session = URLSession(configuration: configuration)
  }

  static func userAgent(appVersion: String?) -> String {
    "JM-AI-Action-Hub-iOS/\(sanitizedVersion(appVersion))"
  }

  private static func sanitizedVersion(_ appVersion: String?) -> String {
    guard let appVersion, appVersion.wholeMatch(of: /[0-9]+\.[0-9]+\.[0-9]+/) != nil else {
      return "unknown"
    }
    return appVersion
  }

  public func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
    do {
      let (data, response) = try await session.data(for: request)
      guard let http = response as? HTTPURLResponse else {
        throw ActionHubAPIError.invalidResponse
      }
      return (data, http)
    } catch let error as ActionHubAPIError {
      throw error
    } catch is CancellationError {
      // Structured-concurrency cancellation (e.g. a `.task` torn down mid-request).
      throw ActionHubAPIError.cancelled
    } catch let urlError as URLError where urlError.code == .cancelled {
      // URLSession cancellation (pull-to-refresh gesture resolving, app backgrounding). Before
      // this case existed, every cancellation was wrapped as `.transport(...)`, which made it
      // structurally impossible for callers to filter cancellation out of error handling --
      // see AppModel.handle(_:).
      throw ActionHubAPIError.cancelled
    } catch {
      throw ActionHubAPIError.transport(error.localizedDescription)
    }
  }
}

public struct ClosureTransport: HTTPTransport {
  public typealias Handler = @Sendable (URLRequest) async throws -> (Data, HTTPURLResponse)
  private let handler: Handler

  public init(_ handler: @escaping Handler) {
    self.handler = handler
  }

  public func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse) {
    try await handler(request)
  }
}
