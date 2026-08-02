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
}
