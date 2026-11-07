#!/bin/sh
# Read-only evidence over an already authenticated, physically bound USB SSH link.
set -eu
export LC_ALL=C
export PATH=/run/current-system/sw/bin:/run/current-system/systemd/bin

challenge=${1-}
case "$challenge" in ''|*[!0-9a-f]*) exit 2 ;; esac
[ "${#challenge}" = 32 ] || exit 2
[ "$(tr -d '\000' </proc/device-tree/chosen/y700,uefi-provider)" = ram-v1 ] || exit 3
[ "$(cat /sys/firmware/efi/fw_platform_size)" = 64 ] || exit 3
[ "$(cat /run/y700-root/mode)" = readonly-overlay ] || exit 3

capture() {
    record=$1
    shift
    if output=$(timeout 5 "$@" 2>&1); then
        status=0
    else
        status=$?
    fi
    if [ "${#output}" -gt 1048576 ]; then
        status=125
        output='Evidence record exceeds limit'
    fi
    printf '%s\t%s\t' "$record" "$status"
    printf '%s' "$output" | base64 -w 0
    printf '\n'
}

blocks() {
    capture "$1" sh -c '
        set -eu
        for node in /sys/class/block/*; do
            [ -d "$node" ] || continue
            partition=0
            [ ! -f "$node/partition" ] || partition=$(cat "$node/partition")
            label=$(sed -n "s/^PARTNAME=//p" "$node/uevent")
            printf "%s\t%s\t%s\t%s\t%s\n" "${node##*/}" \
                "$(cat "$node/dev")" "$(cat "$node/ro")" "$partition" "$label"
        done
    '
}

printf 'Y700_EFI_NIXOS_EVIDENCE_V1\t%s\n' "$challenge"
capture boot_id_start cat /proc/sys/kernel/random/boot_id
capture kernel uname -r
capture efi_platform cat /sys/firmware/efi/fw_platform_size
capture provider_base64 base64 /proc/device-tree/chosen/y700,uefi-provider
guid=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f
capture loader_base64 base64 "/sys/firmware/efi/efivars/LoaderInfo-$guid"
capture entry_base64 base64 "/sys/firmware/efi/efivars/LoaderEntrySelected-$guid"
capture cmdline cat /proc/cmdline
capture current_system readlink -f /run/current-system
capture pid1_exe readlink -f /proc/1/exe
capture root_mode cat /run/y700-root/mode
capture mounts_start cat /proc/1/mountinfo
blocks blocks_start
capture display_manager systemctl show display-manager.service --no-pager \
    --property=ActiveState,SubState,MainPID
capture sshd systemctl show sshd.service --no-pager --property=ActiveState,SubState
capture failed_units systemctl --failed --no-legend --no-pager --plain
capture processes ps -eo pid=,uid=,comm=
capture process_executables sh -c '
    for task in /proc/[0-9]*; do
        executable=$(readlink "$task/exe" 2>/dev/null) || continue
        case "$executable" in
            /nix/store/*-gnome-shell-*/bin/gnome-shell|/nix/store/*-gnome-shell-*/bin/.gnome-shell-wrapped)
                uid=$(awk "/^Uid:/ {print \$3}" "$task/status" 2>/dev/null) || continue
                [ -n "$uid" ] || continue
                printf "%s\t%s\t%s\n" "${task##*/}" "$uid" "$executable"
                ;;
        esac
    done
'
capture sessions loginctl list-sessions --no-legend --no-pager

# The table is only used to select bounded, syntactically safe session IDs.
if sessions=$(timeout 5 loginctl list-sessions --no-legend --no-pager 2>/dev/null); then
    count=0
    printf '%s\n' "$sessions" |
        while read -r session rest; do
            [ -n "$session" ] || continue
            case "$session" in *[!0-9A-Za-z_-]*) exit 4 ;; esac
            count=$((count + 1))
            [ "$count" -le 8 ] || exit 4
            capture "session.$session" loginctl show-session "$session" --no-pager \
                --property=Id --property=User --property=Name --property=Class \
                --property=Type --property=Active --property=State \
                --property=Remote --property=Service
        done
else
    exit 4
fi
blocks blocks_end
capture mounts_end cat /proc/1/mountinfo
capture boot_id_end cat /proc/sys/kernel/random/boot_id
printf 'Y700_EFI_NIXOS_EVIDENCE_END\n'
