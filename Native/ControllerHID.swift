import Foundation
import IOKit
import IOKit.hid
import Darwin

// Known non-keyboard controller collections only. No seizure or output writes.
let identities: Set<String> = ["11836:22352", "11852:22352", "11836:22375", "11836:22376", "11836:22353", "11836:22354", "3727:4644"]
func number(_ device: IOHIDDevice, _ key: String) -> Int { (IOHIDDeviceGetProperty(device, key as CFString) as? NSNumber)?.intValue ?? 0 }
func permitted(_ device: IOHIDDevice) -> Bool {
    let page = number(device, kIOHIDPrimaryUsagePageKey), usage = number(device, kIOHIDPrimaryUsageKey)
    return identities.contains("\(number(device, kIOHIDVendorIDKey)):\(number(device, kIOHIDProductIDKey))") && page != 7 && !(page == 1 && [1, 2, 6, 7].contains(usage))
}
func emit(_ row: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) {
        FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
    }
}
func registryID(_ service: io_service_t) -> String { var id: UInt64 = 0; IORegistryEntryGetRegistryEntryID(service, &id); return String(id) }
func devices() -> [IOHIDDevice] {
    var iterator: io_iterator_t = 0
    guard IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOHIDDevice"), &iterator) == KERN_SUCCESS else { return [] }
    defer { IOObjectRelease(iterator) }
    var result: [IOHIDDevice] = []
    while true {
        let service = IOIteratorNext(iterator); if service == 0 { break }
        if let device = IOHIDDeviceCreate(kCFAllocatorDefault, service), identities.contains("\(number(device, kIOHIDVendorIDKey)):\(number(device, kIOHIDProductIDKey))") { result.append(device) }
        IOObjectRelease(service)
    }
    return result
}
func row(_ device: IOHIDDevice) -> [String: Any] {
    ["id": registryID(IOHIDDeviceGetService(device)), "vendor": number(device, kIOHIDVendorIDKey), "product": number(device, kIOHIDProductIDKey),
     "usagePage": number(device, kIOHIDPrimaryUsagePageKey), "usage": number(device, kIOHIDPrimaryUsageKey),
     "name": (IOHIDDeviceGetProperty(device, kIOHIDProductKey as CFString) as? String) ?? "USB controller",
     "descriptor": ((IOHIDDeviceGetProperty(device, kIOHIDReportDescriptorKey as CFString) as? Data) ?? Data()).base64EncodedString()]
}
final class Connection {
    let device: IOHIDDevice
    let id: String
    let buffer: UnsafeMutablePointer<UInt8>
    let capacity: Int
    var alive = true
    var previous = Data()
    init(_ d: IOHIDDevice) {
        device = d; id = registryID(IOHIDDeviceGetService(d))
        capacity = max(64, min(4096, number(d, kIOHIDMaxInputReportSizeKey)))
        buffer = .allocate(capacity: capacity); buffer.initialize(repeating: 0, count: capacity)
    }
    deinit { buffer.deallocate() }
}
let callback: IOHIDReportCallback = { context, result, _, _, reportID, report, length in
    guard let context, result == kIOReturnSuccess, length > 0, length <= 4096 else { return }
    let state = Unmanaged<Connection>.fromOpaque(context).takeUnretainedValue()
    guard state.alive else { return }
    let data = Data(bytes: report, count: length)
    // State-change reports are retained until removal. Unchanged input never
    // generates a high-rate JSON/logging loop; heartbeat proves liveness.
    var key = Data([UInt8(truncatingIfNeeded: reportID)]); key.append(data)
    if state.previous == key { return }; state.previous = key
    emit(["event": "report", "id": state.id, "reportID": reportID, "hex": data.map { String(format: "%02x", $0) }.joined()])
}
let removal: IOHIDCallback = { context, _, _ in
    guard let context else { return }
    let state = Unmanaged<Connection>.fromOpaque(context).takeUnretainedValue()
    state.alive = false; emit(["event": "removed", "id": state.id])
}
let args = CommandLine.arguments
if args.count == 2 && args[1] == "--inventory" {
    let rows = devices().map(row)
    let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
    FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
} else if args.count >= 3 && args[1] == "--stream" {
    let selected = Set(args.dropFirst(2))
    guard selected.count <= 2 && selected.allSatisfy({ UInt64($0) != nil }) else { exit(2) }
    var active: [Connection] = []
    for device in devices() where selected.contains(registryID(IOHIDDeviceGetService(device))) && permitted(device) {
        let result = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
        guard result == kIOReturnSuccess else { emit(["event": "error", "id": registryID(IOHIDDeviceGetService(device)), "code": result]); continue }
        let connection = Connection(device); active.append(connection)
        let context = Unmanaged.passUnretained(connection).toOpaque()
        IOHIDDeviceRegisterInputReportCallback(device, connection.buffer, connection.capacity, callback, context)
        IOHIDDeviceRegisterRemovalCallback(device, removal, context)
        IOHIDDeviceScheduleWithRunLoop(device, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)
        emit(["event": "opened", "id": connection.id])
        if number(device, kIOHIDVendorIDKey) == 0x0e8f && number(device, kIOHIDProductIDKey) == 0x1224 {
            var feature = [UInt8](repeating: 0, count: 65); feature[0] = 1; var length = feature.count
            let code = IOHIDDeviceGetReport(device, kIOHIDReportTypeFeature, 1, &feature, &length)
            if code == kIOReturnSuccess && length > 0 && length <= feature.count {
                emit(["event": "feature", "id": connection.id, "reportID": 1, "hex": feature.prefix(length).map { String(format: "%02x", $0) }.joined()])
            } else { emit(["event": "error", "id": connection.id, "code": code]) }
        }
    }
    guard active.count == selected.count else { exit(3) }
    // Signal sources perform cleanup on the main run loop.
    signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN)
    let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
    terminate.setEventHandler { CFRunLoopStop(CFRunLoopGetMain()) }; interrupt.setEventHandler { CFRunLoopStop(CFRunLoopGetMain()) }
    terminate.resume(); interrupt.resume()
    let timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
        emit(["event": "heartbeat", "ids": active.filter { $0.alive }.map { $0.id }])
        if getppid() == 1 { CFRunLoopStop(CFRunLoopGetMain()) }
    }
    CFRunLoopRun(); timer.invalidate()
    for state in active {
        IOHIDDeviceUnscheduleFromRunLoop(state.device, CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue)
        IOHIDDeviceClose(state.device, IOOptionBits(kIOHIDOptionsTypeNone))
    }
} else { exit(2) }
