import Foundation

#if os(Linux)
  import Glibc
#else
  import Darwin
#endif

public struct OfflineCaptureQueueRecord: Codable, Sendable, Equatable {
  public let version: Int
  public let capture: CaptureInput
  public var attemptCount: Int
  public var lastError: String?
  public var lastAttemptAt: Date?

  public init(
    version: Int = 1,
    capture: CaptureInput,
    attemptCount: Int = 0,
    lastError: String? = nil,
    lastAttemptAt: Date? = nil
  ) {
    self.version = version
    self.capture = capture
    self.attemptCount = attemptCount
    self.lastError = lastError
    self.lastAttemptAt = lastAttemptAt
  }
}

public struct OfflineCaptureDeadLetter: Codable, Sendable, Equatable, Identifiable {
  public var id: String { record.capture.clientCaptureId }
  public let record: OfflineCaptureQueueRecord
  public let deadLetteredAt: Date

  public init(record: OfflineCaptureQueueRecord, deadLetteredAt: Date = Date()) {
    self.record = record
    self.deadLetteredAt = deadLetteredAt
  }
}

/// A process-safe capture queue shared by the app, Share Extension, widgets, and App Intents.
///
/// The App Group has several independent processes, so every read-modify-write transition holds
/// the same advisory filesystem lock and persists a single capture through an atomic replacement.
public actor OfflineCaptureQueue {
  private enum PendingRecordDecodingError: Error {
    case unsupported
  }

  private let legacyFileURL: URL
  private let baseDirectoryURL: URL
  private let pendingDirectoryURL: URL
  private let deadLetterDirectoryURL: URL
  private let corruptDirectoryURL: URL
  private let lockFileURL: URL
  private let maxAttempts: Int

  public init(fileURL: URL, maxAttempts: Int = 5) {
    legacyFileURL = fileURL
    baseDirectoryURL = fileURL.deletingLastPathComponent()
    pendingDirectoryURL = baseDirectoryURL.appendingPathComponent("pending", isDirectory: true)
    deadLetterDirectoryURL = baseDirectoryURL.appendingPathComponent("dead-letter", isDirectory: true)
    corruptDirectoryURL = baseDirectoryURL.appendingPathComponent("corrupt", isDirectory: true)
    lockFileURL = baseDirectoryURL.appendingPathComponent(".offline-capture.lock")
    self.maxAttempts = max(1, maxAttempts)
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
    let capture = CaptureInput(text: trimmed, source: source, timezone: timezone, metadata: metadata)
    try withLock {
      try prepareStorageLocked()
      let destination = try pendingFileURL(for: capture.clientCaptureId)
      guard !FileManager.default.fileExists(atPath: destination.path) else { return }
      try writeRecord(OfflineCaptureQueueRecord(capture: capture), to: destination)
    }
    return capture
  }

  public func append(_ capture: CaptureInput) async throws {
    try withLock {
      try prepareStorageLocked()
      let destination = try pendingFileURL(for: capture.clientCaptureId)
      guard !FileManager.default.fileExists(atPath: destination.path) else { return }
      try writeRecord(OfflineCaptureQueueRecord(capture: capture), to: destination)
    }
  }

  public func pending(limit: Int = 50) async throws -> [CaptureInput] {
    guard limit > 0 else { return [] }
    return try withLock {
      try prepareStorageLocked()
      return Array(try pendingRecordsLocked().map(\.capture).prefix(limit))
    }
  }

  public func count() async throws -> Int {
    try withLock {
      try prepareStorageLocked()
      return try pendingRecordsLocked().count
    }
  }

  public func deadLetterCount() async throws -> Int {
    try withLock {
      try prepareStorageLocked()
      return try deadLetterFileURLs().count
    }
  }

  public func deadLetters(limit: Int = 100) async throws -> [OfflineCaptureDeadLetter] {
    guard limit > 0 else { return [] }
    return try withLock {
      try prepareStorageLocked()
      return Array(try deadLettersLocked().prefix(limit))
    }
  }

  public func restoreDeadLetter(clientCaptureId: String) async throws {
    try withLock {
      try prepareStorageLocked()
      let source = try deadLetterFileURL(for: clientCaptureId)
      guard FileManager.default.fileExists(atPath: source.path) else { return }
      let destination = try pendingFileURL(for: clientCaptureId)
      guard !FileManager.default.fileExists(atPath: destination.path) else {
        throw ActionHubAPIError.encoding("capture already pending")
      }
      let deadLetter = try decodeDeadLetter(at: source)
      let restored = OfflineCaptureQueueRecord(capture: deadLetter.record.capture)
      try transition(from: source, to: destination) {
        try writeRecord(restored, to: $0)
      }
    }
  }

  public func purgeDeadLetter(clientCaptureId: String) async throws {
    try withLock {
      try prepareStorageLocked()
      try removeItem(at: try deadLetterFileURL(for: clientCaptureId), missingIsSuccess: true)
    }
  }

  public func remove(clientCaptureIds: Set<String>) async throws {
    try withLock {
      try prepareStorageLocked()
      for captureId in clientCaptureIds {
        try removeItem(at: try pendingFileURL(for: captureId), missingIsSuccess: true)
      }
    }
  }

  public func apply(receipts: [CaptureReceipt]) async throws {
    try withLock {
      try prepareStorageLocked()
      let successful = Set(
        receipts.filter { ["processed", "duplicate"].contains($0.status) }.map(\.clientCaptureId)
      )
      for captureId in successful {
        try removeItem(at: try pendingFileURL(for: captureId), missingIsSuccess: true)
      }
      for receipt in receipts where receipt.status == "failed" && !successful.contains(receipt.clientCaptureId) {
        try applyFailedReceiptLocked(receipt)
      }
    }
  }

  /// Holds the production lock for the process-contention executable test.
  public func holdLock(milliseconds: Int, onAcquired: @Sendable () -> Void) async throws {
    try withLock {
      try prepareStorageLocked()
      onAcquired()
      Thread.sleep(forTimeInterval: Double(max(0, milliseconds)) / 1000)
    }
  }

  public func flush(using session: MobileSession, batchSize: Int = 25) async throws
    -> CaptureBatchResponse?
  {
    let batch = try await pending(limit: batchSize)
    guard !batch.isEmpty else { return nil }
    let response = try await session.uploadCaptures(batch)
    // A transport exception never reaches this point, so it cannot increment retry metadata.
    try await apply(receipts: response.receipts)
    return response
  }

  private func applyFailedReceiptLocked(_ receipt: CaptureReceipt) throws {
    let source = try pendingFileURL(for: receipt.clientCaptureId)
    guard FileManager.default.fileExists(atPath: source.path) else { return }
    var record = try decodePendingRecord(at: source)
    let nextAttempt = min(maxAttempts, record.attemptCount + 1)
    record.attemptCount = nextAttempt
    record.lastError = receipt.error.map { String($0.prefix(1024)) }
    record.lastAttemptAt = Date()
    if nextAttempt == maxAttempts {
      let destination = try deadLetterFileURL(for: receipt.clientCaptureId)
      try transition(from: source, to: destination) {
        try writeDeadLetter(OfflineCaptureDeadLetter(record: record), to: $0)
      }
    } else {
      try writeRecord(record, to: source)
    }
  }

  private func prepareStorageLocked() throws {
    try createDirectory(baseDirectoryURL)
    try createDirectory(pendingDirectoryURL)
    try createDirectory(deadLetterDirectoryURL)
    try createDirectory(corruptDirectoryURL)
    try migrateLegacyArrayIfPresentLocked()
  }

  private func migrateLegacyArrayIfPresentLocked() throws {
    guard FileManager.default.fileExists(atPath: legacyFileURL.path) else { return }
    do {
      let captures = try ActionHubJSON.decoder().decode([CaptureInput].self, from: Data(contentsOf: legacyFileURL))
      for capture in captures {
        let destination = try pendingFileURL(for: capture.clientCaptureId)
        if FileManager.default.fileExists(atPath: destination.path) {
          let existing = try decodePendingRecord(at: destination)
          guard existing.capture == capture else {
            try quarantine(legacyFileURL, suffix: "legacy-conflict")
            throw ActionHubAPIError.encoding("legacy capture conflicts with pending capture")
          }
        } else {
          try writeRecord(OfflineCaptureQueueRecord(capture: capture), to: destination)
        }
      }
      try removeItem(at: legacyFileURL, missingIsSuccess: false)
    } catch let error as ActionHubAPIError {
      throw error
    } catch {
      try quarantine(legacyFileURL, suffix: "legacy")
    }
  }

  private func pendingRecordsLocked() throws -> [OfflineCaptureQueueRecord] {
    var records: [OfflineCaptureQueueRecord] = []
    for url in try pendingFileURLs() {
      do {
        records.append(try decodePendingRecord(at: url))
      } catch is PendingRecordDecodingError {
        try quarantine(url, suffix: "pending")
      } catch let error as ActionHubAPIError {
        throw error
      }
    }
    return records.sorted(by: recordOrder)
  }

  private func deadLettersLocked() throws -> [OfflineCaptureDeadLetter] {
    var letters: [OfflineCaptureDeadLetter] = []
    for url in try deadLetterFileURLs() {
      do {
        letters.append(try decodeDeadLetter(at: url))
      } catch {
        try quarantine(url, suffix: "dead-letter")
      }
    }
    return letters.sorted { left, right in
      let leftTime = left.record.capture.referenceTime ?? .distantPast
      let rightTime = right.record.capture.referenceTime ?? .distantPast
      return leftTime == rightTime ? left.id < right.id : leftTime < rightTime
    }
  }

  private func recordOrder(_ left: OfflineCaptureQueueRecord, _ right: OfflineCaptureQueueRecord) -> Bool {
    let leftTime = left.capture.referenceTime ?? .distantPast
    let rightTime = right.capture.referenceTime ?? .distantPast
    return leftTime == rightTime
      ? left.capture.clientCaptureId < right.capture.clientCaptureId
      : leftTime < rightTime
  }

  private func decodePendingRecord(at url: URL) throws -> OfflineCaptureQueueRecord {
    let data: Data
    do {
      data = try Data(contentsOf: url)
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐를 읽을 수 없습니다: \(error.localizedDescription)")
    }
    if let record = try? ActionHubJSON.decoder().decode(OfflineCaptureQueueRecord.self, from: data) {
      guard record.version == 1, record.attemptCount >= 0, record.attemptCount <= maxAttempts else {
        throw PendingRecordDecodingError.unsupported
      }
      return record
    }
    if let capture = try? ActionHubJSON.decoder().decode(CaptureInput.self, from: data) {
      let record = OfflineCaptureQueueRecord(capture: capture)
      try writeRecord(record, to: url)
      return record
    }
    throw PendingRecordDecodingError.unsupported
  }

  private func decodeDeadLetter(at url: URL) throws -> OfflineCaptureDeadLetter {
    do {
      let letter = try ActionHubJSON.decoder().decode(OfflineCaptureDeadLetter.self, from: Data(contentsOf: url))
      guard letter.record.version == 1 else {
        throw ActionHubAPIError.encoding("지원하지 않는 dead-letter 레코드입니다")
      }
      return letter
    } catch let error as ActionHubAPIError {
      throw error
    } catch {
      throw ActionHubAPIError.encoding("dead-letter 레코드를 해석할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func pendingFileURLs() throws -> [URL] { try jsonFileURLs(in: pendingDirectoryURL) }
  private func deadLetterFileURLs() throws -> [URL] { try jsonFileURLs(in: deadLetterDirectoryURL) }

  private func jsonFileURLs(in directory: URL) throws -> [URL] {
    do {
      return try FileManager.default.contentsOfDirectory(
        at: directory, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]
      ).filter { $0.pathExtension == "json" }
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐 목록을 읽을 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func writeRecord(_ record: OfflineCaptureQueueRecord, to destination: URL) throws {
    do {
      let data = try ActionHubJSON.encoder().encode(record)
      try data.write(
        to: destination,
        options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
      )
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐를 저장할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func writeDeadLetter(_ letter: OfflineCaptureDeadLetter, to destination: URL) throws {
    do {
      let data = try ActionHubJSON.encoder().encode(letter)
      try data.write(
        to: destination,
        options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
      )
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐를 저장할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func moveItemAtomically(from source: URL, to destination: URL) throws {
    do {
      try FileManager.default.moveItem(at: source, to: destination)
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐 레코드를 이동할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func transition(
    from source: URL,
    to destination: URL,
    writeDestination: (URL) throws -> Void
  ) throws {
    guard !FileManager.default.fileExists(atPath: destination.path) else {
      throw ActionHubAPIError.encoding("capture transition destination already exists")
    }
    let stagedDestination = destination.deletingLastPathComponent().appendingPathComponent(
      ".offline-capture-transition-\(UUID().uuidString.lowercased()).json")
    do {
      try writeDestination(stagedDestination)
      try FileManager.default.moveItem(at: stagedDestination, to: destination)
    } catch {
      try? FileManager.default.removeItem(at: stagedDestination)
      throw ActionHubAPIError.encoding("오프라인 큐 전환 대상을 저장할 수 없습니다: \(error.localizedDescription)")
    }
    do {
      try removeItem(at: source, missingIsSuccess: false)
    } catch {
      try? FileManager.default.removeItem(at: destination)
      throw error
    }
  }

  private func removeItem(at url: URL, missingIsSuccess: Bool) throws {
    do {
      try FileManager.default.removeItem(at: url)
    } catch let error as CocoaError where missingIsSuccess && error.code == .fileNoSuchFile {
      return
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐 레코드를 삭제할 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func pendingFileURL(for captureId: String) throws -> URL {
    try recordFileURL(for: captureId, in: pendingDirectoryURL)
  }

  private func deadLetterFileURL(for captureId: String) throws -> URL {
    try recordFileURL(for: captureId, in: deadLetterDirectoryURL)
  }

  private func recordFileURL(for captureId: String, in directory: URL) throws -> URL {
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_."))
    guard captureId.count >= 8, captureId.count <= 80,
      captureId.unicodeScalars.allSatisfy(allowed.contains), !captureId.contains("..")
    else {
      throw ActionHubAPIError.encoding("안전하지 않은 capture ID입니다")
    }
    return directory.appendingPathComponent(captureId).appendingPathExtension("json")
  }

  private func quarantine(_ source: URL, suffix: String) throws {
    let destination = corruptDirectoryURL.appendingPathComponent(
      "\(suffix)-\(UUID().uuidString.lowercased()).json")
    try moveItemAtomically(from: source, to: destination)
  }

  private func createDirectory(_ url: URL) throws {
    do {
      try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    } catch {
      throw ActionHubAPIError.encoding("오프라인 큐 디렉터리를 만들 수 없습니다: \(error.localizedDescription)")
    }
  }

  private func withLock<T>(_ operation: () throws -> T) throws -> T {
    try createDirectory(baseDirectoryURL)
    let descriptor = open(lockFileURL.path, O_CREAT | O_RDWR, S_IRUSR | S_IWUSR)
    guard descriptor >= 0 else {
      throw ActionHubAPIError.encoding("오프라인 큐 잠금 파일을 열 수 없습니다")
    }
    guard flock(descriptor, LOCK_EX) == 0 else {
      _ = close(descriptor)
      throw ActionHubAPIError.encoding("오프라인 큐 잠금을 획득할 수 없습니다")
    }
    defer {
      _ = flock(descriptor, LOCK_UN)
      _ = close(descriptor)
    }
    return try operation()
  }
}
