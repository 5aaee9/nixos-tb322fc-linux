{
  config,
  lib,
  pkgs,
  ...
}:

let
  handler = pkgs.stdenv.mkDerivation {
    pname = "y700-power-key";
    version = "1";
    src = ./power-key;
    strictDeps = true;
    buildPhase = ''
      runHook preBuild
      $CC -std=c11 -O2 -Wall -Wextra -Werror power-key.c -o y700-power-key
      runHook postBuild
    '';
    doCheck = true;
    checkPhase = ''
      $CC -std=c11 -O2 -Wall -Wextra -Werror gesture-test.c -o gesture-test
      ./gesture-test
    '';
    installPhase = ''
      mkdir -p $out/bin
      cp y700-power-key $out/bin/
    '';
  };
  bridge = pkgs.writeShellApplication {
    name = "y700-power-key-session";
    runtimeInputs = [
      pkgs.systemd
      pkgs.util-linux
      pkgs.glib
      pkgs.coreutils
      pkgs.getent
    ];
    text = builtins.readFile ./power-key/session-action.sh;
  };
  action = pkgs.writeShellScript "y700-power-key-action" ''
    exec ${pkgs.coreutils}/bin/timeout --kill-after=1s 8s \
      ${bridge}/bin/y700-power-key-session "$@"
  '';
  device = "dev-input-y700_powerkey.device";
in
{
  options.services.y700-power-key.enable = lib.mkOption {
    type = lib.types.bool;
    default = config.services.desktopManager.gnome.enable;
    defaultText = lib.literalExpression "config.services.desktopManager.gnome.enable";
    description = "Handle the Y700 power key through the active local GNOME session.";
  };

  config = lib.mkIf config.services.y700-power-key.enable {
    assertions = [
      {
        assertion = config.services.desktopManager.gnome.enable;
        message = "The Y700 power-key session adapter currently requires GNOME.";
      }
    ];

    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="pmic_pwrkey", SYMLINK+="input/y700_powerkey", TAG+="systemd", ENV{SYSTEMD_ALIAS}+="/dev/input/y700_powerkey", ENV{SYSTEMD_WANTS}+="y700-power-key.service"
    '';

    # A failed/restarting handler must not expose logind's poweroff fallback.
    services.logind.settings.Login = {
      HandlePowerKey = "ignore";
      HandlePowerKeyLongPress = "ignore";
    };

    programs.dconf.profiles.user.databases = [
      {
        settings."org/gnome/settings-daemon/plugins/media-keys".power-static =
          lib.gvariant.mkEmptyArray lib.gvariant.type.string;
      }
    ];

    systemd.services.y700-power-key = {
      description = "Y700 power key display toggle and two-second power menu";
      bindsTo = [ device ];
      after = [
        device
        "systemd-logind.service"
      ];
      unitConfig = {
        ConditionKernelCommandLine = [
          "|root=usb-nbd"
          "|root=PARTLABEL=rootfs"
        ];
        StartLimitIntervalSec = 30;
        StartLimitBurst = 3;
      };
      serviceConfig = {
        Type = "exec";
        ExecStart = "${handler}/bin/y700-power-key /dev/input/y700_powerkey ${action}";
        Restart = "on-failure";
        RestartSec = 1;
        TimeoutStopSec = 5;
        KillMode = "control-group";
        ProtectSystem = "strict";
        ProtectHome = "read-only";
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictAddressFamilies = [ "AF_UNIX" ];
      };
    };

    system.build.y700PowerKey = handler;
    system.build.y700PowerKeyAction = action;
  };
}
