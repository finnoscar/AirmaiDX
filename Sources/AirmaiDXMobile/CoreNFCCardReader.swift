#if os(iOS)
@preconcurrency import CoreNFC
import Foundation
import AirmaiMobileCore

/// Core NFC predates Swift concurrency annotations. The framework guarantees
/// that this connection context is used by its single completion callback.
private final class NFCConnectionContext: @unchecked Sendable {
    let session: NFCTagReaderSession
    let tag: NFCTag
    init(session: NFCTagReaderSession, tag: NFCTag) {
        self.session = session
        self.tag = tag
    }
}

@MainActor final class CoreNFCCardReader: NSObject, CardReader, ObservableObject {
    @Published private(set) var state: CardReaderState = .idle { didSet { onStateChange?(state) } }
    var onStateChange: ((CardReaderState) -> Void)?
    private var session: NFCTagReaderSession?

    override init() {
        super.init()
        if !NFCTagReaderSession.readingAvailable {
            state = .unavailable("此设备不支持 Core NFC 卡片读取。")
        }
    }

    func beginScanning() {
        guard NFCTagReaderSession.readingAvailable else {
            state = .unavailable("此设备不支持 Core NFC 卡片读取。")
            return
        }
        session?.invalidate()
        guard let next = NFCTagReaderSession(
            pollingOption: [.iso14443, .iso15693, .iso18092],
            delegate: self,
            queue: nil
        ) else {
            state = .failed("系统未能创建 NFC 扫描会话。")
            return
        }
        next.alertMessage = "将卡片靠近 iPhone 顶部。仅读取卡片类型和公开标识。"
        session = next
        state = .scanning
        next.begin()
    }

    func cancel() {
        session?.invalidate()
        session = nil
        if NFCTagReaderSession.readingAvailable { state = .idle }
    }
}

extension CoreNFCCardReader: NFCTagReaderSessionDelegate {
    nonisolated func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {}

    nonisolated func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        Task { @MainActor in
            self.session = nil
            let readerError = error as? NFCReaderError
            if readerError?.code == .readerSessionInvalidationErrorUserCanceled
                || readerError?.code == .readerSessionInvalidationErrorFirstNDEFTagRead {
                if case .found = self.state { return }
                self.state = .idle
            } else {
                self.state = .failed("未能完成读取，请重试。")
            }
        }
    }

    nonisolated func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        guard tags.count == 1, let tag = tags.first else {
            session.alertMessage = "一次只能读取一张卡片。"
            session.restartPolling()
            return
        }
        let context = NFCConnectionContext(session: session, tag: tag)
        session.connect(to: tag) { [weak self, context] error in
            let session = context.session
            guard error == nil else {
                session.alertMessage = "连接卡片失败，请保持位置后重试。"
                session.restartPolling()
                return
            }
            let identity: CardIdentity
            switch context.tag {
            case .feliCa(let card): identity = CardIdentity(technology: .feliCa, identifier: card.currentIDm)
            case .miFare(let card): identity = CardIdentity(technology: .miFare, identifier: card.identifier)
            case .iso7816(let card): identity = CardIdentity(technology: .iso7816, identifier: card.identifier)
            case .iso15693(let card): identity = CardIdentity(technology: .iso15693, identifier: card.identifier)
            @unknown default:
                session.alertMessage = "不支持这种卡片。"
                session.invalidate()
                return
            }
            session.alertMessage = "已读取卡片。"
            Task { @MainActor [weak self, identity, context] in
                self?.state = .found(identity)
                self?.session = nil
                context.session.invalidate()
            }
        }
    }
}
#endif
