# Rootfs setup

Use an AArch64 Linux userspace with systemd/udev on an already prepared ext4
partition named `rootfs`. Arch Linux ARM has been used for hardware testing.
This project does not repartition the tablet or ship a prepared rootfs image.

## Base system

The rootfs needs an executable `/sbin/init`, a normal `/usr` and `/etc`, and
writable `/var`. The initramfs mounts tmpfs `/run` and carries the required
firmware into it. No fixed UUID, rootfs size, filesystem-resize tool or private
ADB payload is required by the handoff.

Install the normal distro packages for systemd, udev, D-Bus, networking and a
login account. Configure NetworkManager and Wi-Fi credentials before boot if
SSH is your primary access method. Install/configure OpenSSH separately; do
not embed personal SSH keys in an image or this repository. A USB ADB gadget
is optional rootfs configuration, not a dependency of this boot image.

For a desktop, install a Wayland compositor/session, greeter, libdrm and Mesa
with Adreno 830 Turnip/Zink support. Mesa 26.2.1 has been used successfully.
Speaker playback uses ALSA UCM, PipeWire and WirePlumber. The kernel's tested
device drivers are built in; missing unrelated kernel modules are not a reason
to copy a private module directory.

## Build the patched userspace

The following are **native AArch64 build commands**, run inside the target
distro or an AArch64 build environment. They are not host-x86 binaries to copy
onto the tablet. Fetch the source trees using the umbrella's source script
before running them. Use distro packages for these build dependencies:

| Component | Build/runtime development dependencies |
| --- | --- |
| All | C/C++ compiler, Meson >= 1.4, Ninja, pkg-config, Python 3 |
| hexagonrpc | libc and Linux headers |
| libssc | GLib/GIO, libqmi (qmi-glib >= 1.33.4), protobuf-c, `protoc`, `protoc-gen-c`, GObject introspection, Vala |
| iio-sensor-proxy | GLib/GIO >= 2.76, libgudev >= 237, polkit, udev/systemd, libssc, gettext |
| libcamera/qcam | libyaml, libudev, OpenSSL or GnuTLS, libevent, Qt6 Core/Gui/Widgets/OpenGL, Python Jinja2/PLY/PyYAML, OpenSSL command-line tools |

Build and install in dependency order. These installation commands modify the
target userspace under `/usr`, so run them in the intended rootfs/build system:

```sh
meson setup build/hexagonrpc sources/hexagonrpc --prefix=/usr --libdir=lib
meson compile -C build/hexagonrpc
sudo meson install -C build/hexagonrpc

meson setup build/libssc sources/libssc --prefix=/usr --libdir=lib
meson compile -C build/libssc
sudo meson install -C build/libssc

meson setup build/iio-sensor-proxy sources/iio-sensor-proxy \
    --prefix=/usr --libdir=lib --libexecdir=libexec -Dssc-support=enabled
meson compile -C build/iio-sensor-proxy
sudo meson install -C build/iio-sensor-proxy

meson setup build/libcamera sources/libcamera --prefix=/usr --libdir=lib \
    -Dpipelines=simple -Dipas=softisp -Dqcam=enabled -Dcam=enabled \
    -Ddocumentation=disabled -Dgstreamer=disabled -Dpycamera=disabled \
    -Dlc-compliance=disabled -Dv4l2=disabled -Dsoftisp-gpu=disabled \
    -Dapps-output-dng=disabled -Dtest=false
meson compile -C build/libcamera
sudo meson install -C build/libcamera
sudo ldconfig
```

Meson installs the library, IPA, worker and default configuration together;
keep them from the same build. The included patches require no uncommitted
files or prebuilt private payload. Do not copy a historical camera bundle or
per-unit lens calibration into a generic rootfs. Generic manual capture works
without claiming calibrated autofocus on every module.

## Sensors: data and services

The ADSP filesystem needs data copied **read-only from your own Android system**:

| Linux path | Source |
| --- | --- |
| `/var/lib/hexagonrpc/acdb` | `/vendor/etc/acdbdata` |
| `/var/lib/hexagonrpc/dsp` | `/vendor/dsp` |
| `/var/lib/hexagonrpc/sensors/config` | `/vendor/etc/sensors/config` |
| `/var/lib/hexagonrpc/sensors/state` | Full `/mnt/vendor/persist/sensors` contents, including `registry/`, `sns_reg_version` and companion state files |
| `/var/lib/hexagonrpc/sensors/sns_reg.conf` | `/vendor/etc/sensors/sns_reg_config` |
| `/var/lib/hexagonrpc/socinfo` | Symlink to the running Linux `/sys/devices/soc0` |

Keep this directory private to root. Only `sensors/state` is writable through
HexagonFS; configuration and DSP libraries stay read-only. Preserve existing
Linux sensor state on upgrades. Never write Android persist. A kernel driver
alone cannot replace this device-specific calibration/registry input.

After the binaries and data are installed:

```sh
sudo install -Dm644 rootfs/sensors/hexagonrpcd-sensors.service \
    /etc/systemd/system/hexagonrpcd-sensors.service
sudo install -Dm644 rootfs/sensors/iio-sensor-proxy.conf \
    /etc/systemd/system/iio-sensor-proxy.service.d/ssc.conf
sudo systemctl daemon-reload
sudo udevadm control --reload
sudo systemctl enable hexagonrpcd-sensors.service
```

The patched iio-sensor-proxy installs the SSC accelerometer udev tag. Restart
the sensor services on the target after installation. Gyro is available through
SSC; iio-sensor-proxy does not provide a generic desktop gyro stream.

## Speakers and cameras

Install the files under `rootfs/audio/ucm2/` into `/usr/share/alsa/ucm2/`, retaining
the hierarchy. The matching amplifier profiles and generated topology are
already carried by the boot image. Back up existing UCM files before replacing
them. The supplied UCM exposes the HiFi/Speaker route only.

For cameras, install `rootfs/camera/70-libcamera-dma-heap.rules` into
`/etc/udev/rules.d/` and the desktop file into `/usr/share/applications/`.
The desktop launcher runs the native `qcam` installed above. Active local users
need the normal video/media-node permissions and DMA-heap access. Use the
libcamera default tuning until the individual sensor/lens module is calibrated.
