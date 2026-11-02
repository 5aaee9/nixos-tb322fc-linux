# Boot and initramfs

The boot image contains the kernel, board DTB and an embedded initramfs. Its
external ramdisk is empty. The bootloader retains the Android system; testing
uses `fastboot boot` only.

## Rootfs handoff

`initramfs/init` mounts proc, sysfs and devtmpfs, waits for the six expected
UFS logical units, and locates a partition whose GPT name is `rootfs`.
The selector is `root=PARTLABEL=rootfs` by default. An explicit
`root=PARTUUID=<UUID>` is also supported, but the selected partition must still
be named `rootfs`. Multiple matches and missing devices fail closed.

No fixed partition number, UUID, offset or size is compiled into this script.
It marks other UFS disks/partitions read-only while leaving the selected rootfs
and its parent disk writable, mounts rootfs as ext4 and checks `/sbin/init`.
It does not resize filesystems, repartition, mount Android persist, run repair
tools, change calibration or reboot automatically on failure.

Firmware is copied into the tmpfs `/run/firmware`, and the standard firmware
loader search path points there. This retains the early firmware after the
initramfs is freed, including late Wi-Fi requests. The virtual filesystems
are moved into rootfs before `switch_root` starts the rootfs init.

The script starts no private ADB binary, generates no experiment-specific units,
and performs no hardware register probes. Network access and optional USB
gadgets belong to the rootfs service configuration.

## Logging

Early messages go to the kernel console. Rootfs journaling starts only after
handoff. A kernel initcall hang can occur before rootfs is mounted, so missing
or old rootfs logs do not rule out an early display-driver failure. Do not
infer successful boot from a bootloader accepting the image.

Record a boot-image hash, kernel release, source revisions and actual device
results when reporting problems. Keep raw personal logs and device identifiers
outside the public repository.
