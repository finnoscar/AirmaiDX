import SwiftUI
import AirmaiCore

struct ControllerDevicesView: View {
    @EnvironmentObject var model: AppModel
    var body: some View {
        Panel(title: "ADX 与其他手台", symbol: "gamecontroller") {
            HStack {
                Text("按输入协议识别设备，各通道分别验证。").foregroundStyle(.secondary)
                Spacer()
                Button { Task { await model.refreshControllers() } } label: {
                    Label("刷新设备", systemImage: "arrow.clockwise")
                }.airmaiActionStyle().disabled(model.scanningControllers)
            }
            if let game = model.game {
                Toggle("自动连接已匹配的 ADX HID 输入", isOn: Binding(get: {
                    model.game?.settings.adxEnabled ?? true
                }, set: { value in
                    var settings = game.settings; settings.adxEnabled = value
                    model.perform { try await model.saveSettings(settings) }
                })).disabled(model.busy)
            }
            if model.scanningControllers { ProgressView().controlSize(.small).accessibilityLabel(Text("正在读取设备信息")) }
            if let inventory = model.controllerInventory {
                if inventory.devices.isEmpty {
                    Label("未检测到已知手台", systemImage: "cable.connector.slash").foregroundStyle(.secondary).padding(.vertical, 8)
                }
                ForEach(inventory.devices) { device in
                    Divider()
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: device.status == "keyboard" ? "keyboard" : "gamecontroller")
                            .foregroundStyle(AirmaiTheme.accent).frame(width: 24)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(device.name).font(.headline)
                            Text(device.identity + " · " + profile(device.profile) + (device.player.map { " · \($0 + 1)P" } ?? ""))
                                .font(.caption.monospaced()).foregroundStyle(.secondary)
                            Text(L10n.text(device.detail)).font(.callout).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(L10n.text(device.status == "verifiedProfile" ? "已验证预设" : device.status == "candidate" ? "待实机验证" : device.status == "keyboard" ? "系统键盘" : "尚未接入"))
                            .font(.caption).foregroundStyle(device.status == "verifiedProfile" ? .green : .secondary)
                    }.padding(.vertical, 6)
                }
                ForEach(inventory.errors, id: \.self) { message in
                    Text(L10n.text(message)).font(.caption).foregroundStyle(.secondary)
                }
            }
            if let message = model.session?.controllerMessage {
                Text(L10n.text(message)).font(.caption).foregroundStyle(.secondary)
            }
            if let error = model.controllerError { Text(error).font(.caption).foregroundStyle(.secondary) }
            if model.running, model.session?.inputMode == "adx" {
                Divider()
                Label(model.session?.controllerInput == true ? "原生服务已收到输入" : "等待手台输入", systemImage: "waveform")
                    .foregroundStyle(.secondary)
                Text("此状态表示本机输入通道；游戏内按键与判定仍需实际验证。").font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 8) {
                GridRow { Text("协议").fontWeight(.medium); Text("本次接入范围").fontWeight(.medium) }
                GridRow { Text("ADX HID"); Text("外圈键与功能键") }
                GridRow { Text("NPro HID / Maimoller"); Text("外圈键、功能键与触摸") }
                GridRow { Text("WinUSB / 串口 / LED / Aime"); Text("ADX 通道尚未接入") }
            }.font(.callout)
            Text("ADX 输入适配尚未通过实机验收，不能保证全部型号和固件可用。未匹配接口会保留系统键盘输入。")
                .font(.caption).foregroundStyle(.secondary)
        }.task { await model.refreshControllers() }
    }
    private func profile(_ value: String) -> String {
        switch value {
        case "adx-hid": return "ADX HID"
        case "adx-keyboard": return "ADX Keyboard"
        case "npro-hid": return "NPro HID"
        case "maimoller-hid": return "Maimoller HID"
        case "hdx": return "HDX 02"
        default: return value
        }
    }
}
