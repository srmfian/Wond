import Foundation

enum ZipWriter {
    enum ZipError: Error {
        case entryTooLarge
    }

    struct Entry {
        var path: String
        var crc: UInt32
        var size: UInt32
        var offset: UInt32
        var date: Date
    }

    static func write(entries: [(source: URL, path: String)], to destination: URL) throws {
        FileManager.default.createFile(atPath: destination.path, contents: nil)
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }

        var centralDirectory: [Entry] = []
        var offset: UInt32 = 0

        for item in entries {
            let data = try Data(contentsOf: item.source)
            let name = normalizedPath(item.path)
            let nameData = Data(name.utf8)
            guard data.count <= UInt32.max, nameData.count <= UInt16.max else {
                throw ZipError.entryTooLarge
            }

            let crc = CRC32.checksum(data)
            let size = UInt32(data.count)
            let entryOffset = offset

            var local = Data()
            local.appendUInt32(0x04034b50)
            local.appendUInt16(20)
            local.appendUInt16(0)
            local.appendUInt16(0)
            local.appendUInt16(dosTime(for: Date()))
            local.appendUInt16(dosDate(for: Date()))
            local.appendUInt32(crc)
            local.appendUInt32(size)
            local.appendUInt32(size)
            local.appendUInt16(UInt16(nameData.count))
            local.appendUInt16(0)
            local.append(nameData)

            try handle.write(contentsOf: local)
            try handle.write(contentsOf: data)

            offset += UInt32(local.count) + size
            centralDirectory.append(
                Entry(path: name, crc: crc, size: size, offset: entryOffset, date: Date())
            )
        }

        let centralStart = offset
        for entry in centralDirectory {
            let nameData = Data(entry.path.utf8)
            var central = Data()
            central.appendUInt32(0x02014b50)
            central.appendUInt16(20)
            central.appendUInt16(20)
            central.appendUInt16(0)
            central.appendUInt16(0)
            central.appendUInt16(dosTime(for: entry.date))
            central.appendUInt16(dosDate(for: entry.date))
            central.appendUInt32(entry.crc)
            central.appendUInt32(entry.size)
            central.appendUInt32(entry.size)
            central.appendUInt16(UInt16(nameData.count))
            central.appendUInt16(0)
            central.appendUInt16(0)
            central.appendUInt16(0)
            central.appendUInt16(0)
            central.appendUInt32(0)
            central.appendUInt32(entry.offset)
            central.append(nameData)

            try handle.write(contentsOf: central)
            offset += UInt32(central.count)
        }

        let centralSize = offset - centralStart
        var end = Data()
        end.appendUInt32(0x06054b50)
        end.appendUInt16(0)
        end.appendUInt16(0)
        end.appendUInt16(UInt16(centralDirectory.count))
        end.appendUInt16(UInt16(centralDirectory.count))
        end.appendUInt32(centralSize)
        end.appendUInt32(centralStart)
        end.appendUInt16(0)
        try handle.write(contentsOf: end)
    }

    private static func normalizedPath(_ path: String) -> String {
        path
            .replacingOccurrences(of: "\\", with: "/")
            .split(separator: "/", omittingEmptySubsequences: true)
            .joined(separator: "/")
    }

    private static func dosTime(for date: Date) -> UInt16 {
        let components = Calendar.current.dateComponents([.hour, .minute, .second], from: date)
        let hour = UInt16(components.hour ?? 0)
        let minute = UInt16(components.minute ?? 0)
        let second = UInt16((components.second ?? 0) / 2)
        return (hour << 11) | (minute << 5) | second
    }

    private static func dosDate(for date: Date) -> UInt16 {
        let components = Calendar.current.dateComponents([.year, .month, .day], from: date)
        let year = UInt16(max(1980, components.year ?? 1980) - 1980)
        let month = UInt16(components.month ?? 1)
        let day = UInt16(components.day ?? 1)
        return (year << 9) | (month << 5) | day
    }
}

private enum CRC32 {
    static func checksum(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xffffffff
        for byte in data {
            let index = Int((crc ^ UInt32(byte)) & 0xff)
            crc = table[index] ^ (crc >> 8)
        }
        return crc ^ 0xffffffff
    }

    private static let table: [UInt32] = (0..<256).map { value in
        var crc = UInt32(value)
        for _ in 0..<8 {
            if crc & 1 == 1 {
                crc = 0xedb88320 ^ (crc >> 1)
            } else {
                crc >>= 1
            }
        }
        return crc
    }
}

private extension Data {
    mutating func appendUInt16(_ value: UInt16) {
        append(UInt8(value & 0xff))
        append(UInt8((value >> 8) & 0xff))
    }

    mutating func appendUInt32(_ value: UInt32) {
        append(UInt8(value & 0xff))
        append(UInt8((value >> 8) & 0xff))
        append(UInt8((value >> 16) & 0xff))
        append(UInt8((value >> 24) & 0xff))
    }
}
