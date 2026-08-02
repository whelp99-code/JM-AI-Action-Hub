import AVFoundation
import SwiftUI

struct QRScannerView: UIViewControllerRepresentable {
  let onCode: (String) -> Void
  let onError: (String) -> Void

  func makeUIViewController(context: Context) -> QRScannerController {
    let controller = QRScannerController()
    controller.onCode = onCode
    controller.onError = onError
    return controller
  }

  func updateUIViewController(_ uiViewController: QRScannerController, context: Context) {}
}

final class QRScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
  var onCode: ((String) -> Void)?
  var onError: ((String) -> Void)?
  private let session = AVCaptureSession()
  private var previewLayer: AVCaptureVideoPreviewLayer?
  private var didScan = false
  private var isConfigured = false

  override func viewDidLoad() {
    super.viewDidLoad()
    view.backgroundColor = .black
    requestCameraAndConfigure()
  }

  override func viewWillDisappear(_ animated: Bool) {
    super.viewWillDisappear(animated)
    if session.isRunning { session.stopRunning() }
  }

  override func viewDidLayoutSubviews() {
    super.viewDidLayoutSubviews()
    previewLayer?.frame = view.bounds
  }

  private func requestCameraAndConfigure() {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized:
      configureSession()
    case .notDetermined:
      AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
        Task { @MainActor in
          guard let self else { return }
          if granted {
            self.configureSession()
          } else {
            self.onError?("카메라 권한이 없어 QR 코드를 스캔할 수 없습니다.")
          }
        }
      }
    case .denied, .restricted:
      onError?("설정에서 Action Hub의 카메라 권한을 허용하세요.")
    @unknown default:
      onError?("카메라 권한 상태를 확인할 수 없습니다.")
    }
  }

  private func configureSession() {
    guard !isConfigured else { return }
    guard let device = AVCaptureDevice.default(for: .video) else {
      onError?("사용 가능한 카메라가 없습니다.")
      return
    }
    do {
      let input = try AVCaptureDeviceInput(device: device)
      guard session.canAddInput(input) else {
        onError?("카메라 입력을 구성할 수 없습니다.")
        return
      }
      session.addInput(input)
    } catch {
      onError?("카메라를 시작할 수 없습니다: \(error.localizedDescription)")
      return
    }

    let output = AVCaptureMetadataOutput()
    guard session.canAddOutput(output) else {
      onError?("QR 스캐너 출력을 구성할 수 없습니다.")
      return
    }
    session.addOutput(output)
    output.setMetadataObjectsDelegate(self, queue: .main)
    output.metadataObjectTypes = [.qr]

    let preview = AVCaptureVideoPreviewLayer(session: session)
    preview.videoGravity = .resizeAspectFill
    preview.frame = view.bounds
    view.layer.addSublayer(preview)
    previewLayer = preview
    isConfigured = true

    let box = CaptureSessionBox(session)
    DispatchQueue.global(qos: .userInitiated).async { box.session.startRunning() }
  }

  func metadataOutput(
    _ output: AVCaptureMetadataOutput,
    didOutput metadataObjects: [AVMetadataObject],
    from connection: AVCaptureConnection
  ) {
    guard !didScan,
      let object = metadataObjects.first as? AVMetadataMachineReadableCodeObject,
      let value = object.stringValue
    else { return }
    didScan = true
    session.stopRunning()
    onCode?(value)
  }
}

private final class CaptureSessionBox: @unchecked Sendable {
  let session: AVCaptureSession
  init(_ session: AVCaptureSession) { self.session = session }
}
