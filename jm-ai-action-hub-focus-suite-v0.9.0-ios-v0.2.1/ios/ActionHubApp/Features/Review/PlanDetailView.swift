import ActionHubCore
import SwiftUI

/// A structural review block returned by the server (`blockedItemIds` on the plan). Shown so a
/// user can see *why* an approval didn't go through instead of it silently doing nothing, and
/// can explicitly opt in to forcing it through -- see AppModel.approve(forceReviewItems:).
private struct BlockedApproval: Identifiable {
  let id = UUID()
  let itemIds: [String]
  let items: [(title: String, reason: String)]
  let alsoExecute: Bool
}

struct PlanDetailView: View {
  @EnvironmentObject private var model: AppModel
  @Environment(\.dismiss) private var dismiss
  let planId: String
  @State private var plan: ActionPlan?
  @State private var isWorking = false
  @State private var selectedItem: ActionItem?
  @State private var showRejectConfirmation = false
  @State private var blockedApproval: BlockedApproval?
  @State private var confirmationMessage: String?

  private static let terminalItemStates: Set<String> = [
    "completed", "rejected", "skipped_duplicate", "cancelled",
  ]

  private var hasDraftItems: Bool {
    plan?.items.contains { $0.state == "draft" } ?? false
  }

  private var hasActionableItems: Bool {
    plan?.items.contains { !Self.terminalItemStates.contains($0.state) } ?? false
  }

  var body: some View {
    Group {
      if let plan {
        List {
          Section {
            Text(plan.summary)
            LabeledContent("상태", value: plan.status)
            LabeledContent("분석기", value: plan.parserName)
            LabeledContent("Revision", value: String(plan.revision))
          } header: {
            Text("계획")
          }

          Section("실행 항목") {
            ForEach(plan.items) { item in
              Button {
                selectedItem = item
              } label: {
                ActionItemRow(item: item)
              }
              .buttonStyle(.plain)
            }
          }

          Section {
            Button {
              Task { await approveOnly(plan) }
            } label: {
              Label("검토 승인", systemImage: "checkmark.seal")
            }
            .disabled(isWorking || !hasDraftItems)

            Button {
              Task { await approveAndExecute(plan) }
            } label: {
              Label("승인 후 등록·실행", systemImage: "paperplane.fill")
            }
            .disabled(isWorking || !hasActionableItems)

            Button(role: .destructive) {
              showRejectConfirmation = true
            } label: {
              Label("전체 제외", systemImage: "xmark.circle")
            }
            .disabled(isWorking || !hasActionableItems)
          }
        }
        .refreshable { await Task { await load() }.value }
        .confirmationDialog("이 계획의 모든 항목을 제외합니까?", isPresented: $showRejectConfirmation) {
          Button("전체 제외", role: .destructive) { Task { await reject(plan) } }
        }
        .sheet(item: $selectedItem) { item in
          ActionItemEditor(plan: plan, item: item) { updated in
            self.plan = updated
          }
        }
        .alert(
          "검토가 더 필요합니다", isPresented: blockedApprovalPresented, presenting: blockedApproval
        ) { info in
          Button("강제 승인", role: .destructive) { Task { await forceApprove(info) } }
          Button("취소", role: .cancel) {}
        } message: { info in
          Text(
            info.items.map { "\($0.title): \($0.reason)" }.joined(separator: "\n")
              + "\n\n검토 이유를 해결하지 않고 그대로 승인할 수 있습니다. 실행이 실패할 수 있습니다.")
        }
        .alert(
          "Action Hub", isPresented: confirmationMessagePresented
        ) {
          Button("확인") {}
        } message: {
          Text(confirmationMessage ?? "")
        }
      } else {
        ProgressView("계획 불러오는 중…")
      }
    }
    .navigationTitle("검토 상세")
    .navigationBarTitleDisplayMode(.inline)
    .overlay { if isWorking { ProgressView().controlSize(.large) } }
    .task { await load() }
  }

  private var blockedApprovalPresented: Binding<Bool> {
    Binding(get: { blockedApproval != nil }, set: { if !$0 { blockedApproval = nil } })
  }

  private var confirmationMessagePresented: Binding<Bool> {
    Binding(get: { confirmationMessage != nil }, set: { if !$0 { confirmationMessage = nil } })
  }

  private func load() async {
    do { plan = try await model.loadPlan(planId) } catch {
      model.handle(error)
    }
  }

  private func approveOnly(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do {
      let updated = try await model.approve(plan: current)
      plan = updated
      if updated.blockedItemIds.isEmpty {
        confirmationMessage = "검토를 승인했습니다."
      } else {
        presentBlocked(updated, alsoExecute: false)
      }
    } catch {
      model.handle(error)
      await load()
    }
  }

  private func approveAndExecute(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do {
      let approved = try await model.approve(plan: current)
      plan = approved
      guard approved.blockedItemIds.isEmpty else {
        presentBlocked(approved, alsoExecute: true)
        return
      }
      try await runExecute(approved)
      dismiss()
    } catch {
      model.handle(error)
      await load()
    }
  }

  private func reject(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do {
      plan = try await model.reject(plan: current)
      dismiss()
    } catch {
      model.handle(error)
      await load()
    }
  }

  /// Explicit-force retry after the user has seen why the server blocked the items -- only the
  /// still-blocked items are re-sent with `forceReviewItems: true`, leaving anything already
  /// approved untouched.
  private func forceApprove(_ info: BlockedApproval) async {
    guard let current = plan else { return }
    isWorking = true
    defer { isWorking = false }
    do {
      let updated = try await model.approve(
        plan: current, itemIds: info.itemIds, forceReviewItems: true)
      plan = updated
      if info.alsoExecute {
        try await runExecute(updated)
        dismiss()
      } else {
        confirmationMessage = "강제 승인했습니다."
      }
    } catch {
      model.handle(error)
      await load()
    }
  }

  /// `ExecutionSummary` can report `retrying`/`errors` even on a 200 response (server-side
  /// retry loop still working through a transient failure). A silent success here previously
  /// read as "execution worked" when it might not have -- surface it via the app-wide error
  /// channel since this view is about to dismiss.
  private func runExecute(_ approved: ActionPlan) async throws {
    let summary = try await model.execute(plan: approved)
    guard summary.retrying > 0 || !summary.errors.isEmpty else { return }
    var message = "실행 요청을 보냈지만 일부 항목이 아직 실패 상태입니다"
    if summary.retrying > 0 { message += " (재시도 중 \(summary.retrying)건)" }
    message += "."
    let details = summary.errors.prefix(5).map { "• \($0.title): \($0.error)" }
    if !details.isEmpty { message += "\n" + details.joined(separator: "\n") }
    model.lastError = message
  }

  private func presentBlocked(_ updated: ActionPlan, alsoExecute: Bool) {
    let items = updated.items
      .filter { updated.blockedItemIds.contains($0.id) }
      .map { (title: $0.title, reason: $0.reviewReason ?? "검토 필요") }
    blockedApproval = BlockedApproval(
      itemIds: updated.blockedItemIds, items: items, alsoExecute: alsoExecute)
  }
}

private struct ActionItemRow: View {
  let item: ActionItem

  var body: some View {
    HStack(alignment: .top, spacing: 12) {
      Image(systemName: icon)
        .frame(width: 28, height: 28)
        .background(.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 7))
      VStack(alignment: .leading, spacing: 5) {
        Text(item.title).font(.headline)
        HStack(spacing: 8) {
          Text(item.destination.rawValue)
          Text(item.executor.rawValue)
          if let minutes = item.estimatedMinutes { Text("\(minutes)분") }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        if item.needsReview {
          Label(item.reviewReason ?? "검토 필요", systemImage: "exclamationmark.triangle")
            .font(.caption).foregroundStyle(.orange)
        }
      }
      Spacer()
      Text(item.state).font(.caption2).foregroundStyle(.secondary)
    }
    .contentShape(Rectangle())
    .padding(.vertical, 3)
  }

  private var icon: String {
    switch item.destination {
    case .todoist: "checkmark.square"
    case .github: "chevron.left.forwardslash.chevron.right"
    case .googleCalendar, .localICS: "calendar"
    case .none: "note.text"
    }
  }
}
