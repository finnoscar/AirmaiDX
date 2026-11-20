"""Compile the sibling Editor's preview stack with macOS platform adapters.

The parser, geometry, note drawing and audio presentation calculations come from
their original source files. Fail on an unexpected upstream structure.
"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]

def project_sources(root=ROOT):
    manifest = json.loads((root/'Tools/editor_preview_sources.json').read_text())
    return [(root/source, name) for source, name in manifest]

def sync(output, sources):
    output.mkdir(parents=True, exist_ok=True)
    for source, name in sources:
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        text = adapt(name, data.decode('utf-8-sig'))
        path = output/name
        generated = f'// Airmai Editor source: {source.name}, SHA256 {digest}\n' + text
        if not path.is_file() or path.read_text() != generated:
            path.write_text(generated)

def sync_project(root=ROOT):
    sources = project_sources(root)
    sync(root/'Generated/EditorPreview', sources)
    return sources


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f'Airmai Editor source changed; review the macOS adapter near {before!r}')
    return text.replace(before, after, 1)


def replace_block(text, start, end, replacement):
    left = text.index(start)
    right = text.index(end, left)
    return text[:left] + replacement + text[right:]


def adapt(name, text):
    if name == 'SimaiChartRenderer.swift':
        text = replace_once(text, 'import UIKit', 'import AppKit')
        return replace_block(text, 'struct SimaiMultiTouchSurface:', 'enum SimaiJudgement:', '')
    if name == 'EditorNativePlayer.swift':
        text = replace_once(text, 'import AVFoundation', 'import AVFoundation\nimport AppKit\nimport QuartzCore')
        display_link = '''        let selector = #selector(updatePlaybackTime(_:))
        guard let displayLink = NSApp.keyWindow?.displayLink(target: self, selector: selector)
            ?? NSScreen.main?.displayLink(target: self, selector: selector) else {
            throw CocoaError(.featureUnsupported)
        }
'''
        if '    private var audioObservers: [NSObjectProtocol] = []\n' in text:
            # Newer Editor isolates retries from player construction. Keep the
            # shared playback clock and retry; remove only iOS session APIs.
            text = replace_once(text, '    private var audioObservers: [NSObjectProtocol] = []\n', '')
            text = replace_once(text, '        let session = AVAudioSession.sharedInstance()\n', '')
            text = replace_block(text, '            if needsAudioPreparation { try configureAudioSession(session) }',
                                 '            // Retry a stale player once', '')
            text = replace_once(text, 'for attempt in 0...1', 'for _ in 0...1')
            text = replace_once(text, '                if attempt == 0 { try session.setActive(true) }\n', '')
            text = replace_block(text, '        for observer in audioObservers', '\n    }\n\n    private func configureAudioSession', '')
            text = replace_block(text, '    private func configureAudioSession', '    private func makePlayer', '')
            text = replace_once(text, '        let audioSession = AVAudioSession.sharedInstance()\n', '')
            text = replace_block(text, '        let notifications = NotificationCenter.default', '        displayLink.preferredFramesPerSecond', display_link)
        else:
            text = replace_once(text, '    private var routeChangeObserver: NSObjectProtocol?\n', '')
            text = replace_block(text, '        if let routeChangeObserver {', '\n    }\n\n    private func configurePlayer', '')
            text = replace_block(text, '        let audioSession = AVAudioSession.sharedInstance()', '        let player = try AVAudioPlayer', '')
            text = replace_block(text, '        routeChangeObserver = NotificationCenter', '        displayLink.preferredFramesPerSecond', display_link)
        text = replace_once(text, 'displayLink.preferredFramesPerSecond = 60',
                            'displayLink.preferredFrameRateRange = CAFrameRateRange(minimum: 60, maximum: 60, preferred: 60)')
        return replace_block(text, '    private func updateAudioPresentationLatency(using session:', '    nonisolated func audioPlayerDidFinishPlaying', '')
    if name == 'EditorPlaybackMedia.swift':
        return replace_once(text, '"EditorPlayback"', '"AirmaiDXEditorPlayback"')
    if name == 'SimaiWriter.swift':
        text = replace_once(text, 'static func write(_ document: EditorDocument) throws -> String {',
                            'static func write(_ document: EditorDocument, tokenOverride: ((EditorNote) -> String?)? = nil) throws -> String {')
        return replace_once(text, 'map {token($0,in:document)}',
                            'map {tokenOverride?($0) ?? token($0,in:document)}')
    if name == 'MaidataFields.swift':
        return 'import Foundation\n\n' + text[text.index('enum MaidataFields {'):]
    return text


def main():
    if sys.argv[1:] == ['--project']:
        sync_project()
        return
    output = Path(sys.argv[1])
    sync(output, [(Path(source), name) for source, name in zip(sys.argv[2::2], sys.argv[3::2])])


if __name__ == '__main__':
    main()
