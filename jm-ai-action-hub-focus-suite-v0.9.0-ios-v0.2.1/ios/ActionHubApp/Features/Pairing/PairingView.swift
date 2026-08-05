import ActionHubCore
import SwiftUI

struct PairingView: View {
  @EnvironmentObject private var model: AppModel
  @State private var payload = ""
  @State private var showScanner = false

  private var parsedPayload: PairingPayload? {
    try? PairingPayload.parse(payload)
  }

  /// `PairingPayload.parse` throws a specific Korean reason for every rejection (wrong scheme,
  /// duplicate query items, non-UUID pairing id, malformed code, ...). Discarding it via `try?`
  /// left users staring at a generic "유효하지 않습니다" no matter what was actually wrong.
  private var parseErrorMessage: String? {
    guard parsedPayload == nil,
      !payload.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else { return nil }
    do {
      _ = try PairingPayload.parse(payload)
      return nil
    } catch {
      return error.localizedDescription
    }
  }

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(alignment: .leading, spacing: 24) {
          VStack(alignment: .leading, spacing: 8) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
              .font(.system(size: 54))
              .foregroundStyle(.tint)
            Text("JM-AI Action Hub")
              .font(.largeTitle.bold())
            Text("서버에서 생성한 1회용 QR로 이 iPhone을 안전하게 연결합니다. 관리자 API 키는 iPhone에 저장되지 않습니다.")
              .foregroundStyle(.secondary)
          }
          Button {
            showScanner = true
          } label: {
            Label("페어링 QR 스캔", systemImage: "qrcode.viewfinder")
              .frame(maxWidth: .infinity)
          }
          .buttonStyle(.borderedProminent)
          .controlSize(.large)

          TextField("QR 내용 또는 jmactionhub://pair 링크 붙여넣기", text: $payload, axis: .vertical)
            .lineLimit(3...8)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .padding()
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))

          if let parsedPayload {
            VStack(alignment: .leading, spacing: 8) {
              Label("연결 정보 확인", systemImage: "checkmark.shield")
                .font(.headline)
              LabeledContent("서버", value: parsedPayload.server.absoluteString)
              LabeledContent("페어링 ID", value: String(parsedPayload.pairingId.prefix(8)) + "…")
              Text("표시된 서버가 본인이 운영하는 Action Hub인지 확인한 뒤 연결하세요.")
                .font(.footnote)
                .foregroundStyle(.secondary)
            }
            .padding()
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
          } else if let parseErrorMessage {
            Label(parseErrorMessage, systemImage: "exclamationmark.triangle")
              .font(.footnote)
              .foregroundStyle(.red)
          }

          Button("확인한 서버에 연결") {
            Task { await model.pair(using: payload) }
          }
          .buttonStyle(.bordered)
          .disabled(parsedPayload == nil || model.isRefreshing)

          if model.isRefreshing { ProgressView("연결 중…") }

          Divider()
          Text("서버 명령")
            .font(.headline)
          Text("`action-hub mobile-pairing --base-url https://허브주소` 실행 후 표시되는 QR Payload를 사용하세요.")
            .font(.callout.monospaced())
            .textSelection(.enabled)
        }
        .padding(24)
      }
      .navigationTitle("서버 연결")
      .onAppear {
        if let incoming = model.consumePendingPairingPayload() { payload = incoming }
      }
      .onChange(of: model.pendingPairingPayload) { _, incoming in
        guard let incoming else { return }
        payload = incoming
        _ = model.consumePendingPairingPayload()
      }
      .sheet(isPresented: $showScanner) {
        NavigationStack {
          QRScannerView { value in
            // QR scanning only stages the one-time credential. A separate visible
            // confirmation is required before the network claim is sent.
            payload = value
            showScanner = false
          } onError: { message in
            model.lastError = message
            showScanner = false
          }
          .ignoresSafeArea()
          .navigationTitle("QR 스캔")
          .toolbar {
            ToolbarItem(placement: .cancellationAction) {
              Button("취소") { showScanner = false }
            }
          }
        }
      }
    }
  }
}
