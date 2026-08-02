import Foundation

public enum ActionHubJSON {
  public static func encoder() -> JSONEncoder {
    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase
    encoder.dateEncodingStrategy = .custom { date, encoder in
      var container = encoder.singleValueContainer()
      try container.encode(makeFormatter(fractional: true).string(from: date))
    }
    return encoder
  }

  public static func decoder() -> JSONDecoder {
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    decoder.dateDecodingStrategy = .custom { decoder in
      let container = try decoder.singleValueContainer()
      let value = try container.decode(String.self)
      if let date = makeFormatter(fractional: true).date(from: value)
        ?? makeFormatter(fractional: false).date(from: value)
      {
        return date
      }
      throw DecodingError.dataCorruptedError(
        in: container,
        debugDescription: "Unsupported ISO-8601 date: \(value)"
      )
    }
    return decoder
  }

  private static func makeFormatter(fractional: Bool) -> ISO8601DateFormatter {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions =
      fractional
      ? [.withInternetDateTime, .withFractionalSeconds]
      : [.withInternetDateTime]
    return formatter
  }
}
