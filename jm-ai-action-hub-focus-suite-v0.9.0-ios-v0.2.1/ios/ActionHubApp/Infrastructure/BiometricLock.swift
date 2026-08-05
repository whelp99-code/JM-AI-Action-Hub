import Foundation
import LocalAuthentication

@MainActor
final class BiometricLock: ObservableObject {
  @Published private(set) var isUnlocked = false
  @Published var isEnabled: Bool {
    didSet { UserDefaults.standard.set(isEnabled, forKey: "biometricLockEnabled") }
  }

  private var isAuthenticating = false
  /// Set when an evaluation ends without unlocking. The system authentication sheet moves the
  /// app through `.inactive` → `.active`, so a foreground-triggered retry would re-prompt
  /// immediately and trap the user in a loop. Cleared on `lock()`, i.e. the next session.
  private var suppressForegroundUnlock = false

  init() {
    isEnabled = UserDefaults.standard.object(forKey: "biometricLockEnabled") as? Bool ?? true
    isUnlocked = !isEnabled
  }

  func lock() {
    if isEnabled { isUnlocked = false }
    suppressForegroundUnlock = false
  }

  /// Foreground entry point. Returning to `.active` also happens right after the
  /// authentication sheet closes, so this must not start a second evaluation.
  func unlockIfNeeded() async {
    guard !suppressForegroundUnlock else { return }
    await unlock()
  }

  func unlock() async {
    guard isEnabled else {
      isUnlocked = true
      return
    }
    guard !isUnlocked, !isAuthenticating else { return }
    let context = LAContext()
    context.localizedCancelTitle = "취소"
    var error: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
      isUnlocked = false
      suppressForegroundUnlock = true
      return
    }
    isAuthenticating = true
    defer { isAuthenticating = false }
    do {
      isUnlocked = try await context.evaluatePolicy(
        .deviceOwnerAuthentication,
        localizedReason: "Action Hub의 업무 내용과 실행 상태를 확인합니다."
      )
    } catch {
      isUnlocked = false
    }
    suppressForegroundUnlock = !isUnlocked
  }
}
