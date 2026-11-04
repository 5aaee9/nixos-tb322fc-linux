{ pkgs, ... }:

{
  # Repository image policy; not imported by the reusable device module.
  networking.hostName = "y700-elden";

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
