import AVFoundation
import Foundation
import Speech

@MainActor
final class SpeechCaptureService: ObservableObject {
  @Published private(set) var isRecording = false
  @Published private(set) var transcript = ""
  @Published var errorMessage: String?

  private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "ko-KR"))
  private let audioEngine = AVAudioEngine()
  private var request: SFSpeechAudioBufferRecognitionRequest?
  private var task: SFSpeechRecognitionTask?
  private var tapInstalled = false

  func requestAuthorization() async -> Bool {
    let speech = await withCheckedContinuation { continuation in
      SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
    }
    let microphone = await AVAudioApplication.requestRecordPermission()
    return speech == .authorized && microphone
  }

  func start() async {
    guard !isRecording else { return }
    guard let recognizer, recognizer.isAvailable else {
      errorMessage = "현재 음성 인식 서비스를 사용할 수 없습니다."
      return
    }
    guard await requestAuthorization() else {
      errorMessage = "마이크와 음성 인식 권한이 필요합니다."
      return
    }

    stop()
    transcript = ""
    errorMessage = nil

    do {
      let audioSession = AVAudioSession.sharedInstance()
      try audioSession.setCategory(.record, mode: .measurement, options: [.duckOthers])
      try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

      let request = SFSpeechAudioBufferRecognitionRequest()
      request.shouldReportPartialResults = true
      if recognizer.supportsOnDeviceRecognition {
        request.requiresOnDeviceRecognition = true
      }
      self.request = request

      let input = audioEngine.inputNode
      let format = input.outputFormat(forBus: 0)
      input.installTap(onBus: 0, bufferSize: 1_024, format: format) { buffer, _ in
        request.append(buffer)
      }
      tapInstalled = true
      audioEngine.prepare()
      try audioEngine.start()
      isRecording = true
      task = recognizer.recognitionTask(with: request) { [weak self] result, error in
        Task { @MainActor in
          if let result { self?.transcript = result.bestTranscription.formattedString }
          if let error {
            self?.errorMessage = error.localizedDescription
            self?.stop()
          } else if result?.isFinal == true {
            self?.stop()
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
