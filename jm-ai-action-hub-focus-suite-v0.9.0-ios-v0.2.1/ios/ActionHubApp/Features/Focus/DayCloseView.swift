import ActionHubCore
import SwiftUI

struct DayCloseView: View {
  @EnvironmentObject private var model: AppModel
  @State private var decisions: [String: String] = [:]
  @State private var reasons: [String: String] = [:]
  @State private var isSubmitting = false

  private var items: [FocusActionSummary] {
    let human = model.big3?.human.compactMap(\.action) ?? []
    let ai = model.big3?.ai.compactMap(\.action) ?? []
    return (human + ai).filter { $0.state != "completed" }
  }

  var body: some View {
    List {
      Section {
        if items.isEmpty { Text("오늘 정리할 미완료 Big3가 없습니다.").foregroundStyle(.secondary) }
        ForEach(items) { item in
          VStack(alignment: .leading, spacing: 10) {
            Text(item.title).font(.headline)
            Picker("결정", selection: binding(for: item.id)) {
              Text("선택").tag("")
              Text("내일 재계획").tag("reschedule")
              Text("작업 분할").tag("split")
              Text("AI 위임").tag("delegate")
              Text("취소").tag("cancel")
            }
            .pickerStyle(.menu)
            TextField("이유", text: reasonBinding(for: item.id))
              .textFieldStyle(.roundedBorder)
          }
          .padding(.vertical, 4)
        }
      } header: {
        Text("승인형 이월")
      }

      if let report = model.focusWeeklyReport {
        Section("최근 7일") {
          LabeledContent("집중시간", value: "\(report.focusMinutes)분")
          LabeledContent("Big3 완료율", value: "\(Int(report.big3CompletionRate))%")
          LabeledContent("Q2 투자", value: "\(report.q2InvestmentMinutes)분")
          LabeledContent("이월", value: "\(report.carryOverCount)건")
          ForEach(report.recommendations, id: \.self) { Label($0, systemImage: "lightbulb") }
        }
      }
    }
    .safeAreaInset(edge: .bottom) {
      Button {
        Task { await submit() }
      } label: {
        if isSubmitting {
          ProgressView().frame(maxWidth: .infinity)
        } else {
          Text("하루 마감 반영").frame(maxWidth: .infinity)
        }
      }
      .buttonStyle(.borderedProminent)
      .disabled(isSubmitting || decisions.values.allSatisfy(\.isEmpty))
      .padding()
      .background(.bar)
    }
    .refreshable { await model.refreshAllDetached() }
    .task { await model.loadFocusWeeklyReport() }
  }

  private func binding(for id: String) -> Binding<String> {
    Binding(get: { decisions[id, default: ""] }, set: { decisions[id] = $0 })
  }

  private func reasonBinding(for id: String) -> Binding<String> {
    Binding(get: { reasons[id, default: ""] }, set: { reasons[id] = $0 })
  }

  private func submit() async {
    isSubmitting = true
    defer { isSubmitting = false }
    let payload = items.compactMap { item -> DayCloseDecisionInput? in
      guard let decision = decisions[item.id], !decision.isEmpty else { return nil }
      return DayCloseDecisionInput(
        actionItemId: item.id,
        decision: decision,
        reason: reasons[item.id, default: ""],
        executor: decision == "delegate" ? .ai : nil)
    }
    guard !payload.isEmpty else { return }
    do {
      _ = try await model.closeDay(payload)
      decisions = [:]
      reasons = [:]
      await model.loadFocusWeeklyReport()
    } catch { model.handle(error) }
  }
}
