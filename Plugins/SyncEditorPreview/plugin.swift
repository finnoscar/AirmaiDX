import PackagePlugin
import Foundation

@main struct SyncEditorPreview: BuildToolPlugin {
    func createBuildCommands(context: PluginContext, target: Target) throws -> [Command] {
        let package = context.package.directoryURL
        let workspace = package
        let script = package.appendingPathComponent("Tools/sync_editor_preview.py")
        let output = context.pluginWorkDirectoryURL
        let manifest = package.appendingPathComponent("Tools/editor_preview_sources.json")
        let entries = try JSONDecoder().decode([[String]].self, from: Data(contentsOf: manifest))
        let sources = entries.map { ($0[0], $0[1]) }
        return [.buildCommand(
            displayName: "Sync Airmai Editor preview sources",
            executable: URL(fileURLWithPath: "/usr/bin/python3"),
            arguments: [script.path, output.path] + sources.flatMap { [workspace.appendingPathComponent($0.0).path, $0.1] },
            inputFiles: [script, manifest] + sources.map { workspace.appendingPathComponent($0.0) },
            outputFiles: sources.map { output.appendingPathComponent($0.1) }
        )]
    }
}
