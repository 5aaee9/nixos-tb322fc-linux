{ lib, ... }:

{
  # The repository's persistent test profile owns this account policy. It is
  # deliberately not part of any exported hardware or desktop module.
  users.users.y700.initialHashedPassword = lib.mkForce "!";
  services.displayManager.autoLogin.enable = lib.mkForce false;
}
