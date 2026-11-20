import XCTest
import Foundation
@testable import AirmaiCore

final class WorkerProcessTests: XCTestCase {
    func testLargeStderrAndInputCannotDeadlockEachOther() throws {
        var lines: [String] = []
        let result = try WorkerProcess.run(executable: URL(fileURLWithPath: "/bin/sh"),
            arguments: ["-c", "/usr/bin/head -c 2097152 /dev/zero >&2; /bin/cat >/dev/null; printf 'complete\\n'"],
            input: Data(repeating: 65, count: 2 * 1024 * 1024), environment: [:], timeout: 10) {
                lines.append(String(decoding: $0, as: UTF8.self))
            }
        XCTAssertEqual(result.status, 0)
        XCTAssertEqual(lines, ["complete"])
        XCTAssertLessThanOrEqual(result.errorTail.utf8.count, 16384)
    }

    func testStalledWorkerTimesOut() {
        let start = ProcessInfo.processInfo.systemUptime
        XCTAssertThrowsError(try WorkerProcess.run(executable: URL(fileURLWithPath: "/bin/sh"),
            arguments: ["-c", "while :; do :; done"], input: Data(), environment: [:], timeout: 0.2) { _ in })
        XCTAssertLessThan(ProcessInfo.processInfo.systemUptime - start, 3)
    }

    func testEarlyExitWhileSendingInputDoesNotSignalTheApp() throws {
        let result = try WorkerProcess.run(executable: URL(fileURLWithPath: "/usr/bin/true"),
            arguments: [], input: Data(repeating: 65, count: 1024 * 1024), environment: [:], timeout: 3) { _ in }
        XCTAssertEqual(result.status, 0)
    }
}
