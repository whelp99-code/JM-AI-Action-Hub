import ActionHubCore
import AVFoundation
import Foundation
import Speech
import UIKit

/// `AVAudioNode.installTap` invokes its block on the audio/realtime queue. Keep the legacy
/// Speech request behind an explicit Sendable boundary so a closure created from this
/// `@MainActor` service cannot inherit main-actor isolation and trap when the audio thread calls
/// it. `SFSpeechAudioBufferRecognitionRequest.append` is specifically designed to receive the
/// buffers produced by an audio tap; the unchecked boundary documents that ownership contract.
private final class SpeechAudioBufferRequestBox: @unchecked Sendable {
  private let request: SFSpeechAudioBufferRecognitionRequest

  init(_ request: SFSpeechAudioBufferRecognitionRequest) {
    self.request = request
  }

  func append(_ buffer: AVAudioPCMBuffer) {
    request.append(buffer)
  }
}

@MainActor
final class SpeechCaptureService: ObservableObject {
  @Published private(set) var isRecording = false
  @Published private(set) var transcript = ""
  @Published var errorMessage: String?
  /// True when `errorMessage` (or the pre-flight hint below) means the user must go to
  /// Settings.app to fix this -- the system permission prompt cannot resolve it anymore.
  @Published private(set) var needsSettingsAction = false
  /// Non-nil as soon as the view appears, before the user ever taps the button, when a
  /// permission was already denied in a previous session. Lets the UI show the problem instead
  /// of waiting for a tap that will silently no-op.
  @Published private(set) var permissionHint: String?

  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ko-KR"))
  private let audioEngine = AVAudioEngine()
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private var tapInstalled = false

  init() {
    refreshPermissionStatus()
  }

  /// Re-reads the current permission state without prompting. Call this from `onAppear` and
  /// whenever the app returns from the foreground (e.g. after the user visits Settings.app),
  /// since permission changes made there don't otherwise notify this object.
  func refreshPermissionStatus() {
    let (speech, microphone) = currentPermissionStatus()
    permissionHint = SpeechPermissionCopy.blockingMessage(speech: speech, microphone: microphone)
  }

  func openSettings() {
    guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
    UIApplication.shared.open(url)
  }

  private func currentPermissionStatus() -> (
    speech: SpeechPermissionStatus, microphone: SpeechPermissionStatus
  ) {
    let speech: SpeechPermissionStatus
    switch SFSpeechRecognizer.authorizationStatus() {
    case .notDetermined: speech = .notDetermined
    case .authorized: speech = .authorized
    case .denied: speech = .denied
    case .restricted: speech = .restricted
    @unknown default: speech = .denied
    }
    let microphone: SpeechPermissionStatus
    switch AVAudioApplication.shared.recordPermission {
    case .undetermined: microphone = .notDetermined
    case .granted: microphone = .authorized
    case .denied: microphone = .denied
    @unknown default: microphone = .denied
    }
    return (speech, microphone)
  }

  /// `nonisolated` is load-bearing. `SFSpeechRecognizer.requestAuthorization` runs its completion
  /// handler on an arbitrary background queue, but this type is `@MainActor`, so the handler
  /// inherited main-actor isolation and Swift 6's executor check trapped the process the instant
  /// it ran (`dispatch_assert_queue_fail`, SIGTRAP). The app disappeared to the home screen with
  /// no error the first time anyone tapped 음성 입력. Resume with a `Bool` so no non-Sendable
  /// value crosses the isolation boundary either.
  nonisolated func requestAuthorization() async -> Bool {
    let speech = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
      SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0 == .authorized) }
    }
    let microphone = await AVAudioApplication.requestRecordPermission()
    return speech && microphone
  }

  func start() async {
    guard !isRecording else { return }
    errorMessage = nil
    needsSettingsAction = false

    // A permission denied in a previous session never re-prompts -- `requestAuthorization()`
    // below would just fail again with no UI. Catch that up front with copy that tells the user
    // what to do, instead of a bare "permission required" message.
    let (speechStatus, microphoneStatus) = currentPermissionStatus()
    if let blocked = SpeechPermissionCopy.blockingMessage(
      speech: speechStatus, microphone: microphoneStatus)
    {
      errorMessage = blocked
      needsSettingsAction = SpeechPermissionCopy.needsSettingsAction(
        speech: speechStatus, microphone: microphoneStatus)
      permissionHint = blocked
      return
    }

    guard let recognizer, recognizer.isAvailable else {
      errorMessage = "현재 음성 인식 서비스를 사용할 수 없습니다."
      return
    }

    guard await requestAuthorization() else {
      errorMessage = "마이크와 음성 인식 권한이 필요합니다."
      refreshPermissionStatus()
      needsSettingsAction = permissionHint != nil
      return
    }

    permissionHint = nil
    await beginRecognition(recognizer: recognizer, preferOnDevice: true)
  }

  /// Runs one recognition attempt. On-device recognition is preferred for privacy, but
  /// `SFSpeechRecognizer.supportsOnDeviceRecognition` only reports hardware/OS capability, not
  /// whether the `ko-KR` on-device model is actually downloaded -- there is no public API to
  /// check that ahead of time. If the on-device attempt errors out before producing a single
  /// partial result (the signature of a missing/unavailable model, as opposed to a mid-stream
  /// audio/network hiccup), we transparently retry once against the server-based recognizer
  /// rather than leaving the user with a dead button.
  private func beginRecognition(recognizer: SFSpeechRecognizer, preferOnDevice: Bool) async {
    stop()
    transcript = ""

    do {
      let audioSession = AVAudioSession.sharedInstance()
      try audioSession.setCategory(.record, mode: .measurement, options: [.duckOthers])
      try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

      let request = SFSpeechAudioBufferRecognitionRequest()
      request.shouldReportPartialResults = true
      if preferOnDevice && recognizer.supportsOnDeviceRecognition {
        request.requiresOnDeviceRecognition = true
      }
      self.request = request

      let input = audioEngine.inputNode
      let format = input.outputFormat(forBus: 0)
      let requestBox = SpeechAudioBufferRequestBox(request)
      let tapHandler: @Sendable (AVAudioPCMBuffer, AVAudioTime) -> Void = { [requestBox] buffer, _ in
        requestBox.append(buffer)
      }
      input.installTap(onBus: 0, bufferSize: 1_024, format: format, block: tapHandler)
      tapInstalled = true
      audioEngine.prepare()
      try audioEngine.start()
      isRecording = true
      task = recognizer.recognitionTask(with: request) { [weak self] result, error in
        Task { @MainActor in
          guard let self else { return }
          if let result { self.transcript = result.bestTranscription.formattedString }
          if let error {
            if preferOnDevice && self.transcript.isEmpty {
              self.stop()
              await self.beginRecognition(recognizer: recognizer, preferOnDevice: false)
              return
            }
            self.errorMessage = error.localizedDescription
            self.stop()
          } else if result?.isFinal == true {
            self.stop()
          }
        }
      }
    } catch {
      cleanupAudio()
      errorMessage = error.localizedDescription
    }
  }

  func stop() {
    if audioEngine.isRunning { audioEngine.stop() }
    if tapInstalled {
      audioEngine.inputNode.removeTap(onBus: 0)
      tapInstalled = false
    }
    request?.endAudio()
    task?.cancel()
    request = nil
    task = nil
    isRecording = false
    try? AVAudioSession.sharedInstance().setActive(
      false, options: .notifyOthersOnDeactivation)
  }

  private func cleanupAudio() {
    if audioEngine.isRunning { audioEngine.stop() }
    if tapInstalled {
      audioEngine.inputNode.removeTap(onBus: 0)
      tapInstalled = false
    }
    request = nil
    task = nil
    isRecording = false
    try? AVAudioSession.sharedInstance().setActive(
      false, options: .notifyOthersOnDeactivation)
  }
}
