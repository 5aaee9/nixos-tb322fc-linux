{ pkgs, ... }:

{
  systemd.services.display-manager.requires = [
    "y700-usb-nbd-sleep-policy.service"
    "y700-usb-nbd-prepare-shutdown.service"
  ];

  systemd.services.y700-usb-nbd-transport = {
    description = "Keep the initramfs NBD client alive through final shutdown";
    wantedBy = [ "multi-user.target" ];
    before = [ "y700-usb-nbd-prepare-shutdown.service" "display-manager.service" ];
    unitConfig.ConditionKernelCommandLine = "root=usb-nbd";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      read -r nbdPid < /sys/block/nbd0/pid
      case "$nbdPid" in
        ""|*[!0-9]*|0) echo "NBD root has no live client PID" >&2; exit 1 ;;
      esac
      scope=y700-usb-nbd-client.scope
      if ! systemctl is-active --quiet "$scope"; then
        busctl call org.freedesktop.systemd1 /org/freedesktop/systemd1 \
          org.freedesktop.systemd1.Manager StartTransientUnit \
          'ssa(sv)a(sa(sv))' "$scope" fail 3 \
          PIDs au 1 "$nbdPid" \
          DefaultDependencies b false \
          SurviveFinalKillSignal b true 0
      fi
      for attempt in $(seq 1 20); do
        systemctl is-active --quiet "$scope" && break
        sleep 0.1
      done
      systemctl is-active --quiet "$scope"
      test "$(cat /sys/block/nbd0/pid)" = "$nbdPid"
      group=$(systemctl show "$scope" -p ControlGroup --value)
      test -n "$group"
      grep -Fx "0::$group" "/proc/$nbdPid/cgroup"
      test "$(systemctl show "$scope" -p DefaultDependencies --value)" = no
      test "$(systemctl show "$scope" -p SurviveFinalKillSignal --value)" = yes
    '';
  };

  systemd.services.y700-usb-nbd-prepare-shutdown = {
    description = "Verify the shutdown ramfs while the NBD root is healthy";
    wantedBy = [ "multi-user.target" ];
    requires = [
      "generate-shutdown-ramfs.service"
      "y700-usb-nbd-transport.service"
    ];
    after = [
      "generate-shutdown-ramfs.service"
      "y700-usb-nbd-transport.service"
    ];
    before = [ "display-manager.service" ];
    unitConfig.ConditionKernelCommandLine = "root=usb-nbd";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      # Checking inside this root prevents an absolute symlink from silently
      # resolving against the original NBD store.
      ExecStart = "${pkgs.coreutils}/bin/chroot /run/initramfs ${pkgs.glibc}/lib/ld-linux-aarch64.so.1 --list /shutdown";
    };
  };

  # Suspending DWC3 disconnects the USB link that carries this root disk.
  # Keep this policy in RAM and limited to the temporary NBD boot.
  systemd.services.y700-usb-nbd-sleep-policy = {
    description = "Disable sleep while the root filesystem uses USB NBD";
    wantedBy = [ "multi-user.target" ];
    before = [ "systemd-logind.service" "display-manager.service" ];
    unitConfig.ConditionKernelCommandLine = "root=usb-nbd";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      read -r nbdPid < /sys/block/nbd0/pid
      case "$nbdPid" in
        ""|*[!0-9]*|0) echo "NBD root has no live client PID" >&2; exit 1 ;;
      esac
      test -d "/proc/$nbdPid"
      mkdir -p /run/systemd/sleep.conf.d
      cat > /run/systemd/sleep.conf.d/90-y700-usb-nbd.conf <<'EOF'
      [Sleep]
      AllowSuspend=no
      AllowHibernation=no
      AllowHybridSleep=no
      AllowSuspendThenHibernate=no
      EOF
    '';
  };

  systemd.services.y700-usb-nbd-sleep-inhibitor = {
    description = "Explain why the temporary USB NBD session cannot sleep";
    wantedBy = [ "multi-user.target" ];
    requires = [ "y700-usb-nbd-sleep-policy.service" ];
    after = [
      "y700-usb-nbd-sleep-policy.service"
      "systemd-logind.service"
    ];
    before = [ "display-manager.service" ];
    unitConfig.ConditionKernelCommandLine = "root=usb-nbd";
    serviceConfig.Type = "exec";
    serviceConfig.ExecStart = ''
      ${pkgs.systemd}/bin/systemd-inhibit --what=sleep --mode=block \
        --who=Y700-USB-NBD \
        --why="The temporary root filesystem requires the active USB link" \
        ${pkgs.coreutils}/bin/sleep infinity
    '';
  };
}
