import ActionHubCore
import SwiftUI
import WidgetKit

#if canImport(ActivityKit)
  import ActivityKit
#endif

struct ActionHubWidgetEntry: TimelineEntry {
  let date: Date
  let snapshot: WidgetSnapshot
}

struct ActionHubTimelineProvider: TimelineProvider {
  func placeholder(in context: Context) -> ActionHubWidgetEntry {
    .init(
      date: Date(),
      snapshot: .init(
        reviewCount: 3,
        waitingCount: 2,
        aiRunningCount: 1,
        overloadMinutes: 90,
        topTitles: ["HCI 제안서", "고객 미팅", "PR 검토"],
        untriagedCount: 4,
        humanBig3Titles: ["HCI 제안서", "고객 미팅", "PR 검토"],
        aiBig3Titles: ["회귀 테스트 보강", "운영 문서 정리"],
        activeFocusTitle: "HCI 제안서",
        activeFocusRemainingSeconds: 1_480,
        activeFocusTrafficState: "green"))
  }

  func getSnapshot(in context: Context, completion: @escaping (ActionHubWidgetEntry) -> Void) {
    completion(.init(date: Date(), snapshot: readSnapshot()))
  }

  func getTimeline(
    in context: Context, completion: @escaping (Timeline<ActionHubWidgetEntry>) -> Void
  ) {
    let entry = ActionHubWidgetEntry(date: Date(), snapshot: readSnapshot())
    completion(Timeline(entries: [entry], policy: .after(Date(timeIntervalSinceNow: 15 * 60))))
  }

  private func readSnapshot() -> WidgetSnapshot {
    let group =
      Bundle.main.object(forInfoDictionaryKey: "ActionHubAppGroup") as? String
      ?? "group.com.jmactionhub.shared"
    guard
      let container = FileManager.default.containerURL(
        forSecurityApplicationGroupIdentifier: group),
      let data = try? Data(contentsOf: container.appendingPathComponent("widget/dashboard.json")),
      let snapshot = try? ActionHubJSON.decoder().decode(WidgetSnapshot.self, from: data)
    else {
      return .init()
    }
    return snapshot
  }
}

struct ActionHubWidgetView: View {
  @Environment(\.widgetFamily) private var family
  let entry: ActionHubWidgetEntry

  var body: some View {
    switch family {
    case .systemSmall: small
    default: medium
    }
  }

  private var small: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Image(systemName: entry.snapshot.activeFocusTitle == nil ? "target" : "timer")
        Text(entry.snapshot.activeFocusTitle == nil ? "Action Focus" : "집중 중")
          .font(.headline)
      }
      Spacer()
      if let title = entry.snapshot.activeFocusTitle {
        Text(title).font(.subheadline.bold()).lineLimit(2).privacySensitive()
        Text(remaining(entry.snapshot.activeFocusRemainingSeconds ?? 0))
          .font(.title3.bold().monospacedDigit())
      } else {
        HStack {
          WidgetMetric(value: entry.snapshot.untriagedCount, label: "분류")
          WidgetMetric(value: entry.snapshot.reviewCount, label: "검토")
        }
      }
      Link(destination: URL(string: "jmactionhub://focus")!) {
        Label("Focus 열기", systemImage: "arrow.up.right.circle.fill").font(.caption.bold())
      }
    }
    .containerBackground(.fill.tertiary, for: .widget)
  }

  private var medium: some View {
    HStack(spacing: 16) {
      VStack(alignment: .leading, spacing: 8) {
        Label("내 Big3", systemImage: "person.crop.circle.badge.checkmark").font(.headline)
        let titles =
          entry.snapshot.humanBig3Titles.isEmpty
          ? entry.snapshot.topTitles : entry.snapshot.humanBig3Titles
        ForEach(Array(titles.prefix(3).enumerated()), id: \.offset) { index, title in
          Text("\(index + 1). \(title)")
            .font(.caption)
            .lineLimit(1)
            .privacySensitive()
        }
        if titles.isEmpty {
          Text("Focus에서 오늘의 Big3를 선택하세요")
            .font(.caption).foregroundStyle(.secondary)
        }
      }
      Divider()
      VStack(alignment: .leading, spacing: 8) {
        if let title = entry.snapshot.activeFocusTitle {
          Label("집중 중", systemImage: "timer").font(.caption.bold())
          Text(title).font(.caption).lineLimit(2).privacySensitive()
          Text(remaining(entry.snapshot.activeFocusRemainingSeconds ?? 0))
            .font(.headline.monospacedDigit())
        } else {
          Label("분류 \(entry.snapshot.untriagedCount)", systemImage: "rectangle.stack")
          Label("검토 \(entry.snapshot.reviewCount)", systemImage: "checklist")
          Label("AI \(entry.snapshot.aiRunningCount)", systemImage: "sparkles")
          if entry.snapshot.overloadMinutes > 0 {
            Label("초과 \(entry.snapshot.overloadMinutes)분", systemImage: "exclamationmark.triangle")
              .foregroundStyle(.red)
          }
        }
      }
      .font(.caption)
    }
    .containerBackground(.fill.tertiary, for: .widget)
  }

  private func remaining(_ seconds: Int) -> String {
    String(format: "%02d:%02d", max(0, seconds) / 60, max(0, seconds) % 60)
  }
}

private struct WidgetMetric: View {
  let value: Int
  let label: String
  var body: some View {
    VStack(alignment: .leading, spacing: 1) {
      Text("\(value)").font(.title2.bold()).contentTransition(.numericText())
      Text(label).font(.caption2).foregroundStyle(.secondary)
    }
  }
}

struct ActionHubWidget: Widget {
  let kind = "ActionHubWidget"
  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: ActionHubTimelineProvider()) { entry in
      ActionHubWidgetView(entry: entry)
    }
    .configurationDisplayName("JM-AI Action Focus")
    .description("분류 대기, Dual Big3, 활성 Focus 세션과 AI 실행 상태를 확인합니다.")
    .supportedFamilies([.systemSmall, .systemMedium])
  }
}

#if canImport(ActivityKit)
  struct FocusLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
      ActivityConfiguration(for: FocusActivityAttributes.self) { context in
        FocusLockScreenView(context: context)
          .activityBackgroundTint(.black.opacity(0.82))
          .activitySystemActionForegroundColor(.white)
          .widgetURL(URL(string: "jmactionhub://focus"))
      } dynamicIsland: { context in
        DynamicIsland {
          DynamicIslandExpandedRegion(.leading) {
            Image(systemName: "timer").foregroundStyle(trafficColor(context.state.trafficState))
          }
          DynamicIslandExpandedRegion(.center) {
            Text(context.attributes.title).font(.headline).lineLimit(1).privacySensitive()
          }
          DynamicIslandExpandedRegion(.trailing) {
            FocusRemainingText(state: context.state).font(.headline.monospacedDigit())
          }
          DynamicIslandExpandedRegion(.bottom) {
            ProgressView(value: min(max(context.state.progress, 0), 1))
              .tint(trafficColor(context.state.trafficState))
          }
        } compactLeading: {
          Image(systemName: "timer").foregroundStyle(trafficColor(context.state.trafficState))
        } compactTrailing: {
          FocusRemainingText(state: context.state).font(.caption2.monospacedDigit())
        } minimal: {
          Image(systemName: "target").foregroundStyle(trafficColor(context.state.trafficState))
        }
        .widgetURL(URL(string: "jmactionhub://focus"))
        .keylineTint(trafficColor(context.state.trafficState))
      }
    }
  }

  private struct FocusLockScreenView: View {
    let context: ActivityViewContext<FocusActivityAttributes>

    var body: some View {
      HStack(spacing: 14) {
        Image(systemName: "timer")
          .font(.title2)
          .foregroundStyle(trafficColor(context.state.trafficState))
        VStack(alignment: .leading, spacing: 4) {
          Text(context.attributes.title).font(.headline).lineLimit(1).privacySensitive()
          ProgressView(value: min(max(context.state.progress, 0), 1))
            .tint(trafficColor(context.state.trafficState))
        }
        Spacer()
        FocusRemainingText(state: context.state)
          .font(.title3.bold().monospacedDigit())
      }
      .padding()
    }
  }

  private struct FocusRemainingText: View {
    let state: FocusActivityAttributes.ContentState

    var body: some View {
      if state.state == "running", state.remainingSeconds > 0 {
        let end = state.updatedAt.addingTimeInterval(TimeInterval(state.remainingSeconds))
        Text(timerInterval: state.updatedAt...end, countsDown: true)
      } else {
        Text(
          String(
            format: "%02d:%02d", max(0, state.remainingSeconds) / 60,
            max(0, state.remainingSeconds) % 60))
      }
    }
  }

  private func trafficColor(_ value: String) -> Color {
    switch value {
    case "red": .red
    case "yellow": .orange
    default: .green
    }
  }
#endif

@main
struct ActionHubWidgetBundle: WidgetBundle {
  @WidgetBundleBuilder
  var body: some Widget {
    ActionHubWidget()
    #if canImport(ActivityKit)
      FocusLiveActivityWidget()
    #endif
  }
}
