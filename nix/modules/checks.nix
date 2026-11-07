{ self, inputs, ... }:
{
  perSystem = { pkgs, y700, ... }: {
    checks = {
      nixos-modules = import ../../tests/nixos-modules.nix {
        inherit self inputs pkgs;
      };
      power-key-action =
        (inputs.nixpkgs.lib.nixosSystem {
          system = pkgs.stdenv.hostPlatform.system;
          modules = [
            self.nixosModules.power-key
            { services.desktopManager.gnome.enable = true; }
          ];
        }).config.system.build.y700PowerKeyAction;
      uefi-memory = y700.uefi.memoryCheck;
      kshimc-menu = y700.kshim.menuCheck;
      readonly-runner =
        pkgs.runCommand "y700-readonly-runner-check"
          { nativeBuildInputs = [ pkgs.python3 ]; }
          ''
            python ${../../tools/test-readonly-runner.py} \
              --runner ${y700.diagnostics.runnerNative}/bin/readonly-runner \
              --child ${y700.diagnostics.testChildNative}/bin/readonly-runner-child \
              --reader ${y700.diagnostics.readerNative}/bin/readonly-range-reader \
              --out "$TMPDIR/runner-test"
            mkdir "$out"
            cp "$TMPDIR/runner-test/report.json" "$out/"
          '';
      rootfs-copy-diagnostics =
        pkgs.runCommand "y700-rootfs-copy-diagnostics"
          {
            nativeBuildInputs = [
              pkgs.python3
              pkgs.e2fsprogs
            ];
          }
          ''
            python ${../../tools/test-rootfs-copy.py} --out "$TMPDIR/rootfs-copy-lab"
            mkdir -p "$out"
            cp "$TMPDIR/rootfs-copy-lab/report.json" "$out/"
            for result in "$TMPDIR"/rootfs-copy-lab/*/result.json; do
              case_name="$(basename "$(dirname "$result")")"
              mkdir "$out/$case_name"
              cp "$result" "$out/$case_name/"
              cp "$TMPDIR/rootfs-copy-lab/$case_name/"*.stdout \
                "$TMPDIR/rootfs-copy-lab/$case_name/"*.stderr "$out/$case_name/"
            done
          '';
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
            python -m unittest discover -s tests -p 'test_uefi_nixos_evidence.py' -v
            python -m unittest discover -s tests -p 'test_power_key_session.py' -v
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
