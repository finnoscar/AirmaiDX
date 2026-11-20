import Foundation

/// Synchronous publication keeps the Judge -> Event hop free of actor/main-thread
/// scheduling. Each consumer receives its own AsyncStream and can process events
/// on an appropriate executor.
final class GameplayEventBus: @unchecked Sendable {
    static let shared = GameplayEventBus()

    private let lock = NSLock()
    private var continuations: [UUID: AsyncStream<GameplayEvent>.Continuation] = [:]

    func events(bufferingNewest limit: Int = 256) -> AsyncStream<GameplayEvent> {
        let subscriberID = UUID()
        return AsyncStream(bufferingPolicy: .bufferingNewest(max(limit, 1))) { continuation in
            lock.lock()
            continuations[subscriberID] = continuation
            lock.unlock()

            continuation.onTermination = { [weak self] _ in
                self?.removeSubscriber(subscriberID)
            }
        }
    }

    func publish(_ event: GameplayEvent) {
        lock.lock()
        let activeContinuations = Array(continuations.values)
        lock.unlock()

        for continuation in activeContinuations {
            continuation.yield(event)
        }
    }

    private func removeSubscriber(_ id: UUID) {
        lock.lock()
        continuations.removeValue(forKey: id)
        lock.unlock()
    }
}
