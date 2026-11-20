import Foundation

do {
    guard CommandLine.arguments.count == 2 else { throw CocoaError(.fileReadInvalidFileName) }
    let source = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL
    let values = try source.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
    guard values.isDirectory == true, values.isSymbolicLink != true,
          source.deletingLastPathComponent().lastPathComponent == "Games",
          source.lastPathComponent.range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else {
        throw CocoaError(.fileWriteInvalidFileName)
    }
    var destination: NSURL?
    try FileManager.default.trashItem(at: source, resultingItemURL: &destination)
    guard let destination else { throw CocoaError(.fileWriteUnknown) }
    let result = try JSONSerialization.data(withJSONObject: ["path": destination.path!])
    print(String(decoding: result, as: UTF8.self))
} catch {
    fputs("Could not move game data to Trash: \(error.localizedDescription)\n", stderr)
    exit(1)
}
