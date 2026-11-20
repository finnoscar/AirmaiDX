import Foundation
import Darwin

final class Publisher: NSObject, NetServiceDelegate {
    func netServiceDidPublish(_ sender: NetService) { print("ready"); fflush(stdout) }
    func netService(_ sender: NetService, didNotPublish errorDict: [String:NSNumber]) { exit(3) }
}
guard CommandLine.arguments.count == 3,
      let port = Int32(CommandLine.arguments[1]), port > 1023,
      CommandLine.arguments[2].count == 64 else { exit(2) }
let publisher = Publisher()
let service = NetService(domain: "local.", type: "_airmai-card._tcp.",
    name: Host.current().localizedName ?? "AirmaiDX", port: port)
service.delegate = publisher
service.setTXTRecord(NetService.data(fromTXTRecord: ["v":Data("1".utf8), "fp":Data(CommandLine.arguments[2].utf8)]))
service.publish()
RunLoop.main.run()
