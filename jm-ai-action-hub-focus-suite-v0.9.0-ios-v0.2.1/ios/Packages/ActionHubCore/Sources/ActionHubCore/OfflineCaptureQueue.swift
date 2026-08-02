import Foundation

/// A process-safe capture queue shared by the app, Share Extension, widgets, and App Intents.
///
/// Each capture is stored in its own atomic JSON file. This avoids the lost-update race that
/// occurs when two iOS processes read, modify, and rewrite one shared array file concurrently.
public actor OfflineCaptureQueue {
  private let legacyFileURL: URL
  private let queueDirectoryURL: URL
  private let corruptDirectoryURL: URL
  private var didAttemptLegacyMigration = false

  public init(fileURL: URL) {
    legacyFileURL = fileURL
    let baseName = fileURL.deletingPathExtension().lastPathComponent
    queueDirectoryURL = fileURL.deletingLastPathComponent().appendingPathComponent(baseName)
    corruptDirectoryURL = fileURL.deletingLastPathComponent().appendingPathComponent("corrupt")
  }

  @discardableResult
  public func enqueue(
    text: String,
    source: String = "ios",
    timezone: String = TimeZone.current.identifier,
    metadata: [String: JSONValue] = [:]
  ) async throws -> CaptureInput {
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { throw ActionHubAPIError.encoding("수집할 텍스트가 비어 있습니다") }
    let capture = CaptureInput(
      text: trimmed, source: source, timezone: timezone, metadata: metadata)
    try prepareStorage()
    try write(capture)
    return capture
  }

  public func append(_ capture: CaptureInput) async throws {
    try prepareStorage()
    let destination = try fileURL(for: capture.clientCaptureId)
    guard !FileManager.default.fileExists(atPath: destination.path) else { return }
    try write(capture)
  }

  public func pending(limit: Int = 50) async throws -> [CaptureInput] {
    try prepareStorage()
    guard limit > 0 else { return [] }
    return Array(try readAll().prefix(limit))
  }

  public func count() async throws -> Int {
    try prepareStorage()
    return try captureFileURLs().count
  }

  public func remove(clientCaptureIds: Set<String>) async throws {
    try prepareStorage()
    for captureId in clientCaptureIds {
      let url = try fileURL(for: captureId)
      do {
        try FileManager.default.removeItem(at: url)
      } catch let error as CocoaError where error.code == .fileNoSuchFile {
        // Another process already acknowledged and removed this capture.
      }
    }
  }

  public func apply(receipts: [CaptureReceipt]) async throws {
    let successful = Set(
      receipts.filter { ["processed", "duplicate"].contains($0.status) }.map(\.clientCaptureId)
    )
    try await remove(clientCaptureIds: successful)
  }

  public func flush(using session: MobileSession, batchSize: Int = 25) async throws
    -> CaptureBatchResponse?
  {
    let batch = try await pending(limit: batchSize)
    guard !batch.isEmpty else { return nil }
    let response = try await session.uploadCaptures(batch)
    try await apply(receipts: response.receipts)
    return response
  }

  private func prepareStorage() throws {
    try FileManager.default.createDirectory(
      at: queueDirectoryURL, withIntermediateDirectories: true)
    guard !didAttemptLegacyMigration else { return }
    didAttemptLegacyMigration = true
    try migrateLegacyArrayIfPresent()
  }

  private func migrateLegacyArrayIfPresent() throws {
    guard FileManager.default.fileExists(atPath: legacyFileURL.path) else { return }
    do {
      let data = try Data(contentsOf: legacyFileURL)
      let captures = try ActionHubJSON.decoder().decode([CaptureInput].self, from: data)
      for capture in captures {
        let destination = try fileURL(for: capture.clientCaptureId)
        if !FileManager.default.fileExists(atPath: destination.path) {
          try write(capture)
        }
      }
      try? FileManager.default.removeItem(at: legacyFileURL)
    } catch {
      // Preserve a malformed legacy queue for diagnostics instead of blocking all new captures.
      try quarantine(legacyFileURL, suffix: "legacy")
    }
  }

  private func readAll() throws -> [CaptureInput] {
    var captures: [CaptureInput] = []
    for url in try captureFileURLs() {
      do {
        let data = try Data(contentsOf: url)
        captures.append(try ActionHubJSON.decoder().decode(CaptureInput.self, from: data))
      } catch {
        try? quarantine(url, suffix: "capture")
      }
    }
    return captures.sorted {
      let left = $0.referenceTime ?? .distantPast
      let right = $1.referenceTime ?? .distantPast
      return left == right ? $0.clientCaptureId < $1.clientCaptureId : left < right
    }
  }

  private func captureFileURLs() throws -> [URL] {
    try FileManager.default.contentsOfDirectory(
      at: queueDirectoryURL,
      includingPropertiesForKeys: nil,
      options: [.skipsHiddenFiles]
    )
    .filter { $0.pathExtension == "json" }
  }

  private func write(_ capture: CaptureInput) throws {
    let destination = try fileURL(for: capture.clientCaptureId)
    do {
      let data = try ActionHubJSON.encoder().encode(capture)
      try data.write(
        to: destination,
        options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
      )
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐를 저장할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func fileURL(for captureId: String) throws -> URL {
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_."))
    guard captureId.count >= 8, captureId.count <= 80,
      captureId.unicodeScalars.allSatisfy(allowed.contains),
      !captureId.contains("..")
    else {
      throw ActionHubAPIError.encoding("안전하지 않은 capture ID입니다")
    }
    return queueDirectoryURL.appendingPathComponent(captureId).appendingPathExtension("json")
  }

  private func quarantine(_ source: URL, suffix: String) throws {
    try FileManager.default.createDirectory(
      at: corruptDirectoryURL, withIntermediateDirectories: true)
    let destination = corruptDirectoryURL.appendingPathComponent(
      "\(suffix)-\(UUID().uuidString.lowercased()).json")
    do {
      try FileManager.default.moveItem(at: source, to: destination)
    } catch let error as CocoaError where error.code == .fileNoSuchFile {
      // Another process already migrated or quarantined it.
    }
  }
}
