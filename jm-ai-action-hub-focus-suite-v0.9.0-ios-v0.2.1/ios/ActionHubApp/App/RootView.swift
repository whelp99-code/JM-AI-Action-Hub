import SwiftUI

struct RootView: View {
  @EnvironmentObject private var model: AppModel
  @EnvironmentObject private var lock: BiometricLock

  var body: some View {
    Group {
      switch model.connectionState {
      case .loading:
        ProgressView("Action Hub 연결 확인 중…")
      case .disconnected:
        PairingView()
      case .failed(let message):
        ContentUnavailableView {
          Label("연결 확인 실패", systemImage: "exclamationmark.triangle")
        } description: {
          Text(message)
        } actions: {
          Button("다시 확인") { Task { await model.start() } }
          Button("새로 연결") { model.resetConnection() }
        }
      case .connected:
        if lock.isUnlocked {
          MainTabView()
        } else {
          LockView()
        }
      }
    }
    .animation(.default, value: lock.isUnlocked)
  }
}

private struct LockView: View {
  @EnvironmentObject private var lock: BiometricLock

  var body: some View {
    VStack(spacing: 24) {
      Image(systemName: "lock.shield.fill")
        .font(.system(size: 54))
        .foregroundStyle(.tint)
      Text("Action Hub 잠김")
        .font(.title2.bold())
      Text("업무 내용과 AI 실행 상태를 보려면 기기 인증이 필요합니다.")
        .multilineTextAlignment(.center)
        .foregroundStyle(.secondary)
      Button("Face ID로 열기") { Task { await lock.unlock() } }
        .buttonStyle(.borderedProminent)
    }
    .padding(32)
    .task { await lock.unlock() }
  }
}

private struct MainTabView: View {
  @EnvironmentObject private var model: AppModel

  var body: some View {
    TabView(selection: $model.selectedTab) {
      NavigationStack { TodayView() }
        .tabItem { Label("오늘", systemImage: "sun.max") }
        .tag(AppTab.today)
      NavigationStack { FocusHomeView() }
        .tabItem { Label("Focus", systemImage: "target") }
        .badge(model.triage?.total ?? 0)
        .tag(AppTab.focus)
      NavigationStack(path: $model.reviewNavigationPath) {
        ReviewView()
          .navigationDestination(for: String.self) { planId in
            PlanDetailView(planId: planId)
          }
      }
      .tabItem { Label("검토", systemImage: "checklist") }
      .badge(model.dashboard?.reviewCount ?? 0)
      .tag(AppTab.review)
      NavigationStack { ActivityView() }
        .tabItem { Label("활동", systemImage: "waveform.path.ecg") }
        .badge((model.dashboard?.aiRunningCount ?? 0) + (model.dashboard?.failedCount ?? 0))
        .tag(AppTab.activity)
      NavigationStack { SettingsView() }
        .tabItem { Label("설정", systemImage: "gearshape") }
        .tag(AppTab.settings)
    }
    .overlay(alignment: .bottom) {
      Button {
        model.isCapturePresented = true
      } label: {
        Image(systemName: "plus")
          .font(.title2.bold())
          .frame(width: 54, height: 54)
          .background(.tint, in: Circle())
          .foregroundStyle(.white)
          .shadow(radius: 8, y: 4)
      }
      .accessibilityLabel("빠른 입력")
      .offset(y: -8)
    }
    .sheet(isPresented: $model.isCapturePresented) {
      CaptureView()
        .presentationDetents([.medium, .large])
    }
  }
}
