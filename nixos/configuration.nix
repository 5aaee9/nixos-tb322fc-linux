{ config, pkgs, ... }:

{
  # The Android boot image's initramfs mounts rootfs and execs /sbin/init.
  boot.initrd.enable = false;
  boot.loader.grub.enable = false;
  boot.loader.systemd-boot.enable = false;

  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;

  networking.networkmanager.enable = true;

  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
    wireplumber.enable = true;
  };

  programs.dconf.enable = true;
  security.polkit.enable = true;
  services.gnome.gnome-keyring.enable = true;

  xdg.portal = {
    enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gnome ];
  };

  # Keep the development rootfs observable while leaving the release account
  # and password policy for the first-boot design.
  services.openssh.enable = true;
  services.openssh.settings = {
    PermitRootLogin = "prohibit-password";
    PasswordAuthentication = false;
  };

  environment.systemPackages = with pkgs; [
    bashInteractive
    curl
    git
    pciutils
    usbutils
    vim
  ];

  system.stateVersion = "26.05";
}
