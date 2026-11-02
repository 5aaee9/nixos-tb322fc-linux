{ ... }:

{
  fileSystems."/" = {
    device = "/dev/disk/by-partlabel/rootfs";
    fsType = "ext4";
    options = [ "noatime" "errors=remount-ro" ];
  };

  # The target kernel and Android boot image provide the actual early
  # hardware support. These values document the rootfs contract only.
  swapDevices = [ ];
}
