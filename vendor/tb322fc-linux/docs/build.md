# Build

## Host dependencies

The kernel and boot builder run on a Linux host. Required commands are:
`git`, `python3`, `make`, `cc`, `curl`, `tar`, `sha256sum`,
`aarch64-linux-gnu-gcc`, `clang`, `ld.lld`, LLVM binutils and `mkbootimg`.
Kernel builds also need flex, bison, bc, Perl, pkg-config, OpenSSL and libelf
development headers. BusyBox requires the cross compiler's static AArch64 libc.
Builds have used Clang/LLD 21.1.8 and BusyBox 1.36.1.

On Debian/Ubuntu these tools are provided by:

```sh
sudo apt install git python3 build-essential curl bzip2 flex bison bc \
    pkg-config libssl-dev libelf-dev gcc-aarch64-linux-gnu \
    libc6-dev-arm64-cross clang lld llvm mkbootimg m4 alsa-utils
```

Check the installed compiler versions; changing the compiler can change the
configuration or generated code. Optional tools are `unpack_bootimg`, `fastboot`,
`adb`, `device-tree-compiler` and `dtschema` for artifact/device/schema checks.
If downloads require a proxy, set `https_proxy` and `http_proxy` in your shell.
The build does not depend on a particular proxy or host username.

## Sources

```sh
python3 scripts/fetch-sources.py
```

This fetches all entries in `sources.json` into `sources/`, applies bundled
patches, and verifies each resulting Git tree. No unpublished commit is needed.
Existing source directories are never reset or overwritten. To fetch just the
kernel and topology macros, pass `kernel audioreach-topology wireless-regdb` as arguments.

The kernel is pinned to `b0c05eb72e10140f87efd0e499ad840e6c3e6975`, one
device-support commit above Linux 7.2. Patched userspace source trees intentionally
have staged changes; their expected post-patch trees are in the manifest.

## Firmware and topology

Follow [firmware preparation](firmware.md) to produce `inputs/firmware/`.
The importer checks every file by content, including renamed stock firmware.
Generate the audio topology before importing:

```sh
mkdir -p build/audio
m4 -I sources/audioreach-topology rootfs/audio/topology.m4 > build/audio/topology.conf
alsatplg -c build/audio/topology.conf -o build/audio/Lenovo-Y700-Gen4-tplg.bin
```

The tested topology compiler is alsatplg 1.2.15.2. Expected output hash:
`33288df358504392dcc1d70ebdff4dc7a9ec8f9936edb30a65b3faa88a2000ef`.
An external `Secondary MI2S Playback` widget warning is expected; the machine
driver supplies it. The firmware importer refuses a different output.

## Kernel and boot image

```sh
bash scripts/build-boot.sh
```

The script validates the kernel tree and firmware, downloads and verifies the
BusyBox source archive, cross-builds a static AArch64 BusyBox, assembles the
initramfs, builds Image/DTB, and packs an Android header-4 boot image. Set `JOBS`
to change parallelism. `bash scripts/build-boot.sh initramfs` stops after the
initramfs build.

The supplied full kernel config keeps the tested hardware selections. Its
host paths are replaced with absolute paths inside this checkout during the
build. Unrelated module selections inherited from the base configuration do
not require installing those modules for the built-in tablet drivers.

The DTB and initramfs are embedded in Image; the external boot-image ramdisk
is empty. Do not append another DTB. The forced kernel command line selects
`root=PARTLABEL=rootfs`; edit both `configs/kernel.config` and
`configs/cmdline.txt` consistently when changing it. Retention parameters in
that command line are part of the device-tested kernel baseline.

The Android version/date fields in the boot header reproduce the supported
packing layout; they do not describe the Linux security-patch level.

## Test

With a prepared rootfs and the tablet already in fastboot:

```sh
fastboot boot artifacts/boot.img
```

Record the new image hash, kernel release, mount state and functional tests.
Reusing a configuration does not make a rebuilt image byte-identical to an
older one. No build script flashes or repartitions the tablet.
