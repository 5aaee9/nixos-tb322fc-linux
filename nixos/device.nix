{ ... }:

{
  imports = [ ./audio.nix ];

  # Device firmware and calibration are imported from the user's own matching
  # Android build in a later step. No binary firmware is committed here.
  environment.etc."y700/reference-firmware.json".source =
    ../vendor/tb322fc-linux/firmware.json;

  # The Android initramfs retains this tablet's firmware in RAM. NixOS's
  # default activation otherwise replaces the path with its generic store.
  system.activationScripts.y700Firmware = {
    deps = [ "udevd" ];
    text = ''
      if [ -d /run/firmware ]; then
        echo -n /run/firmware > /sys/module/firmware_class/parameters/path
      fi
    '';
  };
}
