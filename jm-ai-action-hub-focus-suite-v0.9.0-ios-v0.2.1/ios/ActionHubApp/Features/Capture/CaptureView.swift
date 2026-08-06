import ActionHubCore
import SwiftUI
import UIKit

struct CaptureView: View {
  @EnvironmentObject private var model: AppModel
  @Environment(\.dismiss) private var dismiss
  @StateObject private var speech = SpeechCaptureService()
  @State private var text = ""
  @State private var isSubmitting = false
  @FocusState private var focused: Bool
  /// The value of `text` the last time it was set from a speech partial result. Used to detect
  /// a manual edit made mid-recording: if `text` has drifted from this, the user typed
  /// something, and the next partial result must not silently overwrite it.
  @State private var lastAppliedTranscript = ""
  /// The text already in the field when recording started. Speech results are appended after
  /// this rather than replacing it, so starting the mic with existing notes doesn't wipe them.
  @State private var recordingBaseText = ""

  private var visibleSpeechError: String? { speech.errorMessage ?? speech.permissionHint }

  var body: some View {
    NavigationStack {
      VStack(spacing: 16) {
        TextEditor(text: $text)
          .focused($focused)
          .font(.body)
          .padding(10)
          .frame(minHeight: 100, maxHeight: 220)
          .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))
          .overlay(alignment: .topLeading) {
            if text.isEmpty {
              Text("예: 내일 오전 10시 고객 미팅, 미팅 전에 GPU 라이선스 확인")
                .foregroundStyle(.secondary)
                .padding(18)
                .allowsHitTesting(false)
            }
          }

        // Placed directly under the text field -- above the button row -- so it stays visible
        // even at the `.medium` sheet detent, instead of being the last (and first-clipped)
        // element at the bottom of the stack.
        if let error = visibleSpeechError {
          VStack(alignment: .leading, spacing: 6) {
            Label(error, systemImage: "exclamationmark.triangle.fill")
              .font(.footnote)
              .foregroundStyle(.red)
              .accessibilityLabel("음성 입력 오류: \(error)")
            if speech.needsSettingsAction {
              Button("설정 앱에서 권한 켜기") { speech.openSettings() }
                .font(.footnote.bold())
            }
          }
        }

        HStack {
          Button {
            if let value = UIPasteboard.general.string, !value.isEmpty { text = value }
          } label: {
            Label("붙여넣기", systemImage: "doc.on.clipboard")
          }

          Spacer()

          Button {
            Task {
              if speech.isRecording {
                speech.stop()
              } else {
                recordingBaseText = text
                lastAppliedTranscript = text
                await speech.start()
              }
            }
          } label: {
            Label(
              speech.isRecording ? "중지" : "음성",
              systemImage: speech.isRecording ? "stop.circle.fill" : "mic.fill"
            )
            .foregroundStyle(speech.isRecording ? .red : .primary)
          }
        }
        .buttonStyle(.bordered)

        if model.pendingCaptureCount > 0 {
          Label(
            "오프라인 전송 대기 \(model.pendingCaptureCount)건", systemImage: "arrow.triangle.2.circlepath"
          )
          .font(.footnote)
          .foregroundStyle(.secondary)
        }

        Spacer(minLength: 0)
      }
      .padding()
      .navigationTitle("빠른 입력")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
        ToolbarItem(placement: .confirmationAction) {
          Button("수집") {
            isSubmitting = true
            Task {
              let ok = await model.capture(text: text)
              isSubmitting = false
              if ok { dismiss() }
            }
          }
          .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSubmitting)
        }
      }
      .onChange(of: speech.transcript) { _, value in
        guard
          let merged = SpeechTranscriptMerge.apply(
            currentText: text, lastApplied: lastAppliedTranscript, baseText: recordingBaseText,
            newResult: value)
        else { return }
        text = merged
        lastAppliedTranscript = merged
      }
      .onAppear {
        focused = true
        speech.refreshPermissionStatus()
      }
      .onDisappear { speech.stop() }
      .onReceive(
        NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
      ) { _ in
        // Permission changes made in Settings.app while this sheet stayed open don't otherwise
        // notify `speech` -- re-check on every return to the foreground.
        speech.refreshPermissionStatus()
      }
    }
  }
}
