import ActionHubCore
import SwiftUI

struct TriageView: View {
  @EnvironmentObject private var model: AppModel
  @State private var dragOffset: CGSize = .zero
  @State private var isSubmitting = false

  private var item: FocusActionSummary? { model.triage?.items.first }

  var body: some View {
    ScrollView {
      VStack(spacing: 18) {
        header
        if let item {
          card(item)
            .offset(dragOffset)
            .rotationEffect(.degrees(Double(dragOffset.width / 28)))
            .gesture(dragGesture(item))
          actionButtons(item)
        } else {
          ContentUnavailableView(
            "분류 완료", systemImage: "checkmark.seal",
            description: Text("새로 수집된 업무가 생기면 여기에서 빠르게 판단합니다.")
          )
          .padding(.top, 60)
        }
      }
      .padding()
    }
    .refreshable { await model.refreshAllDetached() }
  }

  private var header: some View {
    HStack {
      VStack(alignment: .leading, spacing: 4) {
        Text("Swipe Triage").font(.title2.bold())
        Text("AI 제안을 확인하고 실행·계획·위임·보류를 결정합니다.")
          .font(.subheadline).foregroundStyle(.secondary)
      }
      Spacer()
      Text("\(model.triage?.total ?? 0)")
        .font(.title.bold().monospacedDigit())
        .accessibilityLabel("분류 대기 \(model.triage?.total ?? 0)건")
    }
  }

  private func card(_ item: FocusActionSummary) -> some View {
    VStack(alignment: .leading, spacing: 16) {
      if let assessment = item.assessment {
        HStack {
          Label("AI 권고 · \(assessment.quadrant.title)", systemImage: icon(assessment.quadrant))
            .font(.headline)
          Spacer()
          Text("\(Int(assessment.confidence * 100))%")
            .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
      }
      Text(item.title).font(.title2.bold())
      if !item.description.isEmpty {
        Text(item.description).font(.subheadline).foregroundStyle(.secondary).lineLimit(4)
      }
      HStack(spacing: 14) {
        Label("\(item.estimatedMinutes)분", systemImage: "clock")
        Label(item.executor.rawValue, systemImage: "person.crop.circle.badge.checkmark")
        if let deadline = item.deadlineAt {
          Label(deadline.formatted(date: .abbreviated, time: .shortened), systemImage: "flag")
        }
      }
      .font(.caption).foregroundStyle(.secondary)

      if let reasons = item.assessment?.reasonsJson, !reasons.isEmpty {
        Divider()
        VStack(alignment: .leading, spacing: 6) {
          Text("판단 근거").font(.caption.bold()).foregroundStyle(.secondary)
          ForEach(reasons.prefix(4), id: \.self) { reason in
            Label(reason, systemImage: "circle.fill")
              .font(.caption)
              .symbolRenderingMode(.hierarchical)
          }
        }
      }
    }
    .frame(maxWidth: .infinity, minHeight: 330, alignment: .topLeading)
    .padding(22)
    .background(.background.secondary, in: RoundedRectangle(cornerRadius: 24))
    .overlay(RoundedRectangle(cornerRadius: 24).stroke(.quaternary))
    .shadow(color: .black.opacity(0.08), radius: 12, y: 6)
    .accessibilityElement(children: .combine)
    .accessibilityAction(named: "지금 실행") { classify(item, .q1) }
    .accessibilityAction(named: "계획") { classify(item, .q2) }
    .accessibilityAction(named: "위임") { classify(item, .q3) }
    .accessibilityAction(named: "보류") { classify(item, .q4) }
  }

  private func actionButtons(_ item: FocusActionSummary) -> some View {
    HStack(spacing: 10) {
      quadrantButton(item, .q3, icon: "person.2")
      quadrantButton(item, .q4, icon: "archivebox")
      quadrantButton(item, .q1, icon: "bolt.fill")
      quadrantButton(item, .q2, icon: "calendar.badge.clock")
    }
    .disabled(isSubmitting)
  }

  private func quadrantButton(_ item: FocusActionSummary, _ quadrant: Quadrant, icon: String)
    -> some View
  {
    Button {
      classify(item, quadrant)
    } label: {
      VStack(spacing: 5) {
        Image(systemName: icon).font(.title3)
        Text(quadrant.title).font(.caption.bold())
      }
      .frame(maxWidth: .infinity)
      .padding(.vertical, 10)
    }
    .buttonStyle(.bordered)
    .accessibilityHint(quadrant.subtitle)
  }

  private func dragGesture(_ item: FocusActionSummary) -> some Gesture {
    DragGesture()
      .onChanged { dragOffset = $0.translation }
      .onEnded { value in
        let x = value.translation.width
        let y = value.translation.height
        guard max(abs(x), abs(y)) > 90 else {
          withAnimation(.spring) { dragOffset = .zero }
          return
        }
        let quadrant: Quadrant
        if abs(x) > abs(y) { quadrant = x > 0 ? .q2 : .q3 } else { quadrant = y < 0 ? .q1 : .q4 }
        classify(item, quadrant)
      }
  }

  private func classify(_ item: FocusActionSummary, _ quadrant: Quadrant) {
    guard !isSubmitting else { return }
    isSubmitting = true
    withAnimation(.easeIn(duration: 0.15)) {
      switch quadrant {
      case .q1: dragOffset = CGSize(width: 0, height: -700)
      case .q2: dragOffset = CGSize(width: 700, height: 0)
      case .q3: dragOffset = CGSize(width: -700, height: 0)
      case .q4: dragOffset = CGSize(width: 0, height: 700)
      }
    }
    Task {
      do { try await model.classify(item, as: quadrant) } catch {
        model.lastError = error.localizedDescription
      }
      await MainActor.run {
        dragOffset = .zero
        isSubmitting = false
      }
    }
  }

  private func icon(_ quadrant: Quadrant) -> String {
    switch quadrant {
    case .q1: "bolt.fill"
    case .q2: "calendar.badge.clock"
    case .q3: "person.2"
    case .q4: "archivebox"
    }
  }
}
