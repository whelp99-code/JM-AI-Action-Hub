import ActionHubCore
import SwiftUI

struct TodayView: View {
  @EnvironmentObject private var model: AppModel

  var body: some View {
    ScrollView {
      if let dashboard = model.dashboard {
        LazyVStack(alignment: .leading, spacing: 18) {
          summaryGrid(dashboard)
          focusStatus(dashboard)
          topItems(dashboard)
          risks(dashboard)
          aiCandidates(dashboard)
          waiting(dashboard)
        }
        .padding()
      } else if model.isRefreshing {
        ProgressView("오늘 계획 불러오는 중…")
          .frame(maxWidth: .infinity)
          .padding(.top, 80)
      } else {
        ContentUnavailableView(
          "오늘 정보 없음", systemImage: "sun.max", description: Text("당겨서 새로고침하세요."))
      }
    }
    .refreshable { await model.refreshAllDetached() }
    .navigationTitle("오늘")
    .toolbar {
      ToolbarItem(placement: .topBarTrailing) {
        Button {
          Task { await model.refreshAll() }
        } label: {
          Image(systemName: "arrow.clockwise")
        }
      }
    }
  }

  @ViewBuilder
  private func summaryGrid(_ dashboard: MobileDashboard) -> some View {
    let decision = dashboard.decision
    Grid(horizontalSpacing: 12, verticalSpacing: 12) {
      GridRow {
        MetricCard(
          title: "가용시간", value: minutes(decision.availableMinutes - decision.bufferMinutes),
          systemImage: "clock")
        MetricCard(
          title: "예상 업무", value: minutes(decision.plannedMinutes),
          systemImage: "list.bullet.clipboard")
      }
      GridRow {
        MetricCard(
          title: "초과", value: minutes(decision.overloadMinutes),
          systemImage: "exclamationmark.triangle", emphasized: decision.overloadMinutes > 0)
        MetricCard(title: "검토 대기", value: "\(dashboard.reviewCount)건", systemImage: "checklist")
      }
    }
    .accessibilityElement(children: .contain)
  }

  @ViewBuilder
  private func focusStatus(_ dashboard: MobileDashboard) -> some View {
    if let focus = dashboard.focusSummary {
      SectionCard(title: "Action Focus", systemImage: "target") {
        if let active = focus.activeFocus {
          HStack {
            VStack(alignment: .leading, spacing: 4) {
              Text(active.action?.title ?? "집중 세션").font(.headline).privacySensitive()
              Text("남은 시간 \(clock(active.remainingSeconds)) · \(traffic(active.trafficState))")
                .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("열기") {
              model.selectedTab = .focus
              model.focusRequestedSection = "focus"
            }
            .buttonStyle(.bordered)
          }
        } else {
          HStack {
            Label("분류 대기 \(focus.untriagedCount)건", systemImage: "rectangle.stack")
            Spacer()
            Button("분류") {
              model.selectedTab = .focus
              model.focusRequestedSection = "triage"
            }
            .buttonStyle(.bordered)
          }
        }

        if !focus.humanBig3.isEmpty || !focus.aiBig3.isEmpty {
          Divider()
          VStack(alignment: .leading, spacing: 8) {
            if !focus.humanBig3.isEmpty {
              Text("내 Big3").font(.caption.bold()).foregroundStyle(.secondary)
              ForEach(focus.humanBig3.prefix(3)) { commitment in
                Text("\(commitment.rank). \(commitment.action?.title ?? "제목을 불러올 수 없는 업무")")
                  .font(.subheadline).lineLimit(1).privacySensitive()
              }
            }
            if !focus.aiBig3.isEmpty {
              Text("AI Big3").font(.caption.bold()).foregroundStyle(.secondary)
              ForEach(focus.aiBig3.prefix(3)) { commitment in
                Text("\(commitment.rank). \(commitment.action?.title ?? "제목을 불러올 수 없는 업무")")
                  .font(.subheadline).lineLimit(1).privacySensitive()
              }
            }
          }
        }
      }
    }
  }

  @ViewBuilder
  private func topItems(_ dashboard: MobileDashboard) -> some View {
    SectionCard(title: "오늘의 Top 업무", systemImage: "target") {
      if dashboard.decision.topItems.isEmpty {
        Text("우선순위 업무가 없습니다.").foregroundStyle(.secondary)
      } else {
        ForEach(Array(dashboard.decision.topItems.enumerated()), id: \.element.id) { index, item in
          HStack(alignment: .top) {
            Text("\(index + 1)").font(.headline.monospacedDigit()).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 4) {
              Text(item.title).font(.headline)
              Text("\(minutes(item.estimatedMinutes)) · \(item.executor.rawValue)")
                .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
          }
          if item.id != dashboard.decision.topItems.last?.id { Divider() }
        }
      }
    }
  }

  @ViewBuilder
  private func risks(_ dashboard: MobileDashboard) -> some View {
    if !dashboard.decision.risks.isEmpty || dashboard.failedCount > 0 {
      SectionCard(title: "위험", systemImage: "exclamationmark.shield") {
        ForEach(dashboard.decision.risks, id: \.self) {
          Label($0, systemImage: "exclamationmark.circle")
        }
        if dashboard.failedCount > 0 {
          Label("외부 등록 실패 \(dashboard.failedCount)건", systemImage: "xmark.octagon")
        }
      }
    }
  }

  @ViewBuilder
  private func aiCandidates(_ dashboard: MobileDashboard) -> some View {
    if !dashboard.decision.aiDelegationCandidates.isEmpty {
      SectionCard(title: "AI 위임 후보", systemImage: "sparkles") {
        ForEach(dashboard.decision.aiDelegationCandidates) { item in
          HStack {
            VStack(alignment: .leading) {
              Text(item.title)
              if let worker = item.preferredWorker {
                Text(worker).font(.caption).foregroundStyle(.secondary)
              }
            }
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(.tertiary)
          }
        }
      }
    }
  }

  @ViewBuilder
  private func waiting(_ dashboard: MobileDashboard) -> some View {
    if !dashboard.decision.waitingFollowups.isEmpty {
      SectionCard(title: "응답 대기", systemImage: "hourglass") {
        ForEach(dashboard.decision.waitingFollowups) { followup in
          VStack(alignment: .leading, spacing: 4) {
            Text(followup.actionTitle ?? followup.waitingFor)
            Text(
              "\(followup.waitingFor) · \(followup.followUpAt.formatted(date: .abbreviated, time: .shortened))"
            )
            .font(.caption).foregroundStyle(.secondary)
          }
        }
      }
    }
  }

  private func clock(_ seconds: Int) -> String {
    String(format: "%02d:%02d", max(0, seconds) / 60, max(0, seconds) % 60)
  }

  private func traffic(_ state: FocusTrafficState) -> String {
    switch state {
    case .green: "계획 범위"
    case .yellow: "마감 임박"
    case .red: "시간 초과"
    }
  }

  private func minutes(_ value: Int) -> String {
    if value <= 0 { return "0분" }
    let hours = value / 60
    let remainder = value % 60
    if hours == 0 { return "\(remainder)분" }
    return remainder == 0 ? "\(hours)시간" : "\(hours)시간 \(remainder)분"
  }
}

private struct MetricCard: View {
  let title: String
  let value: String
  let systemImage: String
  var emphasized = false

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Label(title, systemImage: systemImage).font(.caption).foregroundStyle(.secondary)
      Text(value).font(.title3.bold()).foregroundStyle(emphasized ? .red : .primary)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding()
    .background(.background.secondary, in: RoundedRectangle(cornerRadius: 16))
  }
}

struct SectionCard<Content: View>: View {
  let title: String
  let systemImage: String
  let content: Content

  init(title: String, systemImage: String, @ViewBuilder content: () -> Content) {
    self.title = title
    self.systemImage = systemImage
    self.content = content()
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Label(title, systemImage: systemImage).font(.headline)
      content
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding()
    .background(.background.secondary, in: RoundedRectangle(cornerRadius: 16))
  }
}
