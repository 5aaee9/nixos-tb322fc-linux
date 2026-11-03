{ config, lib, ... }:

let
  publicKey = lib.strings.trim config.y700.debugPublicKey;
in
{
  imports = [
    ./usb-nbd.nix
    ./power-key.nix
  ];

  options.y700.debugPublicKey = lib.mkOption {
    type = lib.types.str;
    default = "";
    description = "Trusted host ed25519 public key; empty disables root USB SSH.";
  };

  config = {
    assertions = [
      {
        assertion = publicKey == "" || lib.hasPrefix "ssh-ed25519 " publicKey;
        message = "y700.debugPublicKey must be empty or an ed25519 public key.";
      }
    ];

    # This account exists only in the disposable development rootfs.
    users.users.y700 = {
      isNormalUser = true;
      uid = 1000;
      description = "Y700 development";
      extraGroups = [
        "wheel"
        "networkmanager"
      ];
      initialHashedPassword = "";
    };
    services.displayManager.autoLogin = {
      enable = true;
      user = "y700";
    };

    # Root diagnostics accept only this host over the existing USB link.
    services.openssh.listenAddresses = [
      {
        addr = "192.168.42.2";
        port = 22;
      }
    ];
    services.openssh.settings.KbdInteractiveAuthentication = false;
    users.users.root.openssh.authorizedKeys.keys = lib.optionals (publicKey != "") [
      ''from="192.168.42.1",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${publicKey}''
    ];
  };
}
