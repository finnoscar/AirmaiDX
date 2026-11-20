// Airmai Editor source: EditorPlaybackMedia.swift, SHA256 d5935a2f10739e361d1d87395f3066eb633636d586b2d93efccbb47d469f78d4
import AVFoundation

// A local file is the only adapter needed by AirmaiDX's AVAudioPlayer clock.
// Empty sheets use a silent PCM file through the same clock, never a second timer.
actor EditorPlaybackMedia {
    private var mediaID: UUID?
    private var media: (URL, Double)?
    private var silent: (URL, Double)?
    private let directory = FileManager.default.temporaryDirectory.appendingPathComponent("AirmaiDXEditorPlayback", isDirectory: true)

    func prepare(id: UUID, data: Data?, name: String?, duration: Double) throws -> (URL, Double) {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if let data {
            if mediaID == id, let media { return media }
            let ext = (name ?? "audio").split(separator: ".").last.map(String.init) ?? "audio"
            let url = directory.appendingPathComponent(id.uuidString).appendingPathExtension(ext)
            try data.write(to: url, options: .atomic)
            let audio = try AVAudioPlayer(contentsOf: url)
            mediaID = id; media = (url, audio.duration)
            return (url, audio.duration)
        }
        if let silent, silent.1 >= duration { return silent }
        let seconds = max(30, ceil(duration / 30) * 30)
        let sampleRate: UInt32 = 8_000
        let byteCount = UInt32(min(seconds * Double(sampleRate) * 2, Double(UInt32.max - 44)))
        var header = Data()
        func ascii(_ value: String) { header.append(contentsOf: value.utf8) }
        func u16(_ value: UInt16) { var v = value.littleEndian; withUnsafeBytes(of: &v) { header.append(contentsOf: $0) } }
        func u32(_ value: UInt32) { var v = value.littleEndian; withUnsafeBytes(of: &v) { header.append(contentsOf: $0) } }
        ascii("RIFF"); u32(36 + byteCount); ascii("WAVEfmt "); u32(16)
        u16(1); u16(1); u32(sampleRate); u32(sampleRate * 2); u16(2); u16(16)
        ascii("data"); u32(byteCount)
        let url = directory.appendingPathComponent("silence-\(byteCount).wav")
        FileManager.default.createFile(atPath: url.path, contents: header)
        let file = try FileHandle(forWritingTo: url)
        defer { try? file.close() }
        try file.seekToEnd()
        // Extending a sparse file avoids allocating a long silent song on the main thread.
        try file.truncate(atOffset: UInt64(44) + UInt64(byteCount))
        silent = (url, Double(byteCount) / Double(sampleRate * 2))
        return silent!
    }
}
