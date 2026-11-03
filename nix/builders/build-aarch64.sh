if [[ "$(uname -m)" == aarch64 ]]; then
    exec nix build --extra-experimental-features "nix-command flakes" "$@"
fi
if [[ "${Y700_BINFMT_NAMESPACE:-}" != 1 ]]; then
    export Y700_QEMU_CLOSURE
    Y700_QEMU_CLOSURE="$(nix-store -qR @qemu@ | tr '\n' ' ')"
    export Y700_BINFMT_NAMESPACE=1
    exec unshare -Ur -m "$0" "$@"
fi
mount --make-rprivate /
binfmt_dir="$(mktemp -d)"
trap 'umount "$binfmt_dir"; rmdir "$binfmt_dir"' EXIT
mount -t binfmt_misc binfmt_misc "$binfmt_dir"
printf '%s\n' ':y700-aarch64:M::\x7f\x45\x4c\x46\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:@qemu@/bin/qemu-aarch64:OPF' > "$binfmt_dir/register"
nix build --extra-experimental-features "nix-command flakes" \
    --option extra-platforms aarch64-linux --option build-users-group "" \
    --option require-drop-supplementary-groups false \
    --option extra-sandbox-paths "$Y700_QEMU_CLOSURE" "$@"
