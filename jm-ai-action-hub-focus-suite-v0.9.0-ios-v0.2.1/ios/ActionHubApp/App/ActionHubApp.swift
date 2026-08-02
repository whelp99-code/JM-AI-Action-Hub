import SwiftUI

@main
struct ActionHubApp: App {
  @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @Environment(\.scenePhase) private var scenePhase
  @StateObject private var model: AppModel

  init() {
    let model = AppModel()
    _model = StateObject(wrappedValue: model)
    NotificationManager.shared.configure(model: model)
    BackgroundSyncManager.shared.register(model: model)
  }

  var body: some Scene {
    WindowGroup {
      RootView()
        .environmentObject(model)
        .environmentObject(model.biometricLock)
        .task { await model.start() }
        .onOpenURL { model.handleDeepLink($0) }
        .alert("Action Hub", isPresented: errorPresented) {
          Button("확인") { model.lastError = nil }
        } message: {
          Text(model.lastError ?? "알 수 없는 오류")
        }
    }
    .onChange(of: scenePhase) { _, phase in
      switch phase {
      case .active:
        Task {
          await model.biometricLock.unlock()
          model.handlePendingSystemRoute()
          await model.flushCaptures()
          await model.refreshAll()
        }
      case .background:
        model.biometricLock.lock()
        BackgroundSyncManager.shared.schedule()
      default: break
      }
    }
  }

  private var errorPresented: Binding<Bool> {
    Binding(
      get: { model.lastError != nil },
      set: { if !$0 { model.lastError = nil } }
    )
  }
}
