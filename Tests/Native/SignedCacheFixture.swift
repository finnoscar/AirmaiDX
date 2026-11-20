import Foundation
import CryptoKit
let folder=URL(fileURLWithPath: CommandLine.arguments[1])
let key=P521.Signing.PrivateKey()
let payload=Data("MZ self-authored signed cache fixture".utf8)
let signature=try key.signature(for: SHA256.hash(data: payload)).rawRepresentation
var cache=payload+Data([1])+signature+Data("AquaMaiSig".utf8)+Data([1])
try cache.write(to: folder.appendingPathComponent("valid.cache"))
print(key.publicKey.derRepresentation.base64EncodedString())
