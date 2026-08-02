import Foundation

#if canImport(FoundationNetworking)
  import FoundationNetworking
#endif

public protocol HTTPTransport: Sendable {
  func data(for request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport, @unchecked Sendable {
  private let session: URLSession

  public init(configuration: URLSessionConfiguration = .ephemeral) {
    #if !os(Linux)
      configuration.waitsForConnectivity = true
    #endif
    configuration.timeoutIntervalForRequest = 30
    configuration.timeoutIntervalForResource = 60
    configuration.httpAdditionalHeaders = [
      "Accept": "application/json",
      "User-Agent": "JM-AI-Action-Hub-iOS/0.1",
    ]
    self.session = URLSession(configuration: configuration)
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
