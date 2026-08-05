import ActionHubCore
import SwiftUI

struct ActivityView: View {
  @EnvironmentObject private var model: AppModel
  @Environment(\.openURL) private var openURL
  @State private var filter: ActivityFilter = .all

  var body: some View {
    Group {
      if filtered.isEmpty {
        ContentUnavailableView(
          "활동 없음", systemImage: "waveform.path.ecg",
          description: Text("AI 실행, Follow-up, 등록 실패와 완료 이력이 표시됩니다."))
      } else {
        List(filtered) { item in
          Button {
            if let value = item.externalUrl, let url = URL(string: value) { openURL(url) }
          } label: {
            HStack(alignment: .top, spacing: 12) {
              Image(systemName: icon(for: item.category))
                .frame(width: 30, height: 30)
                .background(
                  color(for: item.category).opacity(0.12), in: RoundedRectangle(cornerRadius: 8)
                )
                .foregroundStyle(color(for: item.category))
              VStack(alignment: .leading, spacing: 4) {
                Text(item.title).font(.headline).foregroundStyle(.primary)
                if let subtitle = item.subtitle {
                  Text(subtitle).font(.subheadline).foregroundStyle(.secondary)
                }
                Text(item.occurredAt.formatted(date: .abbreviated, time: .shortened))
                  .font(.caption2).foregroundStyle(.tertiary)
              }
              Spacer()
              if item.externalUrl != nil {
                Image(systemName: "arrow.up.right.square").foregroundStyle(.tertiary)
              }
            }
          }
          .buttonStyle(.plain)
        }
        .refreshable { await model.refreshAllDetached() }
      }
    }
    .navigationTitle("활동")
    .toolbar {
      ToolbarItem(placement: .topBarTrailing) {
        Menu {
          Picker("필터", selection: $filter) {
            ForEach(ActivityFilter.allCases) { Text($0.title).tag($0) }
          }
        } label: {
          Image(systemName: "line.3.horizontal.decrease.circle")
        }
      }
    }
  }

  private var filtered: [ActivityItem] {
    switch filter {
    case .all: model.activity
    case .ai: model.activity.filter { $0.category == "worker" }
    case .waiting: model.activity.filter { $0.category == "followup" }
    case .failure: model.activity.filter { $0.category == "failure" }
    }
  }

  private func icon(for category: String) -> String {
    switch category {
    case "worker": "sparkles"
    case "followup": "hourglass"
    case "failure": "exclamationmark.octagon"
    default: "clock.arrow.circlepath"
    }
  }

  private func color(for category: String) -> Color {
    switch category {
    case "worker": .purple
    case "followup": .orange
    case "failure": .red
    default: .blue
    }
  }
}

private enum ActivityFilter: String, CaseIterable, Identifiable {
  case all, ai, waiting, failure
  var id: String { rawValue }
  var title: String {
    switch self {
    case .all: "전체"
    case .ai: "AI 실행"
    case .waiting: "응답 대기"
    case .failure: "실패"
    }
  }
}
