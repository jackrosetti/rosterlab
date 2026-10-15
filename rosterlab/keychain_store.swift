import Foundation
import Security

guard CommandLine.arguments.count == 3 else {
    FileHandle.standardError.write(Data("usage: keychain_store account service\n".utf8))
    exit(64)
}

let account = CommandLine.arguments[1]
let service = CommandLine.arguments[2]
let secret = FileHandle.standardInput.readDataToEndOfFile()

let identity: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrAccount as String: account,
    kSecAttrService as String: service,
]
let update: [String: Any] = [kSecValueData as String: secret]

var status = SecItemUpdate(identity as CFDictionary, update as CFDictionary)
if status == errSecItemNotFound {
    var item = identity
    item[kSecValueData as String] = secret
    status = SecItemAdd(item as CFDictionary, nil)
}

guard status == errSecSuccess else {
    FileHandle.standardError.write(Data("Keychain status \(status)\n".utf8))
    exit(1)
}
