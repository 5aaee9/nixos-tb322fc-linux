# AVB signing and locked fastboot

An earlier read-only assessment, before the owner unlocked the tablet,
reported the following state. Current NixOS tests require an already
unlocked bootloader; see [current status](../../../docs/public/status.md).

| Variable | Value |
| --- | --- |
| `modelname` | `TB322FC` |
| `hwboardid` | `TB322FC_SM8750P_16+512` |
| `build.display.id` | `TB322FC_CN_OPEN_USER_Q00041.1_W_ZUXOS_1.5.10.229_ST_260514` |
| `secure` | `yes` |
| `unlocked` | `no` |
| `current-slot` | `a` |
| `partition-size:boot_a` | `0x6000000` |

The `showdo/AOSP-Testkey-BootSigner` reference supplies a TB322FC
`TB322_ZUXOS_1.5.10.183` boot template. Its AVB footer uses the AOSP test
RSA-4096 key (`2597c218aae470a130f61162feaae70afd97f011`), rollback index
`1738713600`, and a `100663296` byte boot partition. The current ABL does not
support the fastboot `fetch` command, so the exact `.229` stock boot image
could not be read from the device while it was in fastboot. The template is
therefore recorded as a versioned public reference, not as proof of the
current `.229` footer properties.

`nix run .#sign-boot-avb` copies footer parameters from an external stock
template and signs a new host-side image with an external private key.
Nix supplies pinned avbtool and OpenSSL; the template and key are runtime
arguments and the key never enters the Nix store. For a new local candidate:

```sh
nix run .#sign-boot-avb -- \
  --input out/boot-usb-nbd/boot.img \
  --template /private/path/stock-avb-template.img \
  --key /private/path/authorized-signing-key.pem \
  --output out/boot-usb-nbd-signed.img
```

The historical `.183`-template candidate was `100663296` bytes and verified locally with
`avbtool verify_image`; its SHA-256 is recorded in
`artifacts/AVB-SHA256SUMS`. The candidate retains the USB/NBD kernel payload
and its boot command line. It is not a replacement for any Android partition.

The candidate was sent with exactly one command:

```text
fastboot -s <serial> boot boot-usb-nbd-aosp-testkey.img
```

Windows fastboot transferred all `98304 KB`, then ABL returned:

```text
Booting FAILED (remote: 'Fastboot boot command is not available in locked device')
```

The post-test read-only checks still reported `unlocked: no`,
`current-slot: a`, and `partition-size:boot_a: 0x6000000`. No RNDIS adapter,
NBD connection, kernel log, or rootfs runtime evidence was produced. The
failure occurs before AVB verification or Linux execution, so an AOSP test-key
footer does not enable `fastboot boot` while this ABL remains locked.

Signing creates a host file only. It does not authorize an unlock, flash,
erase or active-slot change.
