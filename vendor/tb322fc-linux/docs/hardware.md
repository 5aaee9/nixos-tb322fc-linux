# Hardware support

The matrix below is the reference project's machine-validation record.
It describes that reference system, not the parent project's NixOS rootfs.
See the separate [NixOS status](../../../docs/public/status.md) for current
target evidence and the USB/NBD test's limitations.

| Area | Working | Remaining limits |
| --- | --- | --- |
| Boot / storage | Kernel startup, UFS, ext4 rootfs | Requires a dedicated, already prepared rootfs |
| Display | MSM DPU/DSI, NT36536 panel, AW99706 backlight; greeter and 24/40/60/90/120/144/165 Hz | External display is not validated |
| Touch | Built-in NT36536 SPI firmware and input | Physical touch after every suspend scenario is not established |
| Graphics | Adreno 830, Turnip Vulkan and Zink rendering | No graphics conformance or long stress-test claim |
| Wi-Fi | ath12k Peach association and SSH transport | Throughput and long-term stability remain unmeasured |
| Bluetooth | QCA UART firmware load and power-on | Discovery failed; pairing and audio not validated |
| Audio | AW88461 stereo speaker playback and PCM progress; SD1 AudioReach routing | Microphone/headset routes not validated |
| Haptics | Both motors, bounded force-feedback replay and cleanup | Arbitrary audio waveform streaming is not a production API |
| Sensors | Accelerometer, gyro and ambient-light samples over SSC | Physical desktop rotation and compass accuracy need validation |
| Cameras | S5KJNS rear, GC08A8 front, GT9764 actuator, CAMSS capture | Generic autofocus calibration, colour processing and still-image workflow remain incomplete |
| USB | Qualcomm controller and role-switch support | ADB requires a rootfs daemon/gadget setup; not supplied by the initramfs |
| Power / thermal | CPU/GPU scaling and cooling controls | Long-term standby power not measured |
| Suspend | Successful earlier RTC wake cycles and abort recovery | USB-attached sleep can abort with EBUSY; not reliable |
| Battery / charging | Battery-manager communication and existing charging control | PC USB discharge, reporting discrepancies and charger wake behavior remain open |
| Buttons | Kernel input definitions | Physical volume-event checks incomplete |

Verified drivers and their dependencies are built in. `/proc/modules` can be
empty while hardware works. Accel/gyro/light depend on ADSP userspace services,
not AP-side I2C/SPI sensor drivers. Hardware video codecs and CDSP are not
claimed as supported.

The public image identifies itself by its kernel release and source manifest.
Tests should record boot-image hashes and source commits, not private build labels.
