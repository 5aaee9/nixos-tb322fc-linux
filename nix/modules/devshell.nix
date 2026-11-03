{ ... }:
{
  perSystem = { pkgs, y700, ... }: {
    formatter = pkgs.nixfmt;
    devShells.default = pkgs.mkShell {
      packages = with pkgs; [
        nixfmt
        python3
        cmake
        ninja
        git
        gnumake
        bison
        flex
        bc
        perl
        llvmPackages.clang
        llvmPackages.lld
        llvmPackages.llvm
        dtc
        e2fsprogs
        dosfstools
        mtools
        cpio
        gzip
        xz
        qemu
        util-linux
        kmod
        y700.kshim.packer
      ];
      shellHook = ''
        echo "Y700 pinned build environment. Use nix build .#<artifact>."
      '';
    };
  };
}
