import XCTest

@testable import ActionHubCore

final class SpeechPermissionCopyTests: XCTestCase {
  func testAuthorizedPairHasNoBlockingMessage() {
    XCTAssertNil(
      SpeechPermissionCopy.blockingMessage(speech: .authorized, microphone: .authorized))
  }

  func testNotDeterminedPairHasNoBlockingMessage() {
    XCTAssertNil(
      SpeechPermissionCopy.blockingMessage(speech: .notDetermined, microphone: .notDetermined))
    XCTAssertFalse(
      SpeechPermissionCopy.needsSettingsAction(speech: .notDetermined, microphone: .notDetermined)
    )
  }

  func testDeniedEitherSideBlocksWithSettingsGuidance() {
    XCTAssertEqual(
      SpeechPermissionCopy.blockingMessage(speech: .denied, microphone: .authorized),
      "마이크와 음성 인식 권한이 꺼져 있습니다. 설정에서 권한을 켜주세요.")
    XCTAssertEqual(
      SpeechPermissionCopy.blockingMessage(speech: .authorized, microphone: .denied),
      "마이크와 음성 인식 권한이 꺼져 있습니다. 설정에서 권한을 켜주세요.")
    XCTAssertTrue(
      SpeechPermissionCopy.needsSettingsAction(speech: .denied, microphone: .authorized))
    XCTAssertTrue(
      SpeechPermissionCopy.needsSettingsAction(speech: .authorized, microphone: .denied))
  }

  func testRestrictedTakesPriorityAndBlocks() {
    XCTAssertEqual(
      SpeechPermissionCopy.blockingMessage(speech: .restricted, microphone: .authorized),
      "이 기기에서는 음성 입력이 제한되어 있습니다.")
    XCTAssertTrue(
      SpeechPermissionCopy.needsSettingsAction(speech: .restricted, microphone: .authorized))
  }
}

final class SpeechTranscriptMergeTests: XCTestCase {
  func testEmptyBaseTextUsesResultVerbatim() {
    XCTAssertEqual(
      SpeechTranscriptMerge.apply(
        currentText: "", lastApplied: "", baseText: "", newResult: "안녕하세요"),
      "안녕하세요")
  }

  func testNonEmptyBaseTextIsPrefixedNotOverwritten() {
    XCTAssertEqual(
      SpeechTranscriptMerge.apply(
        currentText: "기존 메모", lastApplied: "기존 메모", baseText: "기존 메모",
        newResult: "추가 내용"),
      "기존 메모 추가 내용")
  }

  func testBaseTextEndingInNewlineIsNotDoubleSpaced() {
    XCTAssertEqual(
      SpeechTranscriptMerge.apply(
        currentText: "기존 메모\n", lastApplied: "기존 메모\n", baseText: "기존 메모\n",
        newResult: "추가 내용"),
      "기존 메모\n추가 내용")
  }

  func testManualEditSinceLastResultIsNotStomped() {
    XCTAssertNil(
      SpeechTranscriptMerge.apply(
        currentText: "사용자가 손으로 고침", lastApplied: "이전 partial 결과", baseText: "",
        newResult: "새로운 partial 결과"))
  }

  func testEmptyNewResultDoesNothing() {
    XCTAssertNil(
      SpeechTranscriptMerge.apply(currentText: "", lastApplied: "", baseText: "", newResult: ""))
  }

  func testCumulativeResultsKeepReplacingSuffixNotAppending() {
    // The recognizer sends cumulative (not incremental) partials; a second, longer partial
    // should replace the first appended suffix rather than stack on top of it.
    let base = "기존 메모"
    let first = SpeechTranscriptMerge.apply(
      currentText: base, lastApplied: base, baseText: base, newResult: "추가")
    XCTAssertEqual(first, "기존 메모 추가")
    let second = SpeechTranscriptMerge.apply(
      currentText: first!, lastApplied: first!, baseText: base, newResult: "추가 내용")
    XCTAssertEqual(second, "기존 메모 추가 내용")
  }
}
