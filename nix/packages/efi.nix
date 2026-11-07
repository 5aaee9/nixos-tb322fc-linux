{
  pkgs,
  inputs,
  self,
  project,
  boot,
  firmware,
}:
let
  arm = import inputs.nixpkgs { system = "aarch64-linux"; };
  system = self.nixosConfigurations.elden-persistent.config.system.build.toplevel;
  tools = pkgs.linkFarm "y700-efi-tools" [
    {
      name = "systemd";
      path = arm.systemd;
    }
    {
      name = "dosfstools";
      path = pkgs.dosfstools;
    }
    {
      name = "mtools";
      path = pkgs.mtools;
    }
  ];
  mkGeneration =
    {
      number,
      toplevel ? system,
      usbDebug ? false,
      readonlyRoot ? false,
      kernel ? boot.kernels.efi,
    }:
    pkgs.runCommand "y700-efi-generation-${toString number}"
      {
        nativeBuildInputs = [ pkgs.python3 ];
      }
      ''
        python ${project}/tools/build-efi-generation.py --kernel ${kernel} \
          --system ${toplevel} --generation ${toString number} --out "$out" \
          ${pkgs.lib.optionalString usbDebug "--usb-debug"} \
          ${pkgs.lib.optionalString readonlyRoot "--readonly-root"} \
          --firmware ${firmware} --busybox ${boot.busybox}/bin/busybox \
          --gen-init-cpio ${boot.genInitCpio}/bin/gen_init_cpio
      '';
  generation = mkGeneration { number = 1; };
  mkEsp =
    {
      generations ? [ generation ],
      defaultGeneration ? 1,
    }:
    pkgs.runCommand "y700-efi-esp" { nativeBuildInputs = [ pkgs.python3 ]; } ''
      python ${project}/tools/build-efi-esp.py \
        ${pkgs.lib.concatMapStringsSep " " (g: "--generation ${g}") generations} \
        --default ${toString defaultGeneration} --tools ${tools} --out "$out"
    '';
  esp = mkEsp { };
in
{
  inherit
    generation
    esp
    mkGeneration
    mkEsp
    tools
    ;
}
