import ActionHubCore
import SwiftUI

struct SettingsView: View {
  @EnvironmentObject private var model: AppModel
  @EnvironmentObject private var lock: BiometricLock
  @State private var showDisconnect = false
  @State private var showPurgeDeadLetters = false

  var body: some View {
    Form {
      Section("연결") {
        switch model.connectionState {
        case .connected(let deviceName):
          LabeledContent("기기", value: deviceName)
          LabeledContent("서버", value: model.dashboard?.serverVersion ?? "연결됨")
          LabeledContent(
            "마지막 동기화",
            value: model.dashboard?.generatedAt.formatted(date: .abbreviated, time: .shortened)
              ?? "-")
        default:
          LabeledContent("상태", value: "연결 안 됨")
        }
        LabeledContent("오프라인 큐", value: "\(model.pendingCaptureCount)건")
        Button("지금 동기화") {
          Task {
            await model.flushCaptures()
            await model.refreshAll()
          }
        }
      }

      Section("오프라인 수집 진단") {
        LabeledContent("Dead Letter", value: "\(model.deadLetterCaptureCount)건")
        if model.deadLetters.isEmpty {
          Text("복구 또는 삭제가 필요한 실패 수집이 없습니다.")
            .font(.footnote)
            .foregroundStyle(.secondary)
        } else {
          ForEach(model.deadLetters) { deadLetter in
            VStack(alignment: .leading, spacing: 2) {
              Text(deadLetter.record.capture.text).lineLimit(1)
              Text("재시도 \(deadLetter.record.attemptCount)회 · \(deadLetter.record.lastError ?? "서버 오류")")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            }
          }
        }
        Button("모두 복원") { Task { await model.restoreAllDeadLetters() } }
          .disabled(model.deadLetterCaptureCount == 0)
        Button("모두 삭제", role: .destructive) { showPurgeDeadLetters = true }
          .disabled(model.deadLetterCaptureCount == 0)
      }

      Section("보안") {
        Toggle("앱 열 때 Face ID/기기 인증", isOn: $lock.isEnabled)
        Text("관리자 API 키와 Todoist·GitHub·Google 토큰은 iPhone에 저장하지 않습니다.")
          .font(.footnote).foregroundStyle(.secondary)
      }

      Section("알림") {
        Toggle("검토 필요", isOn: $model.notificationPreferences.reviewRequired)
        Toggle("AI 실행 상태", isOn: $model.notificationPreferences.aiStatus)
        Toggle("Follow-up 도래", isOn: $model.notificationPreferences.followUpDue)
        Toggle("Deadline 위험", isOn: $model.notificationPreferences.deadlineRisk)
        Toggle("커넥터 실패", isOn: $model.notificationPreferences.connectorFailure)
        Button("알림 설정 저장") {
          Task {
            do {
              _ = try await model.updateNotificationPreferences(model.notificationPreferences)
            } catch {
              model.lastError = error.localizedDescription
            }
          }
        }
        Button("시스템 알림 권한 요청") { NotificationManager.shared.requestAuthorizationAndRegister() }
      }

      Section("앱") {
        LabeledContent("iOS 앱", value: AppConfiguration.appVersion)
        LabeledContent("최소 서버", value: "0.9.0")
        NavigationLink("개인정보 처리 원칙") { PrivacyPrinciplesView() }
      }

      Section {
        Button("이 iPhone 연결 해제", role: .destructive) { showDisconnect = true }
      }
    }
    .navigationTitle("설정")
    .confirmationDialog("서버에서도 이 기기의 Refresh Token을 폐기합니다.", isPresented: $showDisconnect) {
      Button("연결 해제", role: .destructive) { Task { await model.disconnect() } }
    }
    .alert("Dead Letter 모두 삭제", isPresented: $showPurgeDeadLetters) {
      Button("모두 삭제", role: .destructive) {
        Task { await model.purgeAllDeadLetters(confirmed: true) }
      }
      Button("취소", role: .cancel) {}
    } message: {
      Text("\(model.deadLetterCaptureCount)건을 삭제하면 복구 불가합니다.")
    }
    .task { await model.refreshDeadLetters() }
  }
}

private struct PrivacyPrinciplesView: View {
  var body: some View {
    List {
      Section("기기") {
        Text("관리자 API 키와 Todoist·GitHub·Google 자격증명은 iPhone에 저장하지 않습니다.")
        Text("기기에는 Action Hub 전용 회전형 Refresh Token만 Keychain에 저장합니다.")
      }
      Section("수집") {
        Text("공유·음성 입력은 사용자가 명시적으로 실행할 때만 수집합니다.")
        Text("음성 원본은 저장하지 않고 전사된 텍스트만 검토 큐로 보냅니다.")
      }
      Section("알림") {
        Text("푸시 알림에는 원문이나 고객 정보를 넣지 않고 이벤트 유형과 내부 ID만 전달합니다.")
      }
      Section("삭제") {
        Text("기기 연결 해제 시 서버의 Refresh Token 계열을 폐기하고 로컬 Keychain 세션을 삭제합니다.")
      }
    }
    .navigationTitle("개인정보 원칙")
  }
}
