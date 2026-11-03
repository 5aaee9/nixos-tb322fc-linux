{ lib, pkgs, ... }:

{
  # Installation sets a password through the trusted USB root connection.
  # Never carry the disposable desktop's empty password onto internal storage.
  users.users.y700.initialHashedPassword = lib.mkForce "!";
  services.displayManager.autoLogin.enable = lib.mkForce false;

  # Internal storage removes the NBD dependency, but suspend/resume still
  # needs a separate hardware test. The power key continues to toggle display.
  systemd.sleep.settings.Sleep = {
    AllowSuspend = "no";
    AllowHibernation = "no";
    AllowHybridSleep = "no";
    AllowSuspendThenHibernate = "no";
  };
  systemd.services.y700-power-key.unitConfig.ConditionKernelCommandLine =
    lib.mkForce "root=PARTLABEL=rootfs";

  systemd.services.display-manager.requires = [
    "y700-local-root-prepare-shutdown.service"
  ];
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
  boot.loader.efi.canTouchEfiVariables = false;
}
