import ActionHubCore
import AppIntents
import Foundation

struct CaptureTextIntent: AppIntent {
  static let title: LocalizedStringResource = "Action Hub에 추가"
  static let description = IntentDescription("말하거나 입력한 내용을 Action Hub 검토 큐에 안전하게 저장합니다.")
  static let openAppWhenRun = false

  @Parameter(title: "내용", requestValueDialog: "무엇을 Action Hub에 추가할까요?")
  var text: String

  func perform() async throws -> some IntentResult & ProvidesDialog {
    let container = try appGroupContainer()
    let queue = OfflineCaptureQueue(
      fileURL: container.appendingPathComponent("captures/pending.json"))
    _ = try await queue.enqueue(text: text, source: "ios-app-intent")
    return .result(dialog: "Action Hub 오프라인 검토 큐에 저장했습니다. 앱이 열리면 서버로 전송합니다.")
  }
}

struct OpenActionHubIntent: AppIntent {
  static let title: LocalizedStringResource = "Action Hub 열기"
  static let description = IntentDescription("오늘의 계획과 검토 대기를 엽니다.")
  static let openAppWhenRun = true

  func perform() async throws -> some IntentResult {
    try writeRoute("today")
    return .result()
  }
}

struct OpenFocusIntent: AppIntent {
  static let title: LocalizedStringResource = "Focus 열기"
  static let description = IntentDescription("Dual Big3와 현재 집중 세션을 엽니다.")
  static let openAppWhenRun = true

  func perform() async throws -> some IntentResult {
    try writeRoute("focus")
    return .result()
  }
}

struct OpenTriageIntent: AppIntent {
  static let title: LocalizedStringResource = "분류 대기 열기"
  static let description = IntentDescription("실행·계획·위임·보류를 결정할 업무를 엽니다.")
  static let openAppWhenRun = true

  func perform() async throws -> some IntentResult {
    try writeRoute("triage")
    return .result()
  }
}

struct OpenMatrixIntent: AppIntent {
  static let title: LocalizedStringResource = "우선순위 매트릭스 열기"
  static let description = IntentDescription("아이젠하워 매트릭스와 사분면별 업무를 엽니다.")
  static let openAppWhenRun = true

  func perform() async throws -> some IntentResult {
    try writeRoute("matrix")
    return .result()
  }
}

struct ActionHubShortcuts: AppShortcutsProvider {
  static var appShortcuts: [AppShortcut] {
    AppShortcut(
      intent: CaptureTextIntent(),
      phrases: [
        "\(.applicationName)에 추가",
        "\(.applicationName)에 할 일 추가",
        "\(.applicationName)로 수집",
      ],
      shortTitle: "Action Hub에 추가",
      systemImageName: "plus.circle.fill"
    )
    AppShortcut(
      intent: OpenFocusIntent(),
      phrases: ["\(.applicationName) Focus 열기", "\(.applicationName) 집중 보여줘"],
      shortTitle: "Focus 열기",
      systemImageName: "target"
    )
    AppShortcut(
      intent: OpenTriageIntent(),
      phrases: ["\(.applicationName) 분류 대기 열기", "\(.applicationName) 업무 분류"],
      shortTitle: "분류 대기",
      systemImageName: "rectangle.stack"
    )
    AppShortcut(
      intent: OpenMatrixIntent(),
      phrases: ["\(.applicationName) 매트릭스 열기", "\(.applicationName) 우선순위 보여줘"],
      shortTitle: "매트릭스",
      systemImageName: "square.grid.2x2"
    )
    AppShortcut(
      intent: OpenActionHubIntent(),
      phrases: ["\(.applicationName) 열기", "\(.applicationName) 오늘 보여줘"],
      shortTitle: "Action Hub 열기",
      systemImageName: "point.3.connected.trianglepath.dotted"
    )
  }
}

private func appGroupContainer() throws -> URL {
  let group =
    Bundle.main.object(forInfoDictionaryKey: "ActionHubAppGroup") as? String
    ?? "group.com.jmactionhub.shared"
  guard
    let container = FileManager.default.containerURL(
      forSecurityApplicationGroupIdentifier: group)
  else { throw AppGroupError.unavailable(group) }
  return container
}

private func writeRoute(_ route: String) throws {
  let destination = try appGroupContainer().appendingPathComponent("navigation/pending-route.txt")
  try FileManager.default.createDirectory(
    at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
  try Data(route.utf8).write(
    to: destination,
    options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
  )
}
