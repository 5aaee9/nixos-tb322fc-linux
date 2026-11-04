set -eu
action=$1
session=$(loginctl show-seat seat0 -p ActiveSession --value)
test -n "$session"
test "$(loginctl show-session "$session" -p Active --value)" = yes
test "$(loginctl show-session "$session" -p Seat --value)" = seat0
test "$(loginctl show-session "$session" -p Remote --value)" = no
case "$(loginctl show-session "$session" -p Type --value)" in
    wayland|x11) ;;
    *) echo "Unsupported session type" >&2; exit 1 ;;
esac
session_uid=$(loginctl show-session "$session" -p User --value)
case "$session_uid" in
    ""|*[!0-9]*|0) echo "Invalid desktop UID" >&2; exit 1 ;;
esac
session_class=$(loginctl show-session "$session" -p Class --value)
session_user=$(loginctl show-session "$session" -p Name --value)
test -n "$session_user"
case "$session_class" in
    greeter)
        case "$session_user" in
            gdm|gdm-greeter) ;;
            *) echo "Unsupported greeter account" >&2; exit 1 ;;
        esac
        ;;
    user)
        case "$session_user" in
            gdm|gdm-greeter) echo "Greeter is not a user session" >&2; exit 1 ;;
        esac
        ;;
    *) echo "Unsupported active session" >&2; exit 1 ;;
esac
test "$session_uid" = "$(id -u "$session_user")"
IFS=: read -r account_name _ account_uid _ _ session_home _ \
    <<< "$(getent passwd "$session_user")"
test "$account_name" = "$session_user"
test "$account_uid" = "$session_uid"
case "$session_home" in
    /*) ;;
    *) echo "Invalid account home" >&2; exit 1 ;;
esac

as_user() {
    # Do not send a delayed key action to a session that lost the active seat.
    test "$(loginctl show-seat seat0 -p ActiveSession --value)" = "$session"
    test "$(loginctl show-session "$session" -p Active --value)" = yes
    runuser -u "$session_user" -- env HOME="$session_home" \
        XDG_RUNTIME_DIR="/run/user/$session_uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$session_uid/bus" \
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
        if test "$session_class" != greeter &&
            test "$(loginctl show-session "$session" -p LockedHint --value)" = yes; then
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
