{ pkgs, project }:
let
  firmwareArchive = pkgs.requireFile {
    name = "tb322fc-229-firmware.tar";
    sha256 = "3b3e61e83579f1a325fe629b8e7f7bd8603654cfe725a2cb89564e0e3d038097";
    message = "Import this tablet's 78 firmware files with nix run .#import-device-inputs -- --firmware DIRECTORY";
  };
in
{
  stockBoot = pkgs.requireFile {
    name = "tb322fc-229-stock-boot.img";
    sha256 = "9f7cf9582f4c36b9ba831578b4f1182439a04be813bf277450fab595ae5d9a53";
    message = "Import the verified own-tablet .229 boot backup with nix run .#import-device-inputs -- --stock-boot FILE";
  };
  firmware =
    pkgs.runCommand "tb322fc-229-firmware"
      {
        nativeBuildInputs = [ pkgs.python3 ];
        preferLocalBuild = true;
        allowSubstitutes = false;
      }
      ''
        mkdir -p "$out"
        tar xf ${firmwareArchive} -C "$out"
        python ${project}/tools/import-nix-device-inputs.py --verify-firmware "$out"
      '';
}
