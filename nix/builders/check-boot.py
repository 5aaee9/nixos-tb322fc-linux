from pathlib import Path
import struct
import sys

out = Path(sys.argv[1])
boot, kernel = (out / "boot.img").read_bytes(), (out / "Image").read_bytes()
assert boot[:8] == b"ANDROID!" and struct.unpack_from("<I", boot, 40)[0] == 4
assert struct.unpack_from("<I", boot, 20)[0] == 1584
assert struct.unpack_from("<I", boot, 1580)[0] == 0
assert not any(boot[24:40]) and not any(boot[1584:4096])
assert struct.unpack_from("<I", boot, 8)[0] == len(kernel)
assert struct.unpack_from("<I", boot, 12)[0] == 0
assert boot[4096:4096+len(kernel)] == kernel
assert boot[44:1580].split(b"\0", 1)[0].decode() == (out / "cmdline.txt").read_text().strip()
assert len(boot) <= 96 * 1024**2
assert not any(boot[4096+len(kernel):])
