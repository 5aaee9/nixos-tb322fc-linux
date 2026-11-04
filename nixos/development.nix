{ config, lib, ... }:

let
  publicKey = lib.strings.trim config.y700.debugPublicKey;
in
{
  # This module configures the temporary USB diagnostics only. It deliberately
  # does not create a local user or enable automatic login.
  imports = [ ./usb-nbd.nix ];

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

    # Root diagnostics accept only this host over the existing USB link.
    services.openssh.enable = true;
    services.openssh.listenAddresses = [
      {
        addr = "192.168.42.2";
        port = 22;
      }
    ];
    services.openssh.settings = {
      PermitRootLogin = "prohibit-password";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    };
    users.users.root.openssh.authorizedKeys.keys = lib.optionals (publicKey != "") [
      ''from="192.168.42.1",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${publicKey}''
    ];
  };
}
