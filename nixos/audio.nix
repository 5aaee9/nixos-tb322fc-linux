{ pkgs, ... }:

let
  boardUcm = pkgs.runCommand "alsa-ucm-conf-tb322fc" { } ''
    mkdir -p "$out/share/alsa/ucm2"
    cp -a ${pkgs.alsa-ucm-conf}/share/alsa/ucm2/. "$out/share/alsa/ucm2/"
    chmod -R u+w "$out/share/alsa/ucm2"
    cp -a ${../vendor/tb322fc-linux/rootfs/audio/ucm2}/. "$out/share/alsa/ucm2/"
  '';
  ucmEnvironment.ALSA_CONFIG_UCM2 = "${boardUcm}/share/alsa/ucm2";
in
{
  # Keep the board routing files separate from ALSA and the desktop policy.
  systemd.user.services.wireplumber.environment = ucmEnvironment;
  systemd.user.services.pipewire.environment = ucmEnvironment;
  systemd.user.services.pipewire-pulse.environment = ucmEnvironment;
  environment.sessionVariables = ucmEnvironment;
  environment.systemPackages = [ pkgs.alsa-utils ];
}
