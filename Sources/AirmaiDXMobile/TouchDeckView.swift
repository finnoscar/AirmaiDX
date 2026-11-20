#if os(iOS)
import SwiftUI
import AirmaiTouchKit

struct TouchDeckView: View {
    @State private var active: Set<TouchSensor> = []
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        GeometryReader { proxy in
            let side = min(proxy.size.width, proxy.size.height)
            ZStack {
                Circle().fill(.black.opacity(0.24))
                    .frame(width: side * 0.92, height: side * 0.92)
                Canvas { context, size in
                    let center = CGPoint(x: size.width / 2, y: size.height / 2)
                    let radius = min(size.width, size.height) * TouchSensorMesh.fieldRadiusScale
                    for sensor in TouchSensor.all {
                        for polygon in TouchSensorMesh.polygons(for: sensor) {
                            var path = Path()
                            for (index, point) in polygon.enumerated() {
                                let mapped = CGPoint(x: center.x + point.x * radius, y: center.y + point.y * radius)
                                index == 0 ? path.move(to: mapped) : path.addLine(to: mapped)
                            }
                            path.closeSubpath()
                            context.fill(path, with: .color(active.contains(sensor) ? MobileTheme.accent.opacity(0.85) : .white.opacity(0.08)))
                            context.stroke(path, with: .color(.white.opacity(active.contains(sensor) ? 0.9 : 0.22)), lineWidth: active.contains(sensor) ? 2 : 1)
                        }
                        let labelPoint = TouchSensorMesh.representativePoint(for: sensor)
                        context.draw(
                            Text(sensor.label).font(.caption2.weight(.semibold)).foregroundStyle(.white.opacity(0.82)),
                            at: CGPoint(x: center.x + labelPoint.x * radius, y: center.y + labelPoint.y * radius)
                        )
                    }
                }
                MultiTouchSurface { frame in active = frame.activeSensors }
                    .accessibilityLabel("触控区")
                    .accessibilityHint("支持多点触控，按下的区域会高亮")
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .aspectRatio(1, contentMode: .fit)
        .onChange(of: scenePhase) { _, phase in if phase != .active { active.removeAll() } }
    }
}
#endif
