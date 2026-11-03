{ self, inputs, ... }:
{
  perSystem = { pkgs, y700, ... }: {
    checks = {
      kshimc-menu = y700.kshim.menuCheck;
      host-contracts =
        pkgs.runCommand "y700-host-contracts"
          {
            nativeBuildInputs = [
              pkgs.python3
              y700.kshim.packer
              pkgs.bash
              pkgs.git
            ];
          }
          ''
            cp -R ${self.outPath} source
            chmod -R u+w source
            cd source
            export KSHIM_PACKER=${y700.kshim.packer}/bin/MultiBootKernelPatcher
            python -m unittest discover -s tests -p 'test_kshimc_image.py' -v
            python -m unittest discover -s tests -p 'test_efi_generation.py' -v
            touch "$out"
          '';
      source-pins =
        pkgs.runCommand "y700-source-pins"
          {
            nativeBuildInputs = [ pkgs.python3 ];
            pins = builtins.toJSON (import ../lib/source-pins.nix { inherit inputs; }).actual;
          }
          ''
            python - ${self.outPath} <<'PY'
            import json,os,sys
            from pathlib import Path
            p=Path(sys.argv[1])/"vendor/tb322fc-linux"
            pins=json.loads(os.environ["pins"])
            assert pins["kernel-src"]["rev"]==json.loads((p/"sources.json").read_text())["kernel"]["commit"]
            shim=json.loads((p/"patches/kshimc/sources.json").read_text())
            assert pins["kshim-src"]["rev"]==shim["runtime"]["revision"]
            for name in ("crdk","picolibc","lvgl"):
                assert pins[name+"-src"]["rev"]==shim["dependencies"][name]["revision"]
            PY
            touch "$out"
          '';
    };
  };
}
