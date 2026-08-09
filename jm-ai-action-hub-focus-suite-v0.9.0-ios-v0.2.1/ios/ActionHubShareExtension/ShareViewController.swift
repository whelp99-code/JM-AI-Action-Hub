import ActionHubCore
import UIKit
import UniformTypeIdentifiers

final class ShareViewController: UIViewController {
  private let statusLabel = UILabel()
  private let spinner = UIActivityIndicatorView(style: .large)

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .systemBackground
    statusLabel.text = "Action Hub에 수집 중…"
    statusLabel.textAlignment = .center
    statusLabel.numberOfLines = 0
    statusLabel.translatesAutoresizingMaskIntoConstraints = false
    spinner.startAnimating()
    spinner.translatesAutoresizingMaskIntoConstraints = false
    view.addSubview(statusLabel)
    view.addSubview(spinner)
    NSLayoutConstraint.activate([
      spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor),
      spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -24),
      statusLabel.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 18),
      statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
      statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
    ])
    Task { await captureAndComplete() }
  }

  @MainActor
  private func captureAndComplete() async {
    do {
      let fragments = try await collectFragments()
      let text =
        fragments
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
        .joined(separator: "\n\n")
      guard !text.isEmpty else { throw ShareError.noSupportedContent }
      let group =
        Bundle.main.object(forInfoDictionaryKey: "ActionHubAppGroup") as? String
        ?? "group.com.jmactionhub.shared"
      guard
        let container = FileManager.default.containerURL(
          forSecurityApplicationGroupIdentifier: group)
      else {
        throw ShareError.appGroupUnavailable
      }
      let queue = OfflineCaptureQueue(
        fileURL: container.appendingPathComponent("captures/pending.json"))
      _ = try await queue.enqueue(
        text: text,
        source: "ios-share-extension",
        metadata: ["share_item_count": .number(Double(fragments.count))]
      )
      // "저장했습니다" alone read as "it is in the app now", so a share that parsed to
      // nothing looked like a failure. Name the second step the user still has to take.
      statusLabel.text = "Action Hub 수집함에 저장했습니다.\n앱을 열면 분석해서 검토 탭에 표시합니다."
      statusLabel.numberOfLines = 0
      spinner.stopAnimating()
      try? await Task.sleep(for: .milliseconds(900))
      extensionContext?.completeRequest(returningItems: nil)
    } catch {
      statusLabel.text = error.localizedDescription
      spinner.stopAnimating()
      try? await Task.sleep(for: .seconds(1))
      extensionContext?.cancelRequest(withError: error)
    }
  }

  private func collectFragments() async throws -> [String] {
    var results: [String] = []
    let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
    for item in items {
      if let attributed = item.attributedContentText?.string, !attributed.isEmpty {
        results.append(attributed)
      }
      for provider in item.attachments ?? [] {
        if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier),
          let text = try await provider.loadString(for: UTType.plainText.identifier)
        {
          results.append(text)
          continue
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier),
          let value = try await provider.loadURL(for: UTType.url.identifier)
        {
          results.append(value.absoluteString)
          continue
        }
      }
    }
    return results
  }
}

extension NSItemProvider {
  // Both loaders stay on the main actor: NSItemProvider is not Sendable, and the caller
  // (a UIViewController) is main-actor-isolated, so crossing isolation would be unsafe.
  @MainActor
  fileprivate func loadString(for typeIdentifier: String) async throws -> String? {
    try await withCheckedThrowingContinuation { continuation in
      loadItem(forTypeIdentifier: typeIdentifier, options: nil) { value, error in
        if let error {
          continuation.resume(throwing: error)
          return
        }
        if let string = value as? String {
          continuation.resume(returning: string)
        } else if let data = value as? Data {
          continuation.resume(returning: String(data: data, encoding: .utf8))
        } else {
          continuation.resume(returning: nil)
        }
      }
    }
  }

  @MainActor
  fileprivate func loadURL(for typeIdentifier: String) async throws -> URL? {
    try await withCheckedThrowingContinuation { continuation in
      loadItem(forTypeIdentifier: typeIdentifier, options: nil) { value, error in
        if let error {
          continuation.resume(throwing: error)
          return
        }
        if let url = value as? URL {
          continuation.resume(returning: url)
        } else if let string = value as? String {
          continuation.resume(returning: URL(string: string))
        } else {
          continuation.resume(returning: nil)
        }
      }
    }
  }
}

private enum ShareError: LocalizedError {
  case noSupportedContent
  case appGroupUnavailable
  var errorDescription: String? {
    switch self {
    case .noSupportedContent: "공유된 텍스트나 링크를 읽을 수 없습니다."
    case .appGroupUnavailable: "Action Hub 공유 저장소를 열 수 없습니다."
    }
  }
}
