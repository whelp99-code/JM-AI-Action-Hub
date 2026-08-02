import ActionHubCore
import Foundation
import Security

actor KeychainCredentialStore: CredentialStore {
  private let service = "com.jmactionhub.ios.mobile-session"
  private let account = "primary"

  func load() async throws -> StoredMobileSession? {
    var query: [String: Any] = baseQuery
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = result as? Data else {
      throw KeychainError.status(status)
    }
    return try ActionHubJSON.decoder().decode(StoredMobileSession.self, from: data)
  }

  func save(_ session: StoredMobileSession) async throws {
    let data = try ActionHubJSON.encoder().encode(session)
    let attributes: [String: Any] = [
      kSecValueData as String: data,
      // Background capture upload must still work while the device is locked
      // after the user has unlocked once since boot. Tokens never migrate to
      // another device or backup.
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
    ]
    let status = SecItemUpdate(baseQuery as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      var insert = baseQuery
      for (key, value) in attributes {
        insert[key] = value
      }
      let addStatus = SecItemAdd(insert as CFDictionary, nil)
      guard addStatus == errSecSuccess else { throw KeychainError.status(addStatus) }
    } else if status != errSecSuccess {
      throw KeychainError.status(status)
    }
  }

  func delete() async throws {
    let status = SecItemDelete(baseQuery as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else {
      throw KeychainError.status(status)
    }
  }

  private var baseQuery: [String: Any] {
    [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
    ]
  }
}

enum KeychainError: LocalizedError {
  case status(OSStatus)
  var errorDescription: String? {
    switch self {
    case .status(let status):
      return SecCopyErrorMessageString(status, nil) as String? ?? "Keychain error \(status)"
    }
  }
}
