import Foundation
import LocalAuthentication

@MainActor
final class BiometricLock: ObservableObject {
  @Published private(set) var isUnlocked = false
  @Published var isEnabled: Bool {
    didSet { UserDefaults.standard.set(isEnabled, forKey: "biometricLockEnabled") }
  }
  /// Set whenever evaluation cannot even start (`canEvaluatePolicy` failed -- most commonly no
  /// device passcode set, so Face ID/Touch ID has no fallback to offer) or ends in a non-cancel
  /// failure. Previously this was silently dropped and the lock screen just sat there
  /// unresponsive with no way forward except reinstalling the app (which loses pairing).
  @Published private(set) var unavailableReason: String?

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
    var policyError: NSError?
    // `.deviceOwnerAuthentication` (unlike `.deviceOwnerAuthenticationWithBiometrics`) falls
    // back to the device passcode automatically when biometrics fail or are locked out, so this
    // check failing almost always means there is no passcode set at all -- the one case with no
    // fallback to offer.
    guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &policyError) else {
      isUnlocked = false
      suppressForegroundUnlock = true
      unavailableReason = Self.describe(policyError)
      return
    }
    isAuthenticating = true
    defer { isAuthenticating = false }
    do {
      isUnlocked = try await context.evaluatePolicy(
        .deviceOwnerAuthentication,
        localizedReason: "Action Hub의 업무 내용과 실행 상태를 확인합니다."
      )
      if isUnlocked { unavailableReason = nil }
    } catch let laError as LAError where laError.code == .userCancel {
      isUnlocked = false
    } catch {
      isUnlocked = false
      unavailableReason = Self.describe(error as NSError)
    }
    suppressForegroundUnlock = !isUnlocked
  }

  /// Explicit user choice from the lock screen's escape hatch, for when authentication cannot
  /// be completed at all (no passcode set, biometry hardware failure, repeated system lockout).
  /// Reinstalling the app to get past a locked screen would also drop the device pairing, so
  /// this has to be reachable without ever leaving RootView's locked state.
  func disableLockAndUnlock() {
    isEnabled = false
    isUnlocked = true
    unavailableReason = nil
    suppressForegroundUnlock = false
  }

  private static func describe(_ error: NSError?) -> String {
    guard let error, error.domain == LAError.errorDomain,
      let code = LAError.Code(rawValue: error.code)
    else {
      return "기기 인증을 사용할 수 없습니다: \(error?.localizedDescription ?? "알 수 없는 오류")"
    }
    switch code {
    case .passcodeNotSet:
      return "기기 암호가 설정되어 있지 않아 인증할 수 없습니다. 설정 앱에서 암호를 만들거나, 아래에서 잠금 기능을 꺼서 계속 사용하세요."
    case .biometryNotAvailable:
      return "이 기기에서 생체 인증을 사용할 수 없습니다."
    case .biometryNotEnrolled:
      return "Face ID/Touch ID가 등록되어 있지 않습니다."
    case .biometryLockout:
      return "생체 인증이 잠시 잠겼습니다. 기기 암호로 다시 시도하거나, 아래에서 잠금 기능을 꺼서 계속 사용하세요."
    default:
      return "기기 인증에 실패했습니다: \(error.localizedDescription)"
    }
  }
}
