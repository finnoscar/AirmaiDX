import SwiftUI
import Foundation

struct PhoneReaderStatus: Decodable {
    struct Client: Decodable, Identifiable { let id: String; let name: String }
    let enabled: Bool
    let code: String?
    let expiresAt: Double
    let clients: [Client]
    let readerReady: Bool
}

struct PhoneReaderView: View {
    @EnvironmentObject private var model: AppModel
    @State private var status: PhoneReaderStatus?
    @State private var working = false
    @State private var message: String?
    @State private var removing: PhoneReaderStatus.Client?
    @State private var stopping = false
    var body: some View {
        PageLayout(title: "iPhone 读卡器", subtitle: "") {
            Panel(title: "配对", symbol: "link") {
                HStack {
                    if let status {
                        Label(status.enabled ? "连接已开启" : "连接未开启", systemImage: status.enabled ? "network" : "network.slash")
                    } else { ProgressView().controlSize(.small); Text("正在读取连接状态") }
                    Spacer()
                    Button(status?.code == nil ? "生成配对码" : "刷新配对码") { action("phonePair") }.airmaiActionStyle(prominent: true).disabled(working)
                }
                if let status, let code = status.code {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let seconds = max(0, Int(status.expiresAt-context.date.timeIntervalSince1970))
                        VStack(alignment: .leading, spacing: 10) {
                            Text(seconds > 0 ? code : "已过期").font(.system(size: 30, weight: .medium, design: .monospaced))
                                .tracking(5).foregroundStyle(AirmaiTheme.accent).textSelection(.enabled)
                            Text("在手机的 Mac 页面选择这台电脑，输入以上数字。\(seconds) 秒后过期，仅可使用一次。")
                                .font(.caption).foregroundStyle(.secondary)
                        }.padding(.vertical, 8)
                    }
                } else {
                    Text("打开 Airmai Card 的 Mac 页面，使用 6 位数字配对。两台设备需连接同一网络。")
                        .foregroundStyle(.secondary)
                }
                if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
            }
            Panel(title: "已配对的设备", symbol: "iphone") {
                if let status {
                    if status.clients.isEmpty { Text("暂无已配对设备").foregroundStyle(.secondary) }
                    ForEach(status.clients) { client in
                        HStack {
                            Label(client.name, systemImage: "iphone")
                            Spacer()
                            Button("取消配对") { removing = client }.airmaiActionStyle().disabled(working)
                        }.padding(.vertical, 4)
                    }
                    if status.enabled {
                        Divider()
                        Button("关闭连接并取消所有配对", role: .destructive) { stopping = true }
                            .airmaiActionStyle().foregroundStyle(.red).disabled(working)
                    }
                }
            }
            Panel(title: "游戏读卡", symbol: "creditcard") {
                if let game = model.game {
                    Text(game.name).font(.headline)
                    Toggle("使用 iPhone 读卡", isOn: Binding(get: {
                        model.game?.settings.phoneReaderEnabled ?? false
                    }, set: { enabled in
                        var settings = game.settings; settings.phoneReaderEnabled = enabled
                        model.perform { try await model.saveSettings(settings) }
                    })).disabled(model.busy || working)
                    Text("下次启动游戏时生效。手台按键、触摸和灯光继续使用原来的连接。")
                        .font(.caption).foregroundStyle(.secondary)
                    if let status {
                        Label(status.readerReady ? "游戏读卡接口已就绪" : "等待游戏启用读卡接口", systemImage: status.readerReady ? "checkmark.circle" : "clock")
                            .foregroundStyle(.secondary)
                    }
                } else { Text("导入游戏后，可在这里启用 iPhone 读卡。").foregroundStyle(.secondary) }
            }
        }.confirmationDialog("取消这台设备的配对？", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), presenting: removing) { client in
            Button("取消配对", role: .destructive) { action("phoneForget", ["clientID": client.id]); removing = nil }
            Button("保留配对", role: .cancel) { removing = nil }
        } message: { client in Text("\(client.name) 需要重新输入配对码才能读卡。") }
        .confirmationDialog("关闭连接并取消所有配对？", isPresented: $stopping) {
            Button("关闭并取消配对", role: .destructive) { action("phoneStop") }
            Button("保留连接", role: .cancel) {}
        }
        .task {
            while !Task.isCancelled {
                if !working {
                    do { status = try await model.worker.request("phoneStatus") }
                    catch { message = error.localizedDescription }
                }
                do { try await Task.sleep(for: .seconds(2)) } catch { break }
            }
        }
    }
    private func action(_ operation: String, _ payload: [String: Any] = [:]) {
        working = true; message = nil
        Task {
            defer { working = false }
            do { status = try await model.worker.request(operation, payload.merging(["parentPID": ProcessInfo.processInfo.processIdentifier]) { a,_ in a }) }
            catch { message = error.localizedDescription }
        }
    }
}
