import ActionHubCore
import SwiftUI

struct ReviewView: View {
  @EnvironmentObject private var model: AppModel

  var body: some View {
    Group {
      if model.reviewPlans.isEmpty {
        // Wrapped in a ScrollView so `.refreshable` below has something to attach a pull
        // gesture to -- ContentUnavailableView alone isn't scrollable and previously left the
        // empty state with no way to refresh except the badge count changing on its own.
        ScrollView {
          ContentUnavailableView {
            Label("검토 대기 없음", systemImage: "checkmark.circle")
          } description: {
            Text("공유하거나 입력한 내용의 분석 결과가 여기에 표시됩니다.")
          } actions: {
            Button("빠른 입력") { model.isCapturePresented = true }
          }
        }
      } else {
        List(model.reviewPlans) { plan in
          NavigationLink(value: plan.id) { ReviewPlanRow(plan: plan) }
        }
      }
    }
    .refreshable { await model.refreshAllDetached() }
    .navigationTitle("검토")
    .onChange(of: model.presentedPlanId) { _, planId in
      // Deep links select this tab; the user can open the highlighted plan from the list.
      guard let planId else { return }
      model.prioritizeReviewPlan(planId)
    }
  }
}

private struct ReviewPlanRow: View {
  let plan: ActionPlan

  /// For a capture the parser found nothing in, the server summary reads
  /// "0개 항목 · 실행 가능 0개" -- true, and useless for recognising which share this was.
  /// Show the captured text instead, which is the only thing that identifies it.
  private var headline: String {
    guard plan.items.isEmpty else {
      return plan.summary.isEmpty ? "Action Plan" : plan.summary
    }
    let raw = (plan.inbox?.rawText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    return raw.isEmpty ? "실행할 일 없음" : raw
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack {
        Text(headline)
          .font(.headline)
          .lineLimit(2)
        Spacer()
        Text(plan.items.isEmpty ? "원문만" : "\(plan.items.count)건")
          .font(.caption.bold())
          .padding(.horizontal, 8).padding(.vertical, 4)
          .background(.tint.opacity(0.12), in: Capsule())
      }
      if plan.items.isEmpty {
        Text("실행할 일을 찾지 못해 원문만 보관했습니다.")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      HStack(spacing: 10) {
        Label(plan.status, systemImage: "circle.dotted")
        Label(plan.updatedAt.formatted(date: .abbreviated, time: .shortened), systemImage: "clock")
      }
      .font(.caption)
      .foregroundStyle(.secondary)
    }
    .padding(.vertical, 4)
  }
}
