// Sensor polygons derived from Airmai's SimaiInputMapper.
// Airmai MIT © 2026 Finn and AirMai contributors.
// Polygon data derives from simai_flutter's MIT-licensed Majdata JudgeAreas port
// © 2024 its authors. Keep this notice with redistributed source/binaries.

import Foundation
import CoreGraphics

public enum TouchSensorMesh {
    /// Radius of the interactive disc relative to the shortest view edge.
    public static let fieldRadiusScale: CGFloat = 0.425
    private static let meshToFieldRadius: CGFloat = 100 * 0.021432761 / 4.8

    private static let aPolygon: [CGPoint] = [
        .init(x: 1.430501, y: 0.410449), .init(x: 1.593672, y: 0.245906),
        .init(x: 2.463311, y: 0.363903), .init(x: 2.433419, y: 0.540234),
        .init(x: 2.313523, y: 0.923573), .init(x: 2.120256, y: 1.299280),
        .init(x: 2.004719, y: 1.478614), .init(x: 1.300943, y: 0.952039),
        .init(x: 1.300530, y: 0.727795), .init(x: 1.336207, y: 0.641237),
        .init(x: 1.371884, y: 0.554679), .init(x: 1.401192, y: 0.482564)
    ]
    private static let bPolygon: [CGPoint] = [
        .init(x: 0.633842, y: 0.267105), .init(x: 0.877328, y: 0.021679),
        .init(x: 0.949844, y: 0.021679), .init(x: 1.038919, y: 0.021679),
        .init(x: 1.300919, y: 0.279573), .init(x: 1.213297, y: 0.490707),
        .init(x: 1.115504, y: 0.725222), .init(x: 1.073558, y: 0.725222),
        .init(x: 0.756555, y: 0.725222), .init(x: 0.633842, y: 0.600329),
        .init(x: 0.633842, y: 0.490707), .init(x: 0.633842, y: 0.376373)
    ]
    private static let cHalfPolygon: [CGPoint] = [
        .init(x: 0.029968, y: -0.480311), .init(x: 0.200254, y: -0.480311),
        .init(x: 0.482047, y: -0.199425), .init(x: 0.482047, y: 0.200260),
        .init(x: 0.200254, y: 0.479532), .init(x: 0.029968, y: 0.479532)
    ]
    private static let dPolygon: [CGPoint] = [
        .init(x: 1.635722, y: -0.197556), .init(x: 2.067223, y: -0.263554),
        .init(x: 2.475411, y: -0.315664), .init(x: 2.491906, y: 0.000249),
        .init(x: 2.471876, y: 0.320876), .init(x: 2.067223, y: 0.262140),
        .init(x: 1.635153, y: 0.199343), .init(x: 1.829966, y: 0.000122)
    ]
    private static let ePolygon: [CGPoint] = [
        .init(x: 1.098899, y: 0), .init(x: 1.433727, y: -0.334828),
        .init(x: 1.768555, y: 0), .init(x: 1.433727, y: 0.334828)
    ]

    public static func sensor(at point: CGPoint) -> TouchSensor? {
        let raw = CGPoint(x: point.x / meshToFieldRadius, y: point.y / meshToFieldRadius)
        let mirrored = cHalfPolygon.map { CGPoint(x: -$0.x, y: -$0.y) }
        let minY = cHalfPolygon.map(\.y).min() ?? 0
        let maxY = cHalfPolygon.map(\.y).max() ?? 0
        if contains(cHalfPolygon, point: raw) || contains(mirrored, point: raw)
            || (abs(raw.x) <= cHalfPolygon[0].x && raw.y >= minY && raw.y <= maxY) {
            return TouchSensor(ring: .c, index: 1)
        }

        let abIndex = nearestIndex(angle: atan2(point.y, point.x), firstAngleDegrees: -67.5)
        let abRaw = rotate(raw, radians: degrees(90 - CGFloat(abIndex) * 45))
        if contains(aPolygon, point: abRaw) { return TouchSensor(ring: .a, index: abIndex + 1) }
        if contains(bPolygon, point: abRaw) { return TouchSensor(ring: .b, index: abIndex + 1) }

        let deIndex = nearestIndex(angle: atan2(point.y, point.x), firstAngleDegrees: -90)
        let deRaw = rotate(raw, radians: degrees(90 - CGFloat(deIndex) * 45))
        if contains(dPolygon, point: deRaw) { return TouchSensor(ring: .d, index: deIndex + 1) }
        if contains(ePolygon, point: deRaw) { return TouchSensor(ring: .e, index: deIndex + 1) }
        return nil
    }

    public static func polygons(for sensor: TouchSensor) -> [[CGPoint]] {
        func transform(_ source: [CGPoint], rotation: CGFloat) -> [CGPoint] {
            source.map {
                let point = rotate($0, radians: rotation)
                return CGPoint(x: point.x * meshToFieldRadius, y: point.y * meshToFieldRadius)
            }
        }
        let zeroBased = CGFloat(sensor.index - 1)
        switch sensor.ring {
        case .a: return [transform(aPolygon, rotation: degrees(zeroBased * 45 - 90))]
        case .b: return [transform(bPolygon, rotation: degrees(zeroBased * 45 - 90))]
        case .c:
            let mirrored = cHalfPolygon.map { CGPoint(x: -$0.x, y: -$0.y) }
            let minY = cHalfPolygon.map(\.y).min() ?? 0
            let maxY = cHalfPolygon.map(\.y).max() ?? 0
            let bridge = [
                CGPoint(x: -cHalfPolygon[0].x, y: minY), CGPoint(x: cHalfPolygon[0].x, y: minY),
                CGPoint(x: cHalfPolygon[0].x, y: maxY), CGPoint(x: -cHalfPolygon[0].x, y: maxY)
            ]
            return [transform(cHalfPolygon, rotation: 0), transform(mirrored, rotation: 0), transform(bridge, rotation: 0)]
        case .d: return [transform(dPolygon, rotation: degrees(zeroBased * 45 - 90))]
        case .e: return [transform(ePolygon, rotation: degrees(zeroBased * 45 - 90))]
        }
    }

    public static func representativePoint(for sensor: TouchSensor) -> CGPoint {
        if sensor.ring == .c { return .zero }
        let radius: CGFloat
        let offset: CGFloat
        switch sensor.ring {
        case .a: radius = 4 / 4.8; offset = 0
        case .b: radius = 2.2 / 4.8; offset = 0
        case .c: return .zero
        case .d: radius = 4.1 / 4.8; offset = -.pi / 8
        case .e: radius = 3.1 / 4.8; offset = -.pi / 8
        }
        let angle = (-CGFloat.pi * 3 / 8) + CGFloat(sensor.index - 1) * (.pi / 4) + offset
        return CGPoint(x: cos(angle) * radius, y: sin(angle) * radius)
    }

    private static func nearestIndex(angle: CGFloat, firstAngleDegrees: CGFloat) -> Int {
        let raw = Int(round((angle - degrees(firstAngleDegrees)) / (.pi / 4)))
        return ((raw % 8) + 8) % 8
    }

    private static func contains(_ polygon: [CGPoint], point: CGPoint) -> Bool {
        guard polygon.count >= 3 else { return false }
        var inside = false
        var previous = polygon.count - 1
        for current in polygon.indices {
            let lhs = polygon[current], rhs = polygon[previous]
            if isOnSegment(point, rhs, lhs) { return true }
            let crosses = (lhs.y > point.y) != (rhs.y > point.y)
                && point.x < (rhs.x - lhs.x) * (point.y - lhs.y) / (rhs.y - lhs.y) + lhs.x
            if crosses { inside.toggle() }
            previous = current
        }
        return inside
    }

    private static func isOnSegment(_ point: CGPoint, _ start: CGPoint, _ end: CGPoint) -> Bool {
        let edgeX = end.x - start.x, edgeY = end.y - start.y
        let pointX = point.x - start.x, pointY = point.y - start.y
        guard abs(edgeX * pointY - edgeY * pointX) <= 1e-9 else { return false }
        let dot = pointX * edgeX + pointY * edgeY
        return dot >= -1e-9 && dot <= edgeX * edgeX + edgeY * edgeY + 1e-9
    }

    private static func rotate(_ point: CGPoint, radians: CGFloat) -> CGPoint {
        CGPoint(x: point.x * cos(radians) - point.y * sin(radians),
                y: point.x * sin(radians) + point.y * cos(radians))
    }

    private static func degrees(_ value: CGFloat) -> CGFloat { value * .pi / 180 }
}
