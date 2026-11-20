#if os(iOS)
import SwiftUI
import UIKit
import AirmaiTouchKit

struct MultiTouchSurface: UIViewRepresentable {
    let onFrame: (TouchFrame) -> Void

    func makeUIView(context: Context) -> MultiTouchView {
        let view = MultiTouchView()
        view.backgroundColor = .clear
        view.isMultipleTouchEnabled = true
        view.isExclusiveTouch = false
        view.onFrame = onFrame
        return view
    }

    func updateUIView(_ view: MultiTouchView, context: Context) { view.onFrame = onFrame }

    static func dismantleUIView(_ view: MultiTouchView, coordinator: ()) { view.releaseAll() }
}

final class MultiTouchView: UIView {
    var onFrame: ((TouchFrame) -> Void)?
    private var state = TouchContactState()

    override init(frame: CGRect) {
        super.init(frame: frame)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(applicationWillResignActive),
            name: UIApplication.willResignActiveNotification,
            object: nil
        )
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(applicationWillResignActive),
            name: UIApplication.willResignActiveNotification,
            object: nil
        )
    }

    deinit { NotificationCenter.default.removeObserver(self) }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        super.touchesBegan(touches, with: event)
        emit(touches.map(contact), phase: .began)
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        super.touchesMoved(touches, with: event)
        var contacts: [TouchContact] = []
        for touch in touches {
            let identifier = touchID(touch)
            var samples = event?.coalescedTouches(for: touch) ?? []
            if samples.isEmpty { samples = [touch] }
            else if let last = samples.last, last.timestamp + 0.000_001 < touch.timestamp { samples.append(touch) }
            contacts.append(contentsOf: samples.map { contact($0, id: identifier) })
        }
        emit(contacts, phase: .moved)
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        super.touchesEnded(touches, with: event)
        emit(touches.map(contact), phase: .ended)
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        super.touchesCancelled(touches, with: event)
        emit(touches.map(contact), phase: .cancelled)
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window == nil { releaseAll() }
    }

    func releaseAll() { onFrame?(state.releaseAll()) }

    @objc private func applicationWillResignActive() { releaseAll() }

    private func emit(_ contacts: [TouchContact], phase: TouchFrame.Phase) {
        guard bounds.width > 0, bounds.height > 0 else { return }
        onFrame?(state.update(contacts, phase: phase))
    }

    private func contact(_ touch: UITouch) -> TouchContact { contact(touch, id: touchID(touch)) }

    private func contact(_ touch: UITouch, id: Int) -> TouchContact {
        let center = CGPoint(x: bounds.midX, y: bounds.midY)
        let radius = min(bounds.width, bounds.height) * TouchSensorMesh.fieldRadiusScale
        let point = touch.location(in: self)
        return TouchContact(
            id: id,
            point: CGPoint(x: (point.x - center.x) / radius, y: (point.y - center.y) / radius),
            timestamp: touch.timestamp
        )
    }

    private func touchID(_ touch: UITouch) -> Int { ObjectIdentifier(touch).hashValue }
}
#endif
