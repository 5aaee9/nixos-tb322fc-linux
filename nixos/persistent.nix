{ config, lib, pkgs, ... }:

{
  boot.loader.efi.efiSysMountPoint = lib.mkDefault "/efi";
  fileSystems.${config.boot.loader.efi.efiSysMountPoint} = {
    device = "/run/y700-esp/device";
    fsType = "vfat";
    noCheck = true;
    options = [ "nofail" "rw" "umask=0077" "nodev" "nosuid" "noexec"
      "x-systemd.requires=y700-esp-guard.service" ];
  };
  systemd.services.y700-esp-guard = {
    description = "Permit writes to the unique onboard Linux ESP";
    after = [ "systemd-udev-trigger.service" ];
    unitConfig = { DefaultDependencies = false; StopWhenUnneeded = true; };
    path = [ pkgs.util-linux pkgs.coreutils pkgs.gnugrep pkgs.systemd ];
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; RuntimeDirectory = "y700-esp"; };
    script = builtins.readFile ./esp-guard.sh;
    preStop = ''
      blockdev --setro /run/y700-esp/device
      test "$(blockdev --getro /run/y700-esp/device)" = 1
    '';
  };

  # Internal storage removes the NBD dependency, but suspend/resume still
  # needs a separate hardware test. The power key continues to toggle display.
  systemd.sleep.settings.Sleep = {
    AllowSuspend = lib.mkDefault "no";
    AllowHibernation = lib.mkDefault "no";
    AllowHybridSleep = lib.mkDefault "no";
    AllowSuspendThenHibernate = lib.mkDefault "no";
  };

  systemd.services.display-manager = lib.mkIf config.services.displayManager.enable {
    requires = [ "y700-local-root-prepare-shutdown.service" ];
  };
  systemd.services.y700-local-root-prepare-shutdown = {
    description = "Verify shutdown ramfs before opening the persistent desktop";
    wantedBy = [ "multi-user.target" ];
    requires = [ "generate-shutdown-ramfs.service" ];
    after = [ "generate-shutdown-ramfs.service" ];
    before = [ "display-manager.service" ];
    unitConfig.ConditionKernelCommandLine = "root=PARTLABEL=rootfs";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.coreutils}/bin/chroot /run/initramfs ${pkgs.glibc}/lib/ld-linux-aarch64.so.1 --list /shutdown";
    };
  };

  # Android remains the installed boot chain. Rebuilds must not install a
  # loader or change EFI variables until the separate boot-chain work passes.
  boot.loader.efi.canTouchEfiVariables = lib.mkDefault false;

  # Netconsole streams printk to the host over USB, but keep a local copy
  # as a fallback. A one-second journald sync interval bounds the evidence
  # loss if the kernel dies before its final UDP datagrams leave the wire.
  services.journald.extraConfig = lib.mkDefault ''
    SyncIntervalSec=1
  '';

}
