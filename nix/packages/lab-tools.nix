{ pkgs, arm }:
pkgs.linkFarm "y700-arm64-efi-lab-tools" [
  {
    name = "qemu";
    path = pkgs.qemu;
  }
  {
    name = "firmware";
    path = arm.OVMF.fd;
  }
  {
    name = "systemd";
    path = arm.systemd;
  }
  {
    name = "kernel";
    path = arm.linuxPackages.kernel;
  }
  {
    name = "kernel-modules";
    path = arm.linuxPackages.kernel.modules;
  }
  {
    name = "mtools";
    path = pkgs.mtools;
  }
  {
    name = "dosfstools";
    path = pkgs.dosfstools;
  }
]
