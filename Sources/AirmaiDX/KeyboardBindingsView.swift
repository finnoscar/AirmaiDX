import SwiftUI
import AirmaiCore

struct KeyboardBindingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.locale) private var locale
    @State private var file: ConfigFile?
    @State private var fileGameID: String?
    @State private var document = SettingsDocument(text: "")
    @State private var dirty = false
    @State private var saving = false
    private struct Control: Identifiable {
        let section: String
        let key: String
        let label: String
        var id: String { section + "." + key }
    }
    private var outer: [Control] {
        (1...8).map { Control(section: "button", key: "1p_btn\($0)", label: L10n.format("外圈第 %lld 键", $0)) }
    }
    private var auxiliary: [Control] {
        [Control(section: "button", key: "1p_btn9", label: "开始 / 选择"),
         Control(section: "io4", key: "coin", label: "投币"),
         Control(section: "io4", key: "test", label: "测试菜单"),
         Control(section: "io4", key: "service", label: "服务键")]
    }
    private let special: [(Int, String)] = [(0,"未分配"),(13,"Return ↩"),(32,"Space"),(37,"←"),(38,"↑"),(39,"→"),(40,"↓"),(27,"Escape"),(9,"Tab")]
    var body: some View {
        Panel(title: "键盘控制", symbol: "keyboard") {
            if file != nil {
                HStack(alignment: .center, spacing: 32) {
                    ZStack {
                        Circle().stroke(AirmaiTheme.accent.opacity(0.25), lineWidth: 12).frame(width: 120, height: 120)
                        ForEach(Array(outer.enumerated()), id: \.offset) { index, control in
                            let angle = (Double(index)*45-67.5)*Double.pi/180
                            Text(label(value(control))).font(.system(.callout, design: .monospaced).bold())
                                .frame(minWidth: 28, minHeight: 25)
                                .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 5))
                                .overlay(RoundedRectangle(cornerRadius: 5).stroke(.secondary.opacity(0.3)))
                                .offset(x: cos(angle)*63, y: sin(angle)*63)
                        }
                        Text("1P").font(.title3.weight(.semibold)).foregroundStyle(.secondary)
                    }.frame(width: 172, height: 172)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("外圈八键的当前键盘映射")
                        .accessibilityValue(outer.map { $0.label + "：" + label(value($0)) }.joined(separator: "，"))
                    VStack(alignment: .leading, spacing: 12) {
                        Text("不接手台，也能使用键盘。").font(.title3.weight(.semibold))
                        Text("点击游戏窗口后操作。外圈第 4 键可用于游客确认，出现确认画面后再按一次。").foregroundStyle(.secondary)
                        Text("当前：\(label(value(auxiliary[1]))) 投币 · \(label(value(outer[3]))) 游客确认 · \(label(value(auxiliary[0]))) 开始")
                            .font(.callout.weight(.medium))
                        Text("数字键使用主键盘；部分 Mac 键盘需配合 Fn 使用 F1 / F2。").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Divider()
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 16) {
                    ForEach(outer + auxiliary) { control in
                        HStack {
                            Text(LocalizedStringKey(control.label)).frame(width: 100, alignment: .leading)
                            keyPicker(control)
                        }
                    }
                }.disabled(model.running || saving)
                if model.running {
                    Text("游戏运行中。停止后可修改键位；当前连接设置会在退出后自动还原。").font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    if duplicateOuter {
                        Label("外圈按键使用了重复键位，请在保存前调整。", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange)
                    }
                    Spacer()
                    Button("保存键位") { Task { await save() } }
                        .airmaiActionStyle(prominent: true).disabled(!dirty || model.running || saving || duplicateOuter || fileGameID != model.game?.id)
                }
            } else {
                ProgressView("正在读取键位…")
            }
        }.task(id: model.game?.id) { await load() }
        .onChange(of: model.running) { _, running in
            if !running && !dirty { Task { await load() } }
        }
    }
    private func keyPicker(_ control: Control) -> some View {
        Picker(LocalizedStringKey(control.label), selection: Binding(get: { value(control) }, set: { code in
            document.set(section: control.section, key: control.key, value: String(format: "0x%02X", code)); dirty = true
        })) {
            Section("常用") { ForEach(special, id: \.0) { Text(LocalizedStringKey($0.1)).tag($0.0) } }
            Section("字母") { ForEach(65...90, id: \.self) { Text(String(UnicodeScalar($0)!)).tag($0) } }
            Section("数字") { ForEach(48...57, id: \.self) { Text(String(UnicodeScalar($0)!)).tag($0) } }
            Section("功能键") { ForEach(112...123, id: \.self) { Text("F\($0-111)").tag($0) } }
            if !known(value(control)) { Text(label(value(control))).tag(value(control)) }
        }.labelsHidden().frame(maxWidth: 180)
    }
    private func known(_ code: Int) -> Bool {
        special.contains { $0.0 == code } || (48...57).contains(code) || (65...90).contains(code) || (112...123).contains(code)
    }
    private func value(_ control: Control) -> Int {
        let raw = document.value(section: control.section, key: control.key).trimmingCharacters(in: .whitespaces)
        return raw.lowercased().hasPrefix("0x") ? Int(raw.dropFirst(2), radix: 16) ?? 0 : Int(raw) ?? 0
    }
    private func label(_ code: Int) -> String {
        if let name = special.first(where: { $0.0 == code })?.1 { return L10n.text(name) }
        if (48...57).contains(code) || (65...90).contains(code) { return String(UnicodeScalar(code)!) }
        if (112...123).contains(code) { return "F\(code-111)" }
        return String(format: "0x%02X", code)
    }
    private var duplicateOuter: Bool {
        let codes = outer.map(value).filter { $0 != 0 }
        return Set(codes).count != codes.count
    }
    private func load() async {
        guard let game = model.game else { return }
        do {
            let data: ConfigFile = try await model.worker.request("readConfig", ["id": game.id, "name": "segatools.ini"])
            guard !Task.isCancelled, model.game?.id == game.id else { return }
            fileGameID = game.id; file = data; document = SettingsDocument(text: data.text); dirty = false
        } catch { model.error = error.localizedDescription }
    }
    private func save() async {
        guard let game = model.game, let file, fileGameID == game.id else { return }
        saving = true; defer { saving = false }
        do {
            let saved: ConfigFile = try await model.worker.request("saveConfig", ["id": game.id, "name": file.name, "text": document.text, "sha256": file.sha256, "encoding": file.encoding])
            guard model.game?.id == game.id else { return }
            self.file = saved; dirty = false; model.notice = "键位已保存，恢复点已创建。"
        } catch { model.error = error.localizedDescription }
    }
}
