{
  pkgs,
  self,
  project,
}:
let
  lib = pkgs.lib;
  profiles = {
    base = self.nixosConfigurations.elden.config.system.build.toplevel;
    desktop = self.nixosConfigurations.elden-desktop.config.system.build.toplevel;
    persistent = self.nixosConfigurations.elden-persistent.config.system.build.toplevel;
  };
  mkArchive =
    profile: system:
    let
      closure = pkgs.closureInfo { rootPaths = [ system ]; };
    in
    pkgs.runCommand "y700-rootfs-${profile}-archive"
      {
        nativeBuildInputs = [
          pkgs.python3
          pkgs.nix
          pkgs.gnutar
          pkgs.gzip
        ];
      }
      ''
        export NIX_CONF_DIR="$TMPDIR/nix-conf"
        mkdir -p "$NIX_CONF_DIR"
        python ${project}/tools/build-persistent-rootfs.py \
          --system ${system} --closure-info ${closure} --profile ${profile} --out staging
        mkdir -p "$out"
        cp staging/{nixos-rootfs.tar.gz,metadata.json,SHA256SUMS,registration.txt,closure.txt} "$out/"
      '';
  archives = lib.mapAttrs mkArchive profiles;
  mkExt4 =
    profile: archive:
    pkgs.runCommand "y700-rootfs-${profile}-ext4"
      {
        nativeBuildInputs = [ pkgs.e2fsprogs ];
      }
      ''
        mkdir "$out"
        truncate -s 12G "$out/nixos-rootfs.ext4"
        export SOURCE_DATE_EPOCH=1 E2FSPROGS_FAKE_TIME=1
        mkfs.ext4 -q -F -L rootfs -U c3df3178-a68d-4d20-8df4-0827fb15b617 \
          -E lazy_itable_init=0,lazy_journal_init=0,hash_seed=c3df3178-a68d-4d20-8df4-0827fb15b617 \
          -d ${archive}/nixos-rootfs.tar.gz "$out/nixos-rootfs.ext4"
        debugfs -R 'stat /tmp' "$out/nixos-rootfs.ext4" 2>/dev/null | \
          grep -Eq 'Type: directory[[:space:]]+Mode:[[:space:]]+01777'
        debugfs -R 'stat /root' "$out/nixos-rootfs.ext4" 2>/dev/null | \
          grep -Eq 'Type: directory[[:space:]]+Mode:[[:space:]]+0700'
        for path in /tmp /root /nix/store; do
          debugfs -R "stat $path" "$out/nixos-rootfs.ext4" 2>/dev/null | \
            grep -Eq 'User:[[:space:]]+0[[:space:]]+Group:[[:space:]]+0'
        done
        e2fsck -fn "$out/nixos-rootfs.ext4"
        cp ${archive}/metadata.json "$out/rootfs-metadata.json"
        cd "$out"
        sha256sum nixos-rootfs.ext4 > SHA256SUMS
      '';
in
{
  inherit profiles archives;
  images = lib.mapAttrs mkExt4 archives;
}
