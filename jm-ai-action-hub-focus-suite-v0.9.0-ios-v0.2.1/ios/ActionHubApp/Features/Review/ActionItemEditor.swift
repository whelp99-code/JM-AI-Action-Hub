import ActionHubCore
import SwiftUI

struct ActionItemEditor: View {
  @EnvironmentObject private var model: AppModel
  @Environment(\.dismiss) private var dismiss
  let plan: ActionPlan
  let item: ActionItem
  let onUpdated: (ActionPlan) -> Void

  @State private var title: String
  @State private var description: String
  @State private var destination: Destination
  @State private var executor: ExecutorType
  @State private var estimatedMinutes: String
  @State private var preferredWorker: String
  @State private var repository: String
  @State private var needsReview: Bool
  @State private var isSaving = false

  init(plan: ActionPlan, item: ActionItem, onUpdated: @escaping (ActionPlan) -> Void) {
    self.plan = plan
    self.item = item
    self.onUpdated = onUpdated
    _title = State(initialValue: item.title)
    _description = State(initialValue: item.description)
    _destination = State(initialValue: item.destination)
    _executor = State(initialValue: item.executor)
    _estimatedMinutes = State(initialValue: item.estimatedMinutes.map(String.init) ?? "")
    _preferredWorker = State(initialValue: item.preferredWorker ?? "")
    _repository = State(initialValue: item.repository ?? "")
    _needsReview = State(initialValue: item.needsReview)
  }

  var body: some View {
    NavigationStack {
      Form {
        Section("내용") {
          TextField("제목", text: $title, axis: .vertical)
          TextField("설명", text: $description, axis: .vertical)
        }
        Section("라우팅") {
          Picker("목적지", selection: $destination) {
            ForEach(Destination.allCases, id: \.self) { Text($0.rawValue).tag($0) }
          }
          Picker("실행자", selection: $executor) {
            ForEach(ExecutorType.allCases, id: \.self) { Text($0.rawValue).tag($0) }
          }
          TextField("예상시간(분)", text: $estimatedMinutes).keyboardType(.numberPad)
          TextField("AI Worker", text: $preferredWorker).textInputAutocapitalization(.never)
          TextField("GitHub owner/repo", text: $repository).textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        }
        Section {
          Toggle("계속 검토 필요", isOn: $needsReview)
          LabeledContent("현재 Revision", value: String(item.revision))
        }
      }
      .navigationTitle("항목 수정")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
        ToolbarItem(placement: .confirmationAction) {
          Button("저장") { Task { await save() } }
            .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
        }
      }
    }
  }

  private func save() async {
    isSaving = true
    defer { isSaving = false }
    var patch = ActionItemPatch(expectedRevision: item.revision)
    patch.title = title
    patch.description = description
    patch.destination = destination
    patch.executor = executor
    patch.estimatedMinutes = Int(estimatedMinutes)
    patch.preferredWorker = preferredWorker.isEmpty ? nil : preferredWorker
    patch.repository = repository.isEmpty ? nil : repository
    patch.needsReview = needsReview
    do {
      let updated = try await model.updateItem(planId: plan.id, itemId: item.id, patch: patch)
      onUpdated(updated)
      dismiss()
    } catch {
      model.lastError = error.localizedDescription
    }
  }
}
