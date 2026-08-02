import ActionHubCore
import SwiftUI

struct PlanDetailView: View {
  @EnvironmentObject private var model: AppModel
  let planId: String
  @State private var plan: ActionPlan?
  @State private var isWorking = false
  @State private var selectedItem: ActionItem?
  @State private var showRejectConfirmation = false

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
            .disabled(isWorking)

            Button {
              Task { await approveAndExecute(plan) }
            } label: {
              Label("승인 후 등록·실행", systemImage: "paperplane.fill")
            }
            .disabled(isWorking)

            Button(role: .destructive) {
              showRejectConfirmation = true
            } label: {
              Label("전체 제외", systemImage: "xmark.circle")
            }
            .disabled(isWorking)
          }
        }
        .refreshable { await load() }
        .confirmationDialog("이 계획의 모든 항목을 제외합니까?", isPresented: $showRejectConfirmation) {
          Button("전체 제외", role: .destructive) { Task { await reject(plan) } }
        }
        .sheet(item: $selectedItem) { item in
          ActionItemEditor(plan: plan, item: item) { updated in
            self.plan = updated
          }
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

  private func load() async {
    do { plan = try await model.loadPlan(planId) } catch {
      model.lastError = error.localizedDescription
    }
  }

  private func approveOnly(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do { plan = try await model.approve(plan: current) } catch {
      model.lastError = error.localizedDescription
      await load()
    }
  }

  private func approveAndExecute(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do {
      let approved = try await model.approve(plan: current)
      _ = try await model.execute(plan: approved)
      plan = try await model.loadPlan(planId)
    } catch {
      model.lastError = error.localizedDescription
      await load()
    }
  }

  private func reject(_ current: ActionPlan) async {
    isWorking = true
    defer { isWorking = false }
    do { plan = try await model.reject(plan: current) } catch {
      model.lastError = error.localizedDescription
      await load()
    }
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
