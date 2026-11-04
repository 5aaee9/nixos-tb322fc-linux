{
  description = "Lenovo Y700 Gen 4: pinned NixOS, kernel and boot artifacts";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";
    flake-parts = {
      url = "github:hercules-ci/flake-parts/f7c1a2d347e4c52d5fb8d10cb4d94b5884e546fb";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    device-config = {
      url = "path:./nix/device-config";
      flake = false;
    };
    kernel-src = {
      url = "github:torvalds/linux/8d3ae59288f1e7d58d76558a6ee96d533bc5019f";
      flake = false;
    };
    audioreach-src = {
      url = "github:linux-msm/audioreach-topology/e7b20b2b16cdda18eb8ae143c8d95c4815c0288e";
      flake = false;
    };
    wireless-regdb-src = {
      url = "git+https://git.kernel.org/pub/scm/linux/kernel/git/wens/wireless-regdb.git?rev=b488e68eb1ca0a0dcdf742c7f4195c7678eafdc5&shallow=1";
      flake = false;
    };
    kshim-src = {
      url = "github:tc1911/kShimC4sheng/51aef95e6bb5fa569c4653e96f3f06ca02f9d784";
      flake = false;
    };
    crdk-src = {
      url = "github:Project-Aloha/CrDK/b6c3335136b7f6b28271917de11e8f11982975fc";
      flake = false;
    };
    picolibc-src = {
      url = "github:picolibc/picolibc/f7edb0869e64b9d687f46961adeef7154921fe92";
      flake = false;
    };
    lvgl-src = {
      url = "github:lvgl/lvgl/7f07a129e8d77f4984fff8e623fd5be18ff42e74";
      flake = false;
    };
    openabl-src = {
      url = "github:OpenHandheldCollective/OpenABL/59338daddd4be82712e2e72bf15cd2f480d517b4";
      flake = false;
    };
    edk2-src = {
      url = "git+https://git.codelinaro.org/clo/la/abl/tianocore/edk2.git?rev=aef4e86045bd151a54d33bab8ae5e8e62462a8f4&shallow=1";
      flake = false;
    };
    microui-src = {
      url = "github:rxi/microui/0850aba860959c3e75fb3e97120ca92957f9d057";
      flake = false;
    };
    qtestsign-src = {
      url = "github:msm8916-mainline/qtestsign/f3df53a5f0e37ccee076541f30f9d5b8340fc2d3";
      flake = false;
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    assert (import ./nix/lib/source-pins.nix { inherit inputs; }).valid;
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      imports = [
        ./nix/modules/nixos-modules.nix
        ./nix/modules/systems.nix
        ./nix/modules/packages.nix
        ./nix/modules/checks.nix
        ./nix/modules/devshell.nix
      ];
    };
}
