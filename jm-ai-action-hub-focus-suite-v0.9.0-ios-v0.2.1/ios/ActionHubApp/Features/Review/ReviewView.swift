import ActionHubCore
import SwiftUI

struct ReviewView: View {
  @EnvironmentObject private var model: AppModel

  var body: some View {
    Group {
      if model.reviewPlans.isEmpty {
        ContentUnavailableView {
          Label("검토 대기 없음", systemImage: "checkmark.circle")
        } description: {
          Text("공유하거나 입력한 내용의 분석 결과가 여기에 표시됩니다.")
        } actions: {
          Button("빠른 입력") { model.isCapturePresented = true }
        }
      } else {
        List(model.reviewPlans) { plan in
          NavigationLink(value: plan.id) { ReviewPlanRow(plan: plan) }
        }
        .refreshable { await model.refreshAll() }
      }
    }
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

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack {
        Text(plan.summary.isEmpty ? "Action Plan" : plan.summary)
          .font(.headline)
          .lineLimit(2)
        Spacer()
        Text("\(plan.items.count)건")
          .font(.caption.bold())
          .padding(.horizontal, 8).padding(.vertical, 4)
          .background(.tint.opacity(0.12), in: Capsule())
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
