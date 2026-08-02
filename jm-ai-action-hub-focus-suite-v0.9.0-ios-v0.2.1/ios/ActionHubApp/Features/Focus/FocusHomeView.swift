import ActionHubCore
import SwiftUI

enum FocusSection: String, CaseIterable, Identifiable {
  case triage = "분류"
  case matrix = "매트릭스"
  case big3 = "Big3"
  case focus = "집중"
  case close = "마감"
  var id: String { rawValue }
}

struct FocusHomeView: View {
  @EnvironmentObject private var model: AppModel
  @State private var section: FocusSection = .triage

  var body: some View {
    VStack(spacing: 0) {
      Picker("Focus 단계", selection: $section) {
        ForEach(FocusSection.allCases) { Text($0.rawValue).tag($0) }
      }
      .pickerStyle(.segmented)
      .padding(.horizontal)
      .padding(.vertical, 8)

      Group {
        switch section {
        case .triage: TriageView()
        case .matrix: MatrixFocusView()
        case .big3: DualBig3View()
        case .focus: FocusSessionView()
        case .close: DayCloseView()
        }
      }
    }
    .navigationTitle("Focus")
    .task { applyRequestedSection() }
    .onChange(of: model.focusRequestedSection) { _, _ in applyRequestedSection() }
    .toolbar {
      ToolbarItem(placement: .topBarTrailing) {
        Button {
          Task { await model.refreshAll() }
        } label: {
          Image(systemName: "arrow.clockwise")
        }
        .accessibilityLabel("Focus 새로고침")
      }
    }
  }

  private func applyRequestedSection() {
    guard let requested = model.focusRequestedSection else { return }
    switch requested {
    case "matrix": section = .matrix
    case "big3": section = .big3
    case "focus": section = .focus
    case "day-close": section = .close
    default: section = .triage
    }
    model.focusRequestedSection = nil
  }
}
