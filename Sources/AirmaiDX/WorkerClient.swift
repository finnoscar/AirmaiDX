import Foundation
import AirmaiCore

final class WorkerClient: @unchecked Sendable {
    let root: URL
    let executable: URL
    let runtime: URL
    init() {
        let bundle = Bundle.main.bundleURL
        root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("AirmaiDX")
        executable = bundle.appendingPathComponent("Contents/Resources/Service/AirmaiDXService")
        runtime = bundle.appendingPathComponent("Contents/Resources/Runtime")
    }
    func request<T: Decodable>(_ operation: String, _ payload: [String: Any] = [:], progress: (@MainActor (String, Double?) -> Void)? = nil) async throws -> T {
        let request = try JSONSerialization.data(withJSONObject: payload)
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                var errorDetails = ""
                do {
                    var environment = ProcessInfo.processInfo.environment
                    environment["PYTHONNOUSERSITE"] = "1"
                    var result: Data?, failure: String?, guide: LaunchGuideIssue?
                    let timeout: TimeInterval = operation == "import" ? 3600 : operation == "delete" ? 180 :
                        operation == "installRuntime" ? 2400 :
                        ["prepare", "start"].contains(operation) ? 900 : operation == "status" ? 12 : 90
                    let completed = try WorkerProcess.run(executable: self.executable,
                        arguments: [operation, "--root", self.root.path, "--runtime", self.runtime.path],
                        input: request, environment: environment, timeout: timeout) { line in
                        guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { return }
                        if object["event"] as? String == "result", let body = object["data"] {
                            result = try JSONSerialization.data(withJSONObject: body, options: [.fragmentsAllowed])
                        } else if object["event"] as? String == "error" {
                            failure = object["message"] as? String
                            if let body = object["guide"], let data = try? JSONSerialization.data(withJSONObject: body) {
                                guide = try? JSONDecoder().decode(LaunchGuideIssue.self, from: data)
                            }
                        } else if object["event"] as? String == "progress", let body = object["data"] as? [String: Any] {
                            let message = body["message"] as? String ?? "正在处理"
                            let fraction = body["fraction"] as? Double
                            DispatchQueue.main.async { progress?(message, fraction) }
                        }
                    }
                    errorDetails = completed.errorTail
                    if let guide { throw guide }
                    if let failure { throw AirmaiError.message(failure) }
                    guard completed.status == 0, let result else {
                        throw AirmaiError.message("后台任务未完成。请在诊断页查看本次记录。")
                    }
                    continuation.resume(returning: try JSONDecoder().decode(T.self, from: result))
                } catch {
                    if error is LaunchGuideIssue {
                        continuation.resume(throwing: error)
                        return
                    }
                    let log = self.root.appendingPathComponent("last-worker-error.log")
                    try? FileManager.default.createDirectory(at: self.root, withIntermediateDirectories: true,
                                                             attributes: [.posixPermissions: 0o700])
                    try? (operation + ": " + error.localizedDescription + "\n" + errorDetails).write(to: log, atomically: true, encoding: .utf8)
                    try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: log.path)
                    continuation.resume(throwing: error)
                }
            }
        }
    }
    static func dictionary<T: Encodable>(_ value: T) throws -> [String: Any] {
        guard let result = try JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any] else {
            throw AirmaiError.message("设置格式不正确。")
        }
        return result
    }
}
