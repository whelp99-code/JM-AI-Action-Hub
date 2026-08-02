import Foundation

public struct SemanticVersion: Comparable, Sendable, Equatable {
  public let components: [Int]

  public init?(_ raw: String) {
    let values = raw.split(separator: ".", omittingEmptySubsequences: false)
    guard !values.isEmpty, values.allSatisfy({ !$0.isEmpty && Int($0) != nil }) else { return nil }
    components = values.map { Int($0)! }
  }

  public static func == (lhs: SemanticVersion, rhs: SemanticVersion) -> Bool {
    compare(lhs, rhs) == 0
  }

  public static func < (lhs: SemanticVersion, rhs: SemanticVersion) -> Bool {
    compare(lhs, rhs) < 0
  }

  public static func requiresUpdate(current: String, minimum: String) -> Bool {
    guard let currentVersion = SemanticVersion(current),
      let minimumVersion = SemanticVersion(minimum)
    else { return true }
    return currentVersion < minimumVersion
  }

  private static func compare(_ lhs: SemanticVersion, _ rhs: SemanticVersion) -> Int {
    let count = max(lhs.components.count, rhs.components.count)
    for index in 0..<count {
      let left = index < lhs.components.count ? lhs.components[index] : 0
      let right = index < rhs.components.count ? rhs.components[index] : 0
      if left != right { return left < right ? -1 : 1 }
    }
    return 0
  }
}
