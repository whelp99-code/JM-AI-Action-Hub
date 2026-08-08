import ActionHubCore
import SwiftUI

struct MatrixFocusView: View {
  @EnvironmentObject private var model: AppModel
  private let columns = [GridItem(.flexible()), GridItem(.flexible())]

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        Text("아이젠하워 매트릭스")
          .font(.title2.bold())
        Text("사분면은 저장소가 아니라 다음 행동을 결정하는 View입니다.")
          .font(.subheadline).foregroundStyle(.secondary)

        LazyVGrid(columns: columns, spacing: 12) {
          ForEach(Quadrant.allCases) { quadrant in
            NavigationLink {
              QuadrantDetailView(quadrant: quadrant)
            } label: {
              matrixCell(quadrant)
            }
            .buttonStyle(.plain)
          }
        }
        if let untriaged = model.matrix?.untriagedCount, untriaged > 0 {
          Label("아직 분류하지 않은 업무 \(untriaged)건", systemImage: "tray.full")
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.orange.opacity(0.12), in: RoundedRectangle(cornerRadius: 16))
        }
      }
      .padding()
    }
    .refreshable { await model.refreshAllDetached() }
  }

  private func matrixCell(_ quadrant: Quadrant) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Image(systemName: icon(quadrant)).font(.title2)
        Spacer()
        Text("\(model.matrix?.counts[quadrant.rawValue] ?? 0)")
          .font(.title.bold().monospacedDigit())
      }
      Text("\(quadrant.rawValue.uppercased()) · \(quadrant.title)").font(.headline)
      Text(quadrant.subtitle).font(.caption).foregroundStyle(.secondary)
      ForEach((model.matrix?.items(for: quadrant) ?? []).prefix(2)) { item in
        Text("• \(item.title)").font(.caption).lineLimit(1).privacySensitive()
      }
    }
    .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
    .padding()
    .background(background(quadrant), in: RoundedRectangle(cornerRadius: 18))
  }

  private func icon(_ q: Quadrant) -> String {
    switch q {
    case .q1: "bolt.fill"
    case .q2: "target"
    case .q3: "person.2"
    case .q4: "archivebox"
    }
  }

  private func background(_ q: Quadrant) -> Color {
    switch q {
    case .q1: .red.opacity(0.13)
    case .q2: .blue.opacity(0.13)
    case .q3: .orange.opacity(0.13)
    case .q4: .gray.opacity(0.13)
    }
  }
}

private struct QuadrantDetailView: View {
  @EnvironmentObject private var model: AppModel
  let quadrant: Quadrant

  var body: some View {
    List(model.matrix?.items(for: quadrant) ?? []) { item in
      VStack(alignment: .leading, spacing: 5) {
        Text(item.title).font(.headline)
        HStack {
          Text("\(item.estimatedMinutes)분")
          Text(item.executor.rawValue)
          if let deadline = item.deadlineAt {
            Text(deadline.formatted(date: .abbreviated, time: .omitted))
          }
        }
        .font(.caption).foregroundStyle(.secondary)
      }
    }
    .navigationTitle("\(quadrant.rawValue.uppercased()) · \(quadrant.title)")
  }
}
