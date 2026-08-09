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

      if let big3 = model.big3 {
        Section {
          Text("중요도·긴급도와 남은 일정, 처리 강도를 함께 계산했습니다. 제안을 담은 뒤 아래에서 확정하세요.")
            .font(.subheadline)
            .foregroundStyle(.secondary)
          Text("내 일정 여유 " + minutes(big3.humanRemainingMinutes) + " · AI 처리 여유 " + minutes(big3.aiRemainingMinutes))
            .font(.caption)
            .foregroundStyle(.secondary)
        } header: {
          Text("오늘의 Big3 제안")
        }
        recommendationSection(
          title: "내 Big3 추천", recommendations: big3.humanRecommendations, owner: .human)
        recommendationSection(
          title: "AI Big3 추천", recommendations: big3.aiRecommendations, owner: .ai)
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
    .refreshable { await model.refreshAllDetached() }
    .task { loadCurrent() }
    .onChange(of: model.big3?.date) { _, _ in loadCurrent() }
  }

  private enum Owner: Equatable { case human, ai }

  @ViewBuilder
  private func recommendationSection(
    title: String, recommendations: [Big3Recommendation], owner: Owner
  ) -> some View {
    Section {
      if recommendations.isEmpty {
        Text("현재 남은 일정에 맞는 새 제안이 없습니다.")
          .foregroundStyle(.secondary)
      } else {
        ForEach(recommendations) { recommendation in
          VStack(alignment: .leading, spacing: 7) {
            Text(recommendation.action.title)
              .font(.headline)
              .lineLimit(2)
              .privacySensitive()
            HStack(spacing: 8) {
              Label(minutes(recommendation.action.estimatedMinutes), systemImage: "clock")
              Label(intensityTitle(recommendation.processingIntensity), systemImage: "flame")
              if let assessment = recommendation.action.assessment {
                Text(
                  "중요 " + String(Int(assessment.importanceScore))
                    + " · 긴급 " + String(Int(assessment.urgencyScore)))
              }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Text(recommendation.reasons.prefix(2).joined(separator: " · "))
              .font(.caption)
              .foregroundStyle(
                recommendation.scheduleFit == "fits" ? Color.secondary : Color.red)
            Button {
              assign(recommendation.action.id, to: owner)
            } label: {
              Label(owner == .human ? "내 Big3에 담기" : "AI Big3에 담기", systemImage: "plus.circle")
            }
            .buttonStyle(.bordered)
            .disabled(owner == .human ? humanIDs.count >= 3 : aiIDs.count >= 3)
          }
          .padding(.vertical, 4)
        }
      }
    } header: {
      HStack {
        Text(title)
        Spacer()
        if !recommendations.isEmpty {
          Button("모두 담기") { accept(recommendations, as: owner) }
            .font(.caption)
        }
      }
    }
  }

  @ViewBuilder
  private func commitmentSection(title: String, owner: Owner, ids: [String]) -> some View {
    Section {
      if ids.isEmpty { Text("최대 3건을 선택하세요.").foregroundStyle(.secondary) }
      ForEach(Array(ids.enumerated()), id: \.element) { index, id in
        HStack {
          Text("\(index + 1)").font(.headline.monospacedDigit()).foregroundStyle(.secondary)
          Text(candidates.first(where: { $0.id == id })?.title ?? "제목을 불러올 수 없는 업무").lineLimit(2)
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

  private func accept(_ recommendations: [Big3Recommendation], as owner: Owner) {
    for recommendation in recommendations {
      assign(recommendation.action.id, to: owner)
    }
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

  private func intensityTitle(_ value: String) -> String {
    switch value {
    case "light": "가벼움"
    case "heavy": "집중 필요"
    default: "보통"
    }
  }
}
