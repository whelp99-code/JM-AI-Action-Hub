import Foundation

public enum ActionHubAPIError: Error, LocalizedError, Sendable, Equatable {
  case invalidBaseURL
  case invalidResponse
  case unauthorized
  case forbidden
  case notFound
  case conflict(code: String?, currentRevision: Int?)
  case server(status: Int, message: String)
  case transport(String)
  case decoding(String)
  case encoding(String)
  case invalidPairingPayload(String)
  case unexpectedService(String)
  case mobileDisabled
  case unsupportedMobileAPIVersion(String)
  case updateRequired(minimumVersion: String)
  case noStoredSession
  case revoked

  public var errorDescription: String? {
    switch self {
    case .invalidBaseURL: return "Action Hub 서버 주소가 올바르지 않습니다."
    case .invalidResponse: return "서버 응답 형식을 확인할 수 없습니다."
    case .unauthorized: return "인증이 만료되었거나 유효하지 않습니다."
    case .forbidden: return "이 기기에 필요한 권한이 없습니다."
    case .notFound: return "요청한 항목을 찾을 수 없습니다."
    case .conflict(let code, let revision):
      let suffix = revision.map { " (현재 revision: \($0))" } ?? ""
      return "다른 기기에서 먼저 수정되어 충돌했습니다: \(code ?? "revision_conflict")\(suffix)"
    case .server(let status, let message): return "서버 오류 \(status): \(message)"
    case .transport(let message): return "네트워크 오류: \(message)"
    case .decoding(let message): return "응답 해석 오류: \(message)"
    case .encoding(let message): return "요청 생성 오류: \(message)"
    case .invalidPairingPayload(let message): return "페어링 정보가 올바르지 않습니다: \(message)"
    case .unexpectedService(let service): return "Action Hub 서버가 아닙니다: \(service)"
    case .mobileDisabled: return "서버에서 iOS Companion 기능이 비활성화되어 있습니다."
    case .unsupportedMobileAPIVersion(let version):
      return "지원하지 않는 Mobile API 버전입니다: \(version)"
    case .updateRequired(let minimumVersion):
      return "이 서버를 사용하려면 Action Hub iOS \(minimumVersion) 이상으로 업데이트해야 합니다."
    case .noStoredSession: return "연결된 Action Hub 서버가 없습니다."
    case .revoked: return "이 기기의 연결이 서버에서 해제되었습니다."
    }
  }
}

struct ErrorEnvelope: Decodable {
  let detail: JSONValue?
}

extension JSONValue {
  var stringDescription: String {
    switch self {
    case .string(let value): return value
    case .number(let value): return String(value)
    case .bool(let value): return String(value)
    case .object(let value):
      return value.map { "\($0.key)=\($0.value.stringDescription)" }.sorted().joined(
        separator: ", ")
    case .array(let value): return value.map(\.stringDescription).joined(separator: ", ")
    case .null: return "null"
    }
  }
}
