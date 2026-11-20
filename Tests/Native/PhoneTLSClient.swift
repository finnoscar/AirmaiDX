import Foundation
struct MacPeer { let name: String; let host: String; let port: Int; let certificateSHA256: String }
@main struct PhoneTLSClient {
    static func main() async {
        guard CommandLine.arguments.count == 4, let port = Int(CommandLine.arguments[1]) else { exit(2) }
        let peer = MacPeer(name: "Isolated test", host: "127.0.0.1", port: port, certificateSHA256: CommandLine.arguments[2])
        do {
            let value = try await MacConnection.pair(peer, code: "001234", deviceName: "Isolated Apple URLSession test")
            guard value.token.count == 64 else { exit(3) }
            print("Apple URLSession numeric pairing passed")
        } catch {
            // Types/codes only. Never write token, code, certificate, card or URLs.
            let value = error as NSError
            print("Apple URLSession rejected: \(value.domain) \(value.code)")
            exit(1)
        }
    }
}
