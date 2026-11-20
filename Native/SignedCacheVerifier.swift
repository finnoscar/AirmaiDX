// Verify user-supplied MuMod caches using CryptoKit, outside Wine's CNG layer.
// Packed block layout verified from user-supplied MuMod e80baeba...cd86;
// publisher public keys match MuNET-OSS/AquaMai. No game data is bundled.
import Foundation
import CryptoKit

let publisherKeys = [
    "MIGbMBAGByqGSM49AgEGBSuBBAAjA4GGAAQBVoScU915wnWeDOvLsQd3uWh9NwclPhup8TT+cqiV3SB683JgQTpLYv2XRCGfH/3zIwTU2KDIXwNPsDPlOpH0QIkB0aVIDo9g6mus7cTMphq/7yjQQEPnsBQO5KbtcNxcy7mSnhykSea2Gv+iOKu1C4FOaO39zNe0HULVoqMrcCNLRkg=",
    "MIGbMBAGByqGSM49AgEGBSuBBAAjA4GGAAQAvi9gtqbPF0g7K52lumBRiztMb5lVKbTwhzwVSVsMBUo5wXp9w86CnIh3/VErXtyneP1BBMLFDEtd4Cb11eQmxBMBuPjY61oca4gZhIxgQ8e0ki/pUhtUQwIQ48AN/gba/lq0GWBaPrwEyhSvHArHsPo2WxFczdsOO0mTgwq0bAw/tTw="
]

do {
    guard CommandLine.arguments.count == 2 else { throw CocoaError(.fileReadInvalidFileName) }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
    guard size > 22, size <= 128 * 1024 * 1024 else { throw CocoaError(.fileReadCorruptFile) }
    let bytes = try Data(contentsOf: url)
    guard bytes.count == size else {
        throw CocoaError(.fileReadCorruptFile)
    }
    guard bytes.count > 144, bytes.suffix(11) == Data("AquaMaiSig".utf8) + Data([1]) else {
        throw CocoaError(.fileReadCorruptFile)
    }
    // Packed v2 block: key id, 132-byte P1363 signature, magic, version.
    let payloadLength = bytes.count - 144
    let keyID = Int(bytes[payloadLength])
    guard keyID == 1 || keyID == 2 else { throw CocoaError(.fileReadCorruptFile) }
    let raw = bytes[(payloadLength + 1)..<(payloadLength + 133)]
    let payload = bytes.prefix(payloadLength)
    guard payload.starts(with: [0x4d, 0x5a]), raw.count == 132 else {
        throw CocoaError(.fileReadCorruptFile)
    }
    let signature = try P521.Signing.ECDSASignature(rawRepresentation: raw)
    let hash = SHA256.hash(data: payload)
    let key = try P521.Signing.PublicKey(derRepresentation: Data(base64Encoded: publisherKeys[keyID - 1])!)
    guard key.isValidSignature(signature, for: hash) else { throw CocoaError(.fileReadCorruptFile) }
    let result: [String: Any] = [
        "verified": true, "payloadLength": payloadLength,
        "sha256": hash.map { String(format: "%02x", $0) }.joined(),
        "cacheSHA256": SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
    ]
    print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
} catch {
    fputs("Signed cache verification failed.\n", stderr)
    exit(1)
}
