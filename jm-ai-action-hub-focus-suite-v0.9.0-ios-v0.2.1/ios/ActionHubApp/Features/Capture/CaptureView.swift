import SwiftUI
import UIKit

struct CaptureView: View {
  @EnvironmentObject private var model: AppModel
  @Environment(\.dismiss) private var dismiss
  @StateObject private var speech = SpeechCaptureService()
  @State private var text = ""
  @State private var isSubmitting = false
  @FocusState private var focused: Bool

  var body: some View {
    NavigationStack {
      VStack(spacing: 16) {
        TextEditor(text: $text)
          .focused($focused)
          .font(.body)
          .padding(10)
          .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))
          .overlay(alignment: .topLeading) {
            if text.isEmpty {
              Text("예: 내일 오전 10시 고객 미팅, 미팅 전에 GPU 라이선스 확인")
                .foregroundStyle(.secondary)
                .padding(18)
                .allowsHitTesting(false)
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
              if speech.isRecording { speech.stop() } else { await speech.start() }
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

        if let error = speech.errorMessage {
          Label(error, systemImage: "exclamationmark.triangle.fill")
            .font(.footnote)
            .foregroundStyle(.red)
            .accessibilityLabel("음성 입력 오류: \(error)")
        }
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
        guard !value.isEmpty else { return }
        text = value
      }
      .onAppear { focused = true }
      .onDisappear { speech.stop() }
    }
  }
}
