set -eu -o pipefail
udevadm settle --timeout=10
grep -Fxq 'lenovo,elden' < <(tr '\000' '\n' </proc/device-tree/compatible)
listing=$(lsblk --raw --noheadings --output NAME,PARTLABEL)
matches=()
while read -r name label; do
    if [[ $label == linux-esp ]]; then matches+=("$name"); fi
done <<< "$listing"
if (( ${#matches[@]} != 1 )); then
    echo "Expected one linux-esp partition; found ${#matches[@]}" >&2
    exit 1
fi
device=/dev/${matches[0]}
node=$(readlink -e "/sys/class/block/${matches[0]}")
[[ $node == /sys/devices/platform/soc@0/1d84000.ufs/*/block/*/* && -f $node/partition ]]
root=$(findmnt -n -o SOURCE --mountpoint /)
root=${root%%\[*}
[[ -b $root && $(lsblk -dnro PARTLABEL "$root") == rootfs ]]
[[ $(lsblk -dnro PKNAME "$root") == "$(lsblk -dnro PKNAME "$device")" ]]
[[ $(blockdev --getro "$root") == 0 && $(findmnt -n -o VFS-OPTIONS /) == rw,* ]]
[[ $(lsblk -dnro PARTTYPE "$device") == c12a7328-f81f-11d2-ba4b-00a0c93ec93b ]]
[[ $(blkid -p -s TYPE -o value "$device") == vfat ]]
[[ $(blockdev --getro "$device") == 1 ]]
ln -s "$device" /run/y700-esp/device
trap 'blockdev --setro "$device"' EXIT
blockdev --setrw "$device"
[[ $(blockdev --getro "$device") == 0 ]]
trap - EXIT
