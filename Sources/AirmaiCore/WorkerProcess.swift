import Foundation
import Darwin

public struct WorkerProcessResult {
    public let status: Int32
    public let errorTail: String
}

/// Drain both pipes while sending input. A worker writing diagnostics must not
/// deadlock the app, and a stalled worker must release the calling operation.
public enum WorkerProcess {
    public static func run(executable: URL, arguments: [String], input: Data,
                           environment: [String: String], timeout: TimeInterval,
                           onLine: (Data) throws -> Void) throws -> WorkerProcessResult {
        let process = Process(), stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
        process.executableURL = executable; process.arguments = arguments
        process.environment = environment
        process.standardInput = stdin; process.standardOutput = stdout; process.standardError = stderr
        try process.run()
        let inputFD = stdin.fileHandleForWriting.fileDescriptor
        let outputFD = stdout.fileHandleForReading.fileDescriptor
        let errorFD = stderr.fileHandleForReading.fileDescriptor
        for fd in [inputFD, outputFD, errorFD] { _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK) }
        var inputOpen = true, outputOpen = true, errorOpen = true
        defer {
            if inputOpen { try? stdin.fileHandleForWriting.close() }
            try? stdout.fileHandleForReading.close(); try? stderr.fileHandleForReading.close()
            if process.isRunning { process.terminate(); kill(process.processIdentifier, SIGKILL) }
            process.waitUntilExit()
        }
        var position = 0, pending = Data(), errors = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        var exitedAt: TimeInterval?
        while process.isRunning || outputOpen || errorOpen {
            let now = ProcessInfo.processInfo.systemUptime
            if now >= deadline {
                throw AirmaiError.message("后台任务等待超时，已停止本次操作。请查看诊断记录后重试。")
            }
            if !process.isRunning {
                if exitedAt == nil { exitedAt = now }
                // Do not wait indefinitely for a stray descendant that inherited
                // a pipe. Continue draining buffered bytes for a short interval.
                if now - (exitedAt ?? now) > 1 { break }
            }
            var descriptors = [pollfd(fd: inputOpen ? inputFD : -1, events: Int16(POLLOUT), revents: 0),
                               pollfd(fd: outputOpen ? outputFD : -1, events: Int16(POLLIN), revents: 0),
                               pollfd(fd: errorOpen ? errorFD : -1, events: Int16(POLLIN), revents: 0)]
            let polled = poll(&descriptors, nfds_t(descriptors.count), 100)
            if polled < 0 {
                if errno == EINTR { continue }
                throw AirmaiError.message("后台通信中断，请查看诊断记录后重试。")
            }
            if inputOpen {
                if position == input.count || descriptors[0].revents & Int16(POLLERR | POLLHUP) != 0 {
                    try stdin.fileHandleForWriting.close(); inputOpen = false
                } else if descriptors[0].revents & Int16(POLLOUT) != 0 {
                    // macOS F_SETNOSIGPIPE prevents a disappearing worker from
                    // terminating the GUI when its stdin closes early.
                    _ = fcntl(inputFD, F_SETNOSIGPIPE, 1)
                    let written = input.withUnsafeBytes { raw in
                        Darwin.write(inputFD, raw.baseAddress!.advanced(by: position), min(65536, input.count - position))
                    }
                    if written > 0 { position += written }
                    else if written < 0 && errno != EAGAIN && errno != EINTR {
                        try stdin.fileHandleForWriting.close(); inputOpen = false
                    }
                }
            }
            for index in [1, 2] where descriptors[index].fd >= 0 && descriptors[index].revents != 0 {
                let count = Darwin.read(descriptors[index].fd, &buffer, buffer.count)
                if count == 0 {
                    if index == 1 { outputOpen = false } else { errorOpen = false }
                } else if count > 0 {
                    if index == 2 {
                        errors.append(contentsOf: buffer.prefix(count))
                        if errors.count > 16384 { errors.removeFirst(errors.count - 16384) }
                    } else {
                        pending.append(contentsOf: buffer.prefix(count))
                        while let newline = pending.firstIndex(of: 10) {
                            try onLine(Data(pending[..<newline])); pending.removeSubrange(...newline)
                        }
                        if pending.count > 8 * 1024 * 1024 { throw AirmaiError.message("后台返回的数据超出预期大小。") }
                    }
                } else if errno != EAGAIN && errno != EINTR {
                    if index == 1 { outputOpen = false } else { errorOpen = false }
                }
            }
        }
        if !pending.isEmpty { try onLine(pending) }
        process.waitUntilExit()
        return WorkerProcessResult(status: process.terminationStatus, errorTail: String(decoding: errors, as: UTF8.self))
    }
}
