import Foundation

/// Platform-independent mirror of `SFSpeechRecognizerAuthorizationStatus` /
/// `AVAudioApplication.recordPermission`, so the mapping from permission state to user-facing
/// copy can be unit tested without linking Speech/AVFoundation.
public enum SpeechPermissionStatus: Equatable, Sendable {
  case notDetermined
  case authorized
  case denied
  case restricted
}

/// Maps microphone + speech-recognition authorization into the message `SpeechCaptureService`
/// should show before the user even taps the record button, so a previously-denied permission
/// never presents as "nothing happened."
public enum SpeechPermissionCopy {
  /// `nil` means both permissions are usable (authorized or not-yet-asked); a non-nil value is a
  /// blocking reason that should be shown with a way to open Settings, except `.notDetermined`
  /// which resolves itself via the system prompt and needs no Settings link.
  public static func blockingMessage(
    speech: SpeechPermissionStatus, microphone: SpeechPermissionStatus
  ) -> String? {
    if speech == .restricted || microphone == .restricted {
      return "이 기기에서는 음성 입력이 제한되어 있습니다."
    }
    if speech == .denied || microphone == .denied {
      return "마이크와 음성 인식 권한이 꺼져 있습니다. 설정에서 권한을 켜주세요."
    }
    return nil
  }

  /// Whether `blockingMessage` for this pair should be paired with an "open Settings" action
  /// (as opposed to a state the system permission prompt can still resolve).
  public static func needsSettingsAction(
    speech: SpeechPermissionStatus, microphone: SpeechPermissionStatus
  ) -> Bool {
    speech == .denied || speech == .restricted || microphone == .denied
      || microphone == .restricted
  }
}

/// Decides what a speech-recognition partial/final transcript result should do to the capture
/// text field, without depending on `Speech`/`SwiftUI`.
public enum SpeechTranscriptMerge {
  /// - Parameters:
  ///   - currentText: the text field's current value.
  ///   - lastApplied: the value the field held right after the previous speech result was
  ///     written into it (or the pre-recording snapshot, before any result has arrived).
  ///   - baseText: the text that was already in the field when recording started; preserved and
  ///     prefixed rather than overwritten.
  ///   - newResult: the newest (cumulative) transcript from the recognizer.
  /// - Returns: the field's new value, or `nil` if `currentText` has drifted from `lastApplied`
  ///   -- meaning the user edited the field by hand since the last result, and this result must
  ///   not stomp that edit.
  public static func apply(
    currentText: String, lastApplied: String, baseText: String, newResult: String
  ) -> String? {
    guard currentText == lastApplied else { return nil }
    guard !newResult.isEmpty else { return nil }
    if baseText.isEmpty { return newResult }
    if baseText.hasSuffix(" ") || baseText.hasSuffix("\n") { return baseText + newResult }
    return baseText + " " + newResult
  }
}
