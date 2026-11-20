import SwiftUI
import AirmaiCore

struct ModSettingsList: View {
    @Environment(\.locale) private var locale
    @Binding var document: SettingsDocument
    @Binding var dirty: Bool
    let search: String
    @State private var filter = "all"
    private let catalog = ModCatalog.shared
    private var language: AppLanguage { AppLanguage(rawValue: locale.identifier) ?? AppLanguage.current }
    private var sections: [SettingsDocument.Section] {
        document.sections.filter {
            (filter == "all" || (filter == "on") == catalog.isEnabled($0)) && catalog.matches($0, query: search)
        }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Picker("显示模组", selection: $filter) {
                    Text("全部").tag("all")
                    Text("已启用").tag("on")
                    Text("已关闭").tag("off")
                }.pickerStyle(.segmented).frame(maxWidth: 330)
                Spacer()
                Text("\(sections.count) 个分组").font(.caption).foregroundStyle(.secondary)
            }
            Text("关闭“自定义”会让 AquaMai 使用该版本的默认值。界面语言与模组语言分别设置。")
                .font(.caption).foregroundStyle(.secondary)
            if sections.isEmpty {
                ContentUnavailableView.search(text: search)
            }
            ForEach(sections) { section in
                DisclosureGroup {
                    VStack(alignment: .leading, spacing: 12) {
                        if !catalog.isEnabled(section) {
                            Label("启用此模组后可编辑选项。", systemImage: "info.circle")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(section.entries.filter { $0.key != "Disabled" }) { entry in
                            entryRow(entry, section: section)
                            if entry.id != section.entries.last(where: { $0.key != "Disabled" })?.id { Divider() }
                        }
                        if !section.help.isEmpty {
                            DisclosureGroup("配置文件中的原始说明") {
                                Text(verbatim: section.help).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            }.font(.caption)
                        }
                    }.padding(.top, 10)
                } label: {
                    HStack(alignment: .top, spacing: 18) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text(catalog.title(section, language: language)).font(.headline)
                            if !section.name.isEmpty {
                                Text(verbatim: section.name).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                            }
                            Text(catalog.help(section, language: language)).font(.callout)
                                .foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        if catalog.isAlwaysEnabled(section) {
                            Text("始终启用").font(.caption).foregroundStyle(.secondary)
                        } else {
                            Toggle(catalog.title(section, language: language), isOn: Binding(
                                get: { catalog.isEnabled(section) },
                                set: { document.setSectionEnabled(section, enabled: $0); dirty = true }
                            )).labelsHidden().toggleStyle(.switch).controlSize(.small)
                        }
                    }
                }.padding(.vertical, 10)
                Divider()
            }
        }
    }
    private func entryRow(_ entry: SettingsDocument.Entry, section: SettingsDocument.Section) -> some View {
        let title = catalog.title(entry, language: language)
        let help = catalog.help(entry, language: language)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).textSelection(.enabled)
                    Text(verbatim: entry.key).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                }.frame(maxWidth: .infinity, alignment: .leading)
                Group {
                    if entry.section == "General" && entry.key == "Locale" {
                        Picker(title, selection: Binding(get: { entry.displayValue }, set: { value in
                            document.set(entry, value: "\"\(value)\"", active: !entry.commented); dirty = true
                        })) {
                            Text("跟随游戏系统").tag("")
                            Text(verbatim: "简体中文").tag("zh")
                            Text(verbatim: "English").tag("en")
                            if !["", "zh", "en"].contains(entry.displayValue) {
                                Text(verbatim: entry.displayValue).tag(entry.displayValue)
                            }
                        }.labelsHidden()
                    } else if entry.isBoolean {
                        Toggle(title, isOn: Binding(get: { entry.boolValue }, set: { value in
                            document.set(entry, value: value ? "true" : "false", active: !entry.commented); dirty = true
                        })).labelsHidden().toggleStyle(.switch).controlSize(.small)
                    } else {
                        TextField(title, text: Binding(get: { entry.value }, set: { value in
                            document.set(entry, value: value, active: !entry.commented); dirty = true
                        })).textFieldStyle(.roundedBorder)
                    }
                }.frame(width: 210, alignment: .trailing).disabled(entry.commented)
                Toggle("自定义", isOn: Binding(get: { !entry.commented }, set: { custom in
                    document.set(entry, value: entry.value, active: custom); dirty = true
                })).toggleStyle(.checkbox).help("关闭后使用该版本的模组默认值。")
                    .accessibilityLabel(L10n.format("自定义 %@", title, language: language))
            }.disabled(!catalog.isEnabled(section))
            if !help.isEmpty {
                Text(help).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if !entry.help.isEmpty && entry.help != help {
                DisclosureGroup("配置文件中的原始说明") {
                    Text(verbatim: entry.help).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                }.font(.caption)
            }
        }
    }
}
