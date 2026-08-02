import Foundation
import LocalAuthentication

@MainActor
final class BiometricLock: ObservableObject {
  @Published private(set) var isUnlocked = false
  @Published var isEnabled: Bool {
    didSet { UserDefaults.standard.set(isEnabled, forKey: "biometricLockEnabled") }
  }

  init() {
    isEnabled = UserDefaults.standard.object(forKey: "biometricLockEnabled") as? Bool ?? true
    isUnlocked = !isEnabled
  }

  func lock() {
    if isEnabled { isUnlocked = false }
  }

  func unlock() async {
    guard isEnabled else {
      isUnlocked = true
      return
    }
    let context = LAContext()
    context.localizedCancelTitle = "취소"
    var error: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
      isUnlocked = false
      return
    }
    do {
      isUnlocked = try await context.evaluatePolicy(
        .deviceOwnerAuthentication,
        localizedReason: "Action Hub의 업무 내용과 실행 상태를 확인합니다."
      )
    } catch {
      isUnlocked = false
    }
  }
}
