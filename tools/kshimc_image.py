"""Strict TB322FC Android-base image checks, independent of the upstream packer."""

import hashlib
import struct

PARTITION_BYTES = 96 * 1024 * 1024
RUNTIME_BYTES = 4 * 1024 * 1024
PAGE = 4096
MARKER = b"tb322fc-diag-v1;"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def stock_kernel(stock, expected_sha256):
    require(sha256(stock) == expected_sha256, "Stock SHA-256 mismatch")
    require(len(stock) == PARTITION_BYTES, "Expected a 96 MiB stock partition backup")
    require(stock[:8] == b"ANDROID!" and u32(stock, 40) == 4, "Expected Android boot v4")
    require(u32(stock, 20) == 1584, "Unexpected boot header size")
    require(u32(stock, 12) == 0 and u32(stock, 1580) == 0, "Unexpected ramdisk/signature")
    size = u32(stock, 8)
    require(64 <= size < len(stock) - PAGE, "Invalid stock kernel length")
    kernel = stock[PAGE:PAGE + size]
    require(kernel[56:60] == b"ARM\x64", "Expected a raw ARM64 stock kernel")
    require(64 <= u64(kernel, 16) < PARTITION_BYTES, "Invalid ARM64 image_size")
    require(kernel[32:56] == bytes(24), "Stock kernel has occupied manifest fields")
    require(stock[-64:-60] == b"AVBf", "Stock backup has no AVB footer")
    return kernel


def inspect_packed(packed, original, runtime):
    require(len(runtime) == RUNTIME_BYTES, "Runtime is not 4 MiB")
    require(len(packed) >= 64 and packed[56:60] == b"ARM\x64", "Bad packed ARM64 header")
    require(u64(packed, 16) == len(packed), "Packed image_size mismatch")
    offset, size, shim_offset = struct.unpack_from("<QQQ", packed, 32)
    require(64 <= offset <= len(packed) and size == len(packed) - offset,
            "Manifest bounds mismatch")
    manifest = packed[offset:]
    require(len(manifest) >= 60, "Truncated manifest")
    magic, major, minor, count, default, timeout = struct.unpack_from("<IHHIII", manifest)
    require((magic, major, minor, count, default, timeout) ==
            (0x464D504B, 0, 1, 2, 0, 10000), "Unexpected diagnostic manifest")
    # Android resumes at base + 4. A branch originally at +0 is relocated.
    first, second = u32(original, 0), u32(original, 4)
    if second & 0xFC000000 == 0x14000000:
        continuation = second
    else:
        require(first & 0xFC000000 == 0x14000000, "Unsupported stock entry branch")
        continuation = 0x14000000 | ((first - 1) & 0x03FFFFFF)
    require(u32(packed, 4) == continuation, "Android continuation instruction changed")
    restored = bytearray(packed[:len(original)])
    for source_offset, target_offset in ((20, 0), (28, 16), (36, 32), (44, 40), (52, 48)):
        struct.pack_into("<Q", restored, target_offset, u64(manifest, source_offset))
    require(restored == original, "Original Android kernel was not preserved")
    entries = []
    position = 60
    for _ in range(count):
        require(position + 56 <= len(manifest), "Truncated entry")
        values = struct.unpack_from("<QQIIQIIIQI", manifest, position)
        entry_offset, entry_size, kind, flags, load, start, dtb, align, maximum, name_len = values
        require(0 < name_len <= 128 and position + 56 + name_len <= len(manifest),
                "Invalid entry name")
        raw_name = manifest[position + 56:position + 56 + name_len]
        require(b"\x00" not in raw_name, "Invalid entry name terminator")
        name = raw_name
        require(entry_offset + entry_size <= offset, "Entry overlaps manifest")
        require((load, start, dtb, maximum) == (0, 0, 0, 0), "Unexpected handoff/copy metadata")
        entries.append((entry_offset, entry_size, kind, flags, align, name))
        position = (position + 56 + name_len + 3) & ~3
    require(position == len(manifest), "Trailing manifest data")
    require(entries[0] == (0, len(original), 1, 5, 21, b"Android"), "Unexpected Android entry")
    require(entries[1][:4] == (shim_offset, RUNTIME_BYTES, 3, 4), "Unexpected runtime entry")
    require(entries[1][4:] == (2, b"Attached Shim"), "Unexpected runtime alignment/name")
    require(shim_offset % 4 == 0, "Misaligned runtime")
    require(shim_offset >= max(len(original), u64(original, 16)), "Runtime overlaps Android")
    require(packed[shim_offset:shim_offset + RUNTIME_BYTES] == runtime, "Runtime byte mismatch")
    instruction = u32(packed, 0)
    require(instruction >> 26 == 0x25, "Entry is not an ARM64 BL")
    displacement = instruction & 0x03FFFFFF
    if displacement & 0x02000000:
        displacement -= 0x04000000
    require(displacement * 4 == shim_offset, "Entry branch misses runtime")
    return {"manifest_offset": offset, "manifest_bytes": size, "shim_offset": shim_offset,
            "entries": 2, "timeout_ms": timeout, "stock_restoration": "byte-identical"}


def wrap_boot(stock, packed):
    header = bytearray(stock[:PAGE])
    struct.pack_into("<I", header, 8, len(packed))
    image = bytes(header) + packed
    image += bytes((-len(image)) % PAGE)
    require(len(image) <= PARTITION_BYTES - 65536, "Boot image exceeds reserved capacity")
    return image


def verify_boot(image, stock, runtime, expected_stock_sha256):
    original = stock_kernel(stock, expected_stock_sha256)
    require(PAGE + 64 <= len(image) <= PARTITION_BYTES - 65536, "Boot image size out of bounds")
    header = bytearray(stock[:PAGE])
    kernel_size = u32(image, 8)
    struct.pack_into("<I", header, 8, kernel_size)
    require(image[:PAGE] == header, "Unexpected stock boot-header modification")
    require(PAGE + kernel_size <= len(image), "Truncated packed kernel")
    require(len(image) == (PAGE + kernel_size + PAGE - 1) // PAGE * PAGE,
            "Unexpected boot-image trailing extent")
    require(not any(image[PAGE + kernel_size:]), "Nonzero boot-image padding")
    return inspect_packed(image[PAGE:PAGE + kernel_size], original, runtime)
