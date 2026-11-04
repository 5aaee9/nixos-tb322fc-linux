{ ... }:

{
  # This account is only for the repository's attended development profile.
  # Reusable modules never import this profile.
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
}
