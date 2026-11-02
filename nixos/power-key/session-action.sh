set -eu
action=$1
session=$(loginctl show-seat seat0 -p ActiveSession --value)
test -n "$session"
test "$(loginctl show-session "$session" -p User --value)" = "@UID@"
test "$(loginctl show-session "$session" -p Active --value)" = yes

as_user() {
    runuser -u @USER@ -- env HOME=/home/@USER@ \
        XDG_RUNTIME_DIR=/run/user/@UID@ \
        DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/@UID@/bus \
        "$@"
}
display_set() {
    as_user gdbus call --session --timeout 2 \
        --dest org.gnome.Mutter.DisplayConfig \
        --object-path /org/gnome/Mutter/DisplayConfig \
        --method org.freedesktop.DBus.Properties.Set \
        org.gnome.Mutter.DisplayConfig PowerSaveMode "<int32 $1>" >/dev/null
}
case "$action" in
    toggle)
        mode=$(as_user gdbus call --session --timeout 2 \
            --dest org.gnome.Mutter.DisplayConfig \
            --object-path /org/gnome/Mutter/DisplayConfig \
            --method org.freedesktop.DBus.Properties.Get \
            org.gnome.Mutter.DisplayConfig PowerSaveMode)
        case "$mode" in
            '(<0>,)') display_set 3; echo "Display off" ;;
            '(<1>,)'|'(<2>,)'|'(<3>,)') display_set 0; echo "Display on" ;;
            *) echo "Unsupported display power state: $mode" >&2; exit 1 ;;
        esac
        ;;
    menu)
        display_set 0
        if test "$(loginctl show-session "$session" -p LockedHint --value)" = yes; then
            echo "Locked session: display on; power dialog withheld"
            exit 0
        fi
        # Shutdown replies after the user decides; do not hold the key handler
        # while the confirmation dialog is open or treat Cancel as an error.
        as_user busctl --user --timeout=2s --expect-reply=no call \
            org.gnome.SessionManager /org/gnome/SessionManager \
            org.gnome.SessionManager Shutdown
        echo "Power menu requested"
        ;;
    *) exit 2 ;;
esac
