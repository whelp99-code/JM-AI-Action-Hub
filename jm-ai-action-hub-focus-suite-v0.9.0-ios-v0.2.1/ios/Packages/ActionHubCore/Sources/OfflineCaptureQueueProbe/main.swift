import ActionHubCore
import Foundation

#if os(Linux)
  import Glibc
#else
  import Darwin
#endif

@main
struct OfflineCaptureQueueProbe {
  private struct Arguments {
    let command: String
    let legacyFileURL: URL
    let prefix: String
    let count: Int
    let rounds: Int
    let milliseconds: Int

    init() throws {
      var values: [String: String] = [:]
      let arguments = Array(CommandLine.arguments.dropFirst())
      guard let command = arguments.first else { throw ProbeError.usage }
      var index = 1
      while index < arguments.count {
        let key = arguments[index]
        guard key.hasPrefix("--"), index + 1 < arguments.count else { throw ProbeError.usage }
        values[key] = arguments[index + 1]
        index += 2
      }
      guard let path = values["--legacy-file"], path.hasPrefix("/") else { throw ProbeError.usage }
      guard let count = Int(values["--count"] ?? "0"), count >= 0 else { throw ProbeError.usage }
      guard let rounds = Int(values["--rounds"] ?? "1"), rounds >= 0 else { throw ProbeError.usage }
      guard let milliseconds = Int(values["--milliseconds"] ?? "0"), milliseconds >= 0 else {
        throw ProbeError.usage
      }
      self.command = command
      legacyFileURL = URL(fileURLWithPath: path)
      prefix = values["--prefix"] ?? "probe"
      self.count = count
      self.rounds = rounds
      self.milliseconds = milliseconds
    }
  }

  private enum ProbeError: LocalizedError {
    case usage
    case unknownCommand(String)

    var errorDescription: String? {
      switch self {
      case .usage:
        return "usage: offline-capture-queue-probe enqueue|apply-failed|restore|purge|inventory|hold-lock --legacy-file <absolute pending.json> --prefix <string> --count <int> [--rounds <int>] [--milliseconds <int>]"
      case .unknownCommand(let command): return "unknown command: \(command)"
      }
    }
  }

  static func main() async {
    do {
      let arguments = try Arguments()
      let queue = OfflineCaptureQueue(fileURL: arguments.legacyFileURL)
      switch arguments.command {
      case "enqueue":
        for index in 0..<arguments.count {
          try await queue.append(capture(arguments.prefix, index))
        }
        print("ENQUEUED count=\(arguments.count) prefix=\(arguments.prefix)")
      case "apply-failed":
        for _ in 0..<arguments.rounds {
          let captures = try await queue.pending(limit: .max).filter {
            $0.clientCaptureId.hasPrefix("\(arguments.prefix)-capture-")
          }
          try await queue.apply(receipts: try captures.map {
            try failedReceipt(clientCaptureID: $0.clientCaptureId)
          })
        }
        print("FAILED rounds=\(arguments.rounds) prefix=\(arguments.prefix)")
      case "restore":
        let letters = try await queue.deadLetters(limit: .max).filter { isOddCapture($0.id) }
        for letter in letters { try await queue.restoreDeadLetter(clientCaptureId: letter.id) }
        print("RESTORED count=\(letters.count)")
      case "purge":
        let letters = try await queue.deadLetters(limit: .max).filter { !isOddCapture($0.id) }
        for letter in letters { try await queue.purgeDeadLetter(clientCaptureId: letter.id) }
        print("PURGED count=\(letters.count)")
      case "inventory":
        let pending = try await queue.pending(limit: .max)
        let letters = try await queue.deadLetters(limit: .max)
        let unique = Set(pending.map(\.clientCaptureId)).union(letters.map(\.id)).count
        let corrupt = try jsonFileCount(
          at: arguments.legacyFileURL.deletingLastPathComponent().appendingPathComponent("corrupt"))
        print("INVENTORY pending=\(pending.count) dlq=\(letters.count) corrupt=\(corrupt) unique=\(unique)")
      case "hold-lock":
        try await queue.holdLock(milliseconds: arguments.milliseconds) {
          print("LOCK_HELD")
          fflush(stdout)
        }
      default:
        throw ProbeError.unknownCommand(arguments.command)
      }
    } catch {
      FileHandle.standardError.write(Data("offline-capture-queue-probe: \(error.localizedDescription)\n".utf8))
      exit(1)
    }
  }

  private static func capture(_ prefix: String, _ index: Int) -> CaptureInput {
    CaptureInput(
      clientCaptureId: "\(prefix)-capture-\(String(format: "%04d", index))",
      text: "probe capture \(prefix) \(index)",
      source: "offline-capture-queue-probe",
      timezone: "UTC",
      referenceTime: Date(timeIntervalSince1970: TimeInterval(index))
    )
  }

  private static func failedReceipt(clientCaptureID: String) throws -> CaptureReceipt {
    let payload: [String: Any] = [
      "clientCaptureId": clientCaptureID,
      "status": "failed",
      "planId": NSNull(),
      "error": "probe confirmed failure",
      "deduplicated": false,
    ]
    return try JSONDecoder().decode(
      CaptureReceipt.self, from: JSONSerialization.data(withJSONObject: payload))
  }

  private static func isOddCapture(_ captureID: String) -> Bool {
    guard let suffix = captureID.split(separator: "-").last, let index = Int(suffix) else { return false }
    return index % 2 == 1
  }

  private static func jsonFileCount(at directory: URL) throws -> Int {
    guard FileManager.default.fileExists(atPath: directory.path) else { return 0 }
    return try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
      .filter { $0.pathExtension == "json" }
      .count
  }
}
