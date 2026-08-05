import XCTest

@testable import ActionHubCore

final class OfflineCaptureQueueTests: XCTestCase {
  func testQueuePersistsAndRemovesReceipts() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("captures.json")
    let first = OfflineCaptureQueue(fileURL: file)
    let capture = try await first.enqueue(text: "금요일까지 제안서 보내기", source: "share-extension")
    let firstCount = try await first.count()
    XCTAssertEqual(firstCount, 1)

    let reloaded = OfflineCaptureQueue(fileURL: file)
    let reloadedPending = try await reloaded.pending()
    XCTAssertEqual(reloadedPending.first?.clientCaptureId, capture.clientCaptureId)
    try await reloaded.apply(receipts: [
      CaptureReceipt(
        clientCaptureId: capture.clientCaptureId, status: "processed", planId: "plan-1", error: nil,
        deduplicated: false)
    ])
    let finalCount = try await reloaded.count()
    XCTAssertEqual(finalCount, 0)
  }

  func testRejectsEmptyCapture() async throws {
    let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let queue = OfflineCaptureQueue(fileURL: file)
    do {
      _ = try await queue.enqueue(text: "   ")
      XCTFail("Expected an error")
    } catch let error as ActionHubAPIError {
      guard case .encoding = error else { return XCTFail("Unexpected error: \(error)") }
    }
  }

  func testIndependentQueueInstancesDoNotLoseConcurrentCaptures() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("captures/pending.json")
    let appQueue = OfflineCaptureQueue(fileURL: file)
    let shareExtensionQueue = OfflineCaptureQueue(fileURL: file)

    async let appCapture = appQueue.enqueue(text: "앱에서 입력한 업무", source: "ios-app")
    async let sharedCapture = shareExtensionQueue.enqueue(
      text: "공유 확장에서 입력한 업무", source: "ios-share-extension")
    let captures = try await [appCapture, sharedCapture]

    let reloaded = OfflineCaptureQueue(fileURL: file)
    let pending = try await reloaded.pending(limit: 10)
    XCTAssertEqual(Set(pending.map(\.clientCaptureId)), Set(captures.map(\.clientCaptureId)))
    XCTAssertEqual(pending.count, 2)
  }

  func testLegacyArrayQueueIsMigratedWithoutDataLoss() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    let file = root.appendingPathComponent("pending.json")
    let capture = CaptureInput(
      clientCaptureId: UUID().uuidString.lowercased(),
      text: "기존 v0.1 오프라인 입력"
    )
    let legacyData = try ActionHubJSON.encoder().encode([capture])
    try legacyData.write(to: file, options: .atomic)

    let queue = OfflineCaptureQueue(fileURL: file)
    let pending = try await queue.pending()
    XCTAssertEqual(pending.count, 1)
    XCTAssertEqual(pending.first?.clientCaptureId, capture.clientCaptureId)
    XCTAssertEqual(pending.first?.text, capture.text)
    XCTAssertFalse(FileManager.default.fileExists(atPath: file.path))
  }

  func testFailedReceiptsMovePoisonCaptureToDeadLetterAndRestoreOrPurgeExplicitly() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("captures/pending.json")
    let queue = OfflineCaptureQueue(fileURL: file)
    let capture = try await queue.enqueue(text: "실패할 오프라인 수집")
    let longError = String(repeating: "e", count: 1_100)

    for _ in 1...5 {
      try await queue.apply(receipts: [
        CaptureReceipt(
          clientCaptureId: capture.clientCaptureId,
          status: "failed",
          planId: nil,
          error: longError,
          deduplicated: false
        )
      ])
    }

    let pendingAfterFailures = try await queue.count()
    let deadLetterCount = try await queue.deadLetterCount()
    let letters = try await queue.deadLetters()
    XCTAssertEqual(pendingAfterFailures, 0)
    XCTAssertEqual(deadLetterCount, 1)
    let deadLetter = try XCTUnwrap(letters.first)
    XCTAssertEqual(deadLetter.record.version, 1)
    XCTAssertEqual(deadLetter.record.attemptCount, 5)
    XCTAssertEqual(deadLetter.record.lastError?.count, 1_024)
    XCTAssertNotNil(deadLetter.record.lastAttemptAt)

    try await queue.restoreDeadLetter(clientCaptureId: capture.clientCaptureId)
    let deadLetterCountAfterRestore = try await queue.deadLetterCount()
    let pendingAfterRestore = try await queue.count()
    XCTAssertEqual(deadLetterCountAfterRestore, 0)
    XCTAssertEqual(pendingAfterRestore, 1)
    let restoredData = try Data(contentsOf: root.appendingPathComponent(
      "captures/pending/\(capture.clientCaptureId).json"))
    let restored = try ActionHubJSON.decoder().decode(OfflineCaptureQueueRecord.self, from: restoredData)
    XCTAssertEqual(restored.attemptCount, 0)
    XCTAssertNil(restored.lastError)
    XCTAssertNil(restored.lastAttemptAt)

    for _ in 1...5 {
      try await queue.apply(receipts: [
        CaptureReceipt(
          clientCaptureId: capture.clientCaptureId,
          status: "failed",
          planId: nil,
          error: "confirmed failure",
          deduplicated: false
        )
      ])
    }
    try await queue.purgeDeadLetter(clientCaptureId: capture.clientCaptureId)
    try await queue.purgeDeadLetter(clientCaptureId: capture.clientCaptureId)
    let deadLetterCountAfterPurge = try await queue.deadLetterCount()
    XCTAssertEqual(deadLetterCountAfterPurge, 0)
  }

  func testTransportFailureDoesNotIncrementAttemptMetadata() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let file = root.appendingPathComponent("captures/pending.json")
    let queue = OfflineCaptureQueue(fileURL: file)
    let capture = try await queue.enqueue(text: "네트워크 실패는 재시도 횟수를 늘리지 않는다")
    let session = MobileSession(store: InMemoryCredentialStore())

    do {
      _ = try await queue.flush(using: session)
      XCTFail("Expected upload without a stored session to fail")
    } catch {
      XCTAssertEqual(error as? ActionHubAPIError, .noStoredSession)
    }

    let data = try Data(contentsOf: root.appendingPathComponent(
      "captures/pending/\(capture.clientCaptureId).json"))
    let record = try ActionHubJSON.decoder().decode(OfflineCaptureQueueRecord.self, from: data)
    XCTAssertEqual(record.attemptCount, 0)
    XCTAssertNil(record.lastError)
    XCTAssertNil(record.lastAttemptAt)
  }

  func testRawPerFileCaptureIsMigratedToVersionedRecordBeforeLegacyArrayDecode() async throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString, isDirectory: true)
    defer { try? FileManager.default.removeItem(at: root) }
    let base = root.appendingPathComponent("captures", isDirectory: true)
    let pending = base.appendingPathComponent("pending", isDirectory: true)
    try FileManager.default.createDirectory(at: pending, withIntermediateDirectories: true)
    let capture = CaptureInput(clientCaptureId: UUID().uuidString.lowercased(), text: "기존 단일 파일")
    let rawURL = pending.appendingPathComponent(capture.clientCaptureId).appendingPathExtension("json")
    try ActionHubJSON.encoder().encode(capture).write(to: rawURL, options: .atomic)

    let queue = OfflineCaptureQueue(fileURL: base.appendingPathComponent("pending.json"))
    let migratedPending = try await queue.pending()
    XCTAssertEqual(migratedPending.map(\.clientCaptureId), [capture.clientCaptureId])
    let migrated = try ActionHubJSON.decoder().decode(
      OfflineCaptureQueueRecord.self, from: Data(contentsOf: rawURL))
    // Compare against the persisted-precision capture: ISO-8601 fractional encoding keeps
    // milliseconds, so an in-memory Date's sub-millisecond tail never survives the file.
    let persistedCapture = try ActionHubJSON.decoder().decode(
      CaptureInput.self, from: ActionHubJSON.encoder().encode(capture))
    XCTAssertEqual(migrated, OfflineCaptureQueueRecord(capture: persistedCapture))
  }
}
