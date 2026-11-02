{ lib, ... }:

let
  keyFile = builtins.getEnv "Y700_DEBUG_PUBLIC_KEY_FILE";
  publicKey =
    if keyFile == "" then ""
    else lib.strings.trim (builtins.readFile keyFile);
in
{
  imports = [ ./usb-nbd.nix ./power-key.nix ];

  assertions = [
    {
      assertion = lib.hasPrefix "ssh-ed25519 " publicKey;
      message = "elden-desktop requires Y700_DEBUG_PUBLIC_KEY_FILE with the trusted host's public key.";
    }
  ];

  # This account exists only in the disposable development rootfs.
  users.users.y700 = {
    isNormalUser = true;
    uid = 1000;
    description = "Y700 development";
    extraGroups = [ "wheel" "networkmanager" ];
    initialHashedPassword = "";
  };
  services.displayManager.autoLogin = {
    enable = true;
    user = "y700";
  };

  # Root diagnostics accept only this host over the existing USB link.
  services.openssh.listenAddresses = [
    { addr = "192.168.42.2"; port = 22; }
  ];
  services.openssh.settings.KbdInteractiveAuthentication = false;
  users.users.root.openssh.authorizedKeys.keys = [
    ''from="192.168.42.1",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${publicKey}''
  ];
}
