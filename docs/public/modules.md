# Use the NixOS modules

The flake exports account-free device and desktop modules. Add this project
as an input to your deployment and keep hostname, users, credentials, SSH
access and `system.stateVersion` in your own configuration.

```nix
{
  inputs = {
    y700.url = "github:5aaee9/nixos-tb322fc-linux";
    nixpkgs.follows = "y700/nixpkgs";
  };

  outputs = { nixpkgs, y700, ... }: {
    nixosConfigurations.tablet = nixpkgs.lib.nixosSystem {
      modules = [
        y700.nixosModules.default
        y700.nixosModules.gnome
        ./configuration.nix
      ];
    };
  };
}
```

For example, the consuming `configuration.nix` can declare:

```nix
{ ... }:
{
  networking.hostName = "my-tablet";
  system.stateVersion = "26.05";

  users.users.alice = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" ];
  };
}
```

Configure the user's password or authorized SSH keys through your own
credential management. This example supplies neither a password nor
automatic login. Following this project's nixpkgs input retains the tested,
pinned stable base; update your deployment's lock file deliberately.

| Export | Purpose |
| --- | --- |
| `default`, `y700` | TB322FC ARM64 userspace integration, root mount defaults, firmware path, board audio and shutdown/transport guards. No desktop, normal user or SSH listener. |
| `gnome` | GNOME, GDM, PipeWire, portals, dconf and keyring. No account, password or automatic login. |
| `development` | Optional trusted-host USB SSH and USB/NBD lifecycle policy. Exposes `y700.debugPublicKey`; does not create a normal user. |
| `hardware`, `device` | Lower-level root/platform and board firmware/audio layers, already imported by `y700`. |
| `persistent`, `usb-nbd`, `power-key` | Lower-level lifecycle and input layers, already imported by `y700`. |
| `desktop` | Alias for `gnome`. The old export's implicit development account and USB diagnostics have been removed. |

The exports are organized in `nix/modules/nixos-modules.nix`; repository
image configurations compose these same exports in `nix/modules/systems.nix`.
The organization follows the reference project's separation of
`flake.nixosModules` from its image configurations.

## Device and desktop policy

The device module defaults to `aarch64-linux` and a Btrfs root at
`/dev/disk/by-partlabel/rootfs`. Hostname and `system.stateVersion` belong to
the consumer. Root mount defaults use `mkDefault` so an explicit consumer
setting takes precedence; any changed root device must also agree with the
separately built early-boot image.

Importing both `y700` and `gnome` enables the existing udev/systemd power-key
handler. It discovers the active local graphical session through logind and
resolves that account's UID and home through NSS. It works with a custom
user and the GDM greeter, without assuming UID 1000 or `/home/y700`.
Short press toggles the display; holding for two seconds requests GNOME's
power menu. It remains limited to the existing USB/NBD and local-root boot
contracts. Set `services.y700-power-key.enable = false` to supply another
input policy. Actual suspend remains disabled by default pending hardware
validation.

USB debug access is optional:

```nix
{
  imports = [ y700.nixosModules.development ];
  y700.debugPublicKey = "ssh-ed25519 YOUR_PUBLIC_KEY";
}
```

Here `y700` is the flake input in scope; alternatively add the development
module to the consuming flake's `modules` list. The key is public and will
enter the Nix store. An empty key installs no root authorized key. This
profile listens on the development USB address and disables password
authentication; choose your own SSH configuration when not using it.

## Build and deploy

From the consuming flake:

```sh
nix build .#nixosConfigurations.tablet.config.system.build.toplevel
```

Build on an ARM64 host or use a configured ARM64 builder. After the system
closure and deployment credentials are ready, standard NixOS deployment
tools can activate that configuration on the installed Linux system.
This module refactor itself performs no deployment or device operation.

The board kernel, firmware-bearing initramfs and Android boot image are
separate artifacts. The stock-ABL/kShimC UEFI provider can run systemd-boot;
its current EFI filesystem is embedded in the boot image. Importing a module
does not build or install that boot image, write the disk ESP, or substitute
the generic NixOS kernel for the TB322FC kernel. Updating the userspace
closure and updating the embedded kernel/initrd remain separate operations.
Use the matching own-tablet firmware and the
[Btrfs/installed-menu procedure](btrfs.md).

## Repository image profiles

The exported modules contain no `users.users.y700` definition. To retain
the repository's attended test workflows, its configurations add separate,
unexported files under `nix/profiles/`:

- `elden` retains GNOME with no normal user.
- `elden-desktop` adds the disposable `y700` user, UID 1000, an empty initial
  local password and automatic login.
- `elden-persistent` locks that user's initial password and enables
  GNOME automatic login for attended development; the fresh installer
  supplies a private password.

The packaged `rootfs*` artifacts still use these repository profiles.
Importing the modules into a different flake does not import those accounts.
For consumers of the previous `desktop` export, explicitly add
`development` only if USB diagnostics are desired, and define users and
login policy in the consuming configuration.

The host check `checks.x86_64-linux.nixos-modules` evaluates complete
account-free, custom-user, debug and standalone-GNOME systems, and checks the
repository profiles' account policies. Power-key session tests cover custom
accounts, greeters, lock state and invalid-session rejection.
