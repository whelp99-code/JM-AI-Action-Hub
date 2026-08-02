import Foundation

struct AppConfiguration {
  static let appGroupIdentifier: String = {
    Bundle.main.object(forInfoDictionaryKey: "ActionHubAppGroup") as? String
      ?? "group.com.jmactionhub.shared"
  }()

  static let refreshTaskIdentifier =
    (Bundle.main.bundleIdentifier ?? "com.jmactionhub.ios") + ".refresh"
  static let appVersion =
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.2.1"
  static let pushEnvironment: String = {
    #if DEBUG
      "sandbox"
    #else
      "production"
    #endif
  }()
}
