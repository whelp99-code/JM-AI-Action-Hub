import ActionHubCore
import SwiftUI

struct FocusSessionView: View {
  @EnvironmentObject private var model: AppModel
  @State private var selectedItem: FocusActionSummary?
  @State private var isWorking = false

  var body: some View {
    ScrollView {
      if let session = model.activeFocus {
        activeSession(session)
      } else {
        startPanel
      }
    }
    .padding()
    .refreshable { await model.refreshAllDetached() }
  }

  private func activeSession(_ session: FocusSession) -> some View {
    TimelineView(.periodic(from: .now, by: 1)) { context in
      let projection = projected(session, at: context.date)
      VStack(spacing: 20) {
        VStack(spacing: 8) {
          Text(session.action?.title ?? "집중 세션").font(.title2.bold()).multilineTextAlignment(
            .center)
          Text(timeString(projection.remaining))
            .font(.system(size: 54, weight: .bold, design: .rounded)).monospacedDigit()
          ProgressView(value: projection.progress)
            .tint(trafficColor(projection.traffic))
          Label(trafficLabel(projection.traffic), systemImage: "circle.fill")
            .foregroundStyle(trafficColor(projection.traffic))
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 24))

        if !session.microSteps.isEmpty {
          SectionCard(title: "마이크로 스텝", systemImage: "list.number") {
            ForEach(session.microSteps) { step in
              Button {
                Task { await toggle(step) }
              } label: {
                HStack {
                  Image(systemName: step.state == "completed" ? "checkmark.circle.fill" : "circle")
                  VStack(alignment: .leading) {
                    Text(step.title).strikethrough(step.state == "completed")
                    Text("\(step.executor.rawValue) · \(step.estimatedMinutes ?? 0)분")
                      .font(.caption).foregroundStyle(.secondary)
                  }
                  Spacer()
                }
              }
              .buttonStyle(.plain)
            }
          }
        }

        HStack {
          if session.state == .running {
            control("일시정지", icon: "pause.fill") { await update("pause") }
          } else {
            control("재개", icon: "play.fill") { await update("resume") }
          }
          control("10분 연장", icon: "plus.circle") { await update("extend", extensionMinutes: 10) }
        }
        HStack {
          control("종료", icon: "stop.fill", role: .destructive) { await update("abandon") }
          control("완료", icon: "checkmark", prominent: true) {
            await update("complete", markCompleted: true)
          }
        }
      }
    }
  }

  private var startPanel: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text("집중할 업무 선택").font(.title2.bold())
      Text("Q1·Q2 또는 내 Big3에서 하나를 선택합니다. 동시에 한 세션만 실행할 수 있습니다.")
        .font(.subheadline).foregroundStyle(.secondary)

      ForEach(focusCandidates) { item in
        VStack(alignment: .leading, spacing: 10) {
          HStack {
            VStack(alignment: .leading) {
              Text(item.title).font(.headline)
              Text(
                "\(item.assessment?.quadrant.rawValue.uppercased() ?? "-") · 예상 \(item.estimatedMinutes)분"
              )
              .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Menu {
              ForEach([10, 25, 50, 90], id: \.self) { minutes in
                Button("\(minutes)분") { Task { await start(item, minutes: minutes) } }
              }
            } label: {
              Label("시작", systemImage: "play.fill")
            }
            .buttonStyle(.borderedProminent)
          }
          Button("3~5개 마이크로 스텝 만들기") {
            Task {
              do { _ = try await model.decompose(item) } catch {
                model.lastError = error.localizedDescription
              }
            }
          }
          .font(.caption)
        }
        .padding()
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 16))
      }
      if focusCandidates.isEmpty {
        ContentUnavailableView(
          "집중 후보 없음", systemImage: "target",
          description: Text("먼저 업무를 분류하고 내 Big3를 선택하세요."))
      }
    }
  }

  private var focusCandidates: [FocusActionSummary] {
    let committed = model.big3?.human.compactMap(\.action) ?? []
    let matrix = (model.matrix?.q1 ?? []) + (model.matrix?.q2 ?? [])
    var seen = Set<String>()
    return (committed + matrix).filter { seen.insert($0.id).inserted }
  }

  private func start(_ item: FocusActionSummary, minutes: Int) async {
    guard !isWorking else { return }
    isWorking = true
    defer { isWorking = false }
    do { _ = try await model.startFocus(on: item, minutes: minutes) } catch {
      model.lastError = error.localizedDescription
    }
  }

  private func update(_ action: String, extensionMinutes: Int? = nil, markCompleted: Bool = false)
    async
  {
    guard !isWorking else { return }
    isWorking = true
    defer { isWorking = false }
    do {
      _ = try await model.updateFocus(
        action: action, extensionMinutes: extensionMinutes,
        completionNote: action == "complete" ? "iOS Focus에서 완료" : nil,
        markActionCompleted: markCompleted)
    } catch { model.lastError = error.localizedDescription }
  }

  private func toggle(_ step: MicroStep) async {
    do {
      _ = try await model.updateMicroStep(
        step, state: step.state == "completed" ? "pending" : "completed")
    } catch { model.lastError = error.localizedDescription }
  }

  @ViewBuilder
  private func control(
    _ title: String, icon: String, role: ButtonRole? = nil, prominent: Bool = false,
    action: @escaping () async -> Void
  ) -> some View {
    if prominent {
      Button(role: role) {
        Task { await action() }
      } label: {
        Label(title, systemImage: icon).frame(maxWidth: .infinity)
      }
      .buttonStyle(.borderedProminent)
      .disabled(isWorking)
    } else {
      Button(role: role) {
        Task { await action() }
      } label: {
        Label(title, systemImage: icon).frame(maxWidth: .infinity)
      }
      .buttonStyle(.bordered)
      .disabled(isWorking)
    }
  }

  private func projected(_ session: FocusSession, at date: Date) -> (
    remaining: Int, progress: Double, traffic: FocusTrafficState
  ) {
    let extra =
      session.state == .running ? max(0, Int(date.timeIntervalSince(session.updatedAt))) : 0
    let elapsed = session.elapsedSeconds + extra
    let total = max(1, session.totalPlannedMinutes * 60)
    let progress = Double(elapsed) / Double(total)
    let traffic: FocusTrafficState = elapsed > total ? .red : (progress >= 0.8 ? .yellow : .green)
    return (max(0, total - elapsed), progress, traffic)
  }

  private func timeString(_ seconds: Int) -> String {
    String(format: "%02d:%02d", seconds / 60, seconds % 60)
  }

  private func trafficLabel(_ state: FocusTrafficState) -> String {
    switch state {
    case .green: "계획 범위"
    case .yellow: "마감 임박"
    case .red: "예정시간 초과"
    }
  }

  private func trafficColor(_ state: FocusTrafficState) -> Color {
    switch state {
    case .green: .green
    case .yellow: .orange
    case .red: .red
    }
  }
}
