import Foundation

public struct PairingPayload: Codable, Sendable, Equatable {
  public static let preferredScheme = "jmactionhub"
  public static let legacyScheme = "actionhub"

  public let type: String
  public let version: Int
  public let server: URL
  public let pairingId: String
  public let code: String

  public init(server: URL, pairingId: String, code: String, version: Int = 1) throws {
    guard version == 1 else {
      throw ActionHubAPIError.invalidPairingPayload("지원하지 않는 페어링 버전입니다")
    }
    try Self.validate(server: server, pairingId: pairingId, code: code)
    self.type = "jm-ai-action-hub-pairing"
    self.version = version
    self.server = server
    self.pairingId = pairingId
    self.code = code
  }

  public static func parse(_ raw: String, allowInsecureLocalhost: Bool = true) throws
    -> PairingPayload
  {
    let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else {
      throw ActionHubAPIError.invalidPairingPayload("내용이 비어 있습니다")
    }

    if trimmed.first == "{" {
      do {
        let decoded = try ActionHubJSON.decoder().decode(
          PairingPayload.self, from: Data(trimmed.utf8))
        guard decoded.type == "jm-ai-action-hub-pairing", decoded.version == 1 else {
          throw ActionHubAPIError.invalidPairingPayload("지원하지 않는 형식 또는 버전입니다")
        }
        try validate(
          server: decoded.server, pairingId: decoded.pairingId, code: decoded.code,
          allowInsecureLocalhost: allowInsecureLocalhost)
        return decoded
      } catch let error as ActionHubAPIError {
        throw error
      } catch {
        throw ActionHubAPIError.invalidPairingPayload(error.localizedDescription)
      }
    }

    guard let url = URL(string: trimmed),
      let scheme = url.scheme?.lowercased(),
      scheme == preferredScheme || scheme == legacyScheme,
      url.host?.lowercased() == "pair",
      url.user == nil,
      url.password == nil,
      url.fragment == nil
    else {
      throw ActionHubAPIError.invalidPairingPayload(
        "QR JSON 또는 \(preferredScheme)://pair 링크가 아닙니다")
    }

    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
      throw ActionHubAPIError.invalidPairingPayload("페어링 링크를 해석할 수 없습니다")
    }
    let requiredNames = Set(["server", "pairing_id", "code"])
    var values: [String: String] = [:]
    for item in components.queryItems ?? [] {
      guard requiredNames.contains(item.name), let value = item.value,
        values[item.name] == nil
      else {
        throw ActionHubAPIError.invalidPairingPayload("중복되거나 허용되지 않은 쿼리 항목입니다")
      }
      values[item.name] = value
    }
    guard values.count == requiredNames.count,
      let serverText = values["server"], let server = URL(string: serverText),
      let pairingId = values["pairing_id"], let code = values["code"]
    else {
      throw ActionHubAPIError.invalidPairingPayload("필수 server, pairing_id, code가 없습니다")
    }
    try validate(
      server: server, pairingId: pairingId, code: code,
      allowInsecureLocalhost: allowInsecureLocalhost)
    return try PairingPayload(server: server, pairingId: pairingId, code: code)
  }

  private static func validate(
    server: URL,
    pairingId: String,
    code: String,
    allowInsecureLocalhost: Bool = true
  ) throws {
    let scheme = server.scheme?.lowercased()
    let host = server.host?.lowercased() ?? ""
    let local = host == "localhost" || host == "127.0.0.1" || host == "::1"
    guard !host.isEmpty,
      scheme == "https" || (allowInsecureLocalhost && local && scheme == "http"),
      server.user == nil,
      server.password == nil,
      server.query == nil,
      server.fragment == nil
    else {
      throw ActionHubAPIError.invalidPairingPayload("HTTPS 서버만 연결할 수 있습니다")
    }
    guard UUID(uuidString: pairingId) != nil else {
      throw ActionHubAPIError.invalidPairingPayload("pairing_id가 UUID가 아닙니다")
    }
    let canonical = code.uppercased().filter { $0 != "-" && !$0.isWhitespace }
    let allowed = Set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    guard canonical.count == 16, canonical.allSatisfy({ allowed.contains($0) }) else {
      throw ActionHubAPIError.invalidPairingPayload("페어링 코드 형식이 올바르지 않습니다")
    }
  }
}
