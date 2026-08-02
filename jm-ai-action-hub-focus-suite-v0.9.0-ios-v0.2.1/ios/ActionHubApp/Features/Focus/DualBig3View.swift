import ActionHubCore
import SwiftUI

struct DualBig3View: View {
  @EnvironmentObject private var model: AppModel
  @State private var humanIDs: [String] = []
  @State private var aiIDs: [String] = []
  @State private var availableMinutes = 480
  @State private var isSaving = false

  private var candidates: [FocusActionSummary] {
    guard let matrix = model.matrix else { return [] }
    return matrix.q1 + matrix.q2 + matrix.q3 + matrix.q4
  }

  var body: some View {
    List {
      Section {
        Stepper(
          "오늘 가용시간 \(minutes(availableMinutes))", value: $availableMinutes, in: 30...900, step: 30)
        if humanMinutes > availableMinutes {
          Label(
            "내 Big3가 \(humanMinutes - availableMinutes)분 초과합니다.",
            systemImage: "exclamationmark.triangle"
          )
          .foregroundStyle(.red)
        }
      } header: {
        Text("Capacity")
      }

      commitmentSection(title: "내 Big3", owner: .human, ids: humanIDs)
      commitmentSection(title: "AI Big3", owner: .ai, ids: aiIDs)

      Section("후보 업무") {
        if candidates.isEmpty { Text("먼저 업무를 분류하세요.").foregroundStyle(.secondary) }
        ForEach(candidates) { item in
          HStack {
            VStack(alignment: .leading, spacing: 4) {
              Text(item.title)
              Text(
                "\(item.assessment?.quadrant.rawValue.uppercased() ?? "-") · \(item.estimatedMinutes)분 · \(item.executor.rawValue)"
              )
              .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Menu {
              Button("내 Big3") { assign(item.id, to: .human) }
              Button("AI Big3") { assign(item.id, to: .ai) }
              Button("선택 해제", role: .destructive) { remove(item.id) }
            } label: {
              Image(systemName: ownerIcon(item.id))
            }
          }
        }
      }
    }
    .safeAreaInset(edge: .bottom) {
      Button {
        Task { await save() }
      } label: {
        if isSaving {
          ProgressView().frame(maxWidth: .infinity)
        } else {
          Text("Dual Big3 확정").frame(maxWidth: .infinity)
        }
      }
      .buttonStyle(.borderedProminent)
      .disabled(isSaving)
      .padding()
      .background(.bar)
    }
    .task { loadCurrent() }
    .onChange(of: model.big3?.date) { _, _ in loadCurrent() }
  }

  private enum Owner { case human, ai }

  @ViewBuilder
  private func commitmentSection(title: String, owner: Owner, ids: [String]) -> some View {
    Section {
      if ids.isEmpty { Text("최대 3건을 선택하세요.").foregroundStyle(.secondary) }
      ForEach(Array(ids.enumerated()), id: \.element) { index, id in
        HStack {
          Text("\(index + 1)").font(.headline.monospacedDigit()).foregroundStyle(.secondary)
          Text(candidates.first(where: { $0.id == id })?.title ?? id).lineLimit(2)
          Spacer()
          Button(role: .destructive) {
            remove(id)
          } label: {
            Image(systemName: "xmark.circle")
          }
        }
      }
    } header: {
      HStack {
        Text(title)
        Spacer()
        Text("\(ids.count)/3")
      }
    }
  }

  private var humanMinutes: Int {
    humanIDs.compactMap { id in candidates.first(where: { $0.id == id })?.estimatedMinutes }.reduce(
      0, +)
  }

  private func assign(_ id: String, to owner: Owner) {
    remove(id)
    switch owner {
    case .human: if humanIDs.count < 3 { humanIDs.append(id) }
    case .ai: if aiIDs.count < 3 { aiIDs.append(id) }
    }
  }

  private func remove(_ id: String) {
    humanIDs.removeAll { $0 == id }
    aiIDs.removeAll { $0 == id }
  }

  private func ownerIcon(_ id: String) -> String {
    if humanIDs.contains(id) { return "person.crop.circle.fill" }
    if aiIDs.contains(id) { return "sparkles" }
    return "plus.circle"
  }

  private func loadCurrent() {
    guard let big3 = model.big3 else { return }
    humanIDs = big3.human.map(\.actionItemId)
    aiIDs = big3.ai.map(\.actionItemId)
    availableMinutes = big3.availableMinutes
  }

  private func save() async {
    isSaving = true
    defer { isSaving = false }
    do {
      try await model.configureBig3(
        humanItemIds: humanIDs, aiItemIds: aiIDs, availableMinutes: availableMinutes)
    } catch { model.lastError = error.localizedDescription }
  }

  private func minutes(_ value: Int) -> String {
    let h = value / 60
    let m = value % 60
    return h == 0 ? "\(m)분" : (m == 0 ? "\(h)시간" : "\(h)시간 \(m)분")
  }
}
