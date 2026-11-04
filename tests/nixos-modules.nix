{
  inputs,
  self,
  pkgs,
}:

let
  lib = inputs.nixpkgs.lib;
  headless = lib.nixosSystem {
    modules = [
      self.nixosModules.default
      { system.stateVersion = "26.05"; }
    ];
  };
  custom = headless.extendModules {
    modules = [
      self.nixosModules.gnome
      {
        networking.hostName = "my-tablet";
        fileSystems."/".device = "/dev/disk/by-label/custom-root";
        users.users.owner = {
          isNormalUser = true;
          uid = 1234;
          home = "/srv/users/owner";
          extraGroups = [ "networkmanager" ];
        };
        services.displayManager.autoLogin = {
          enable = true;
          user = "owner";
        };
      }
    ];
  };
  debug = custom.extendModules {
    modules = [
      self.nixosModules.development
      self.nixosModules.persistent
      { y700.debugPublicKey = ""; }
    ];
  };
  gnomeOnly = lib.nixosSystem {
    modules = [
      self.nixosModules.gnome
      {
        nixpkgs.hostPlatform = "aarch64-linux";
        system.stateVersion = "26.05";
        boot.loader.grub.enable = false;
        fileSystems."/" = {
          device = "/dev/disk/by-label/example";
          fsType = "ext4";
        };
      }
    ];
  };
  h = headless.config;
  c = custom.config;
  d = debug.config;
  g = gnomeOnly.config;
  base = self.nixosConfigurations.elden.config;
  desktop = self.nixosConfigurations.elden-desktop.config;
  persistent = self.nixosConfigurations.elden-persistent.config;
  withoutDemoUser = config: !(config.users.users ? y700);
  # Evaluate full toplevel derivations without building an ARM64 system in
  # this host check. This forces unit generation and NixOS assertions too.
  evaluated =
    lib.mapAttrs
      (_: system: builtins.unsafeDiscardStringContext system.config.system.build.toplevel.drvPath)
      {
        inherit
          headless
          custom
          debug
          gnomeOnly
          ;
      };
in
assert lib.all withoutDemoUser [
  h
  c
  d
  g
  base
];
assert h.nixpkgs.hostPlatform.system == "aarch64-linux";
assert !h.services.desktopManager.gnome.enable;
assert !h.services.displayManager.enable;
assert !h.services.openssh.enable;
assert !h.services.y700-power-key.enable;
assert !(h.systemd.services ? display-manager);
assert !(h.systemd.user.services ? pipewire);
assert !(h.systemd.user.services ? wireplumber);
assert !h.boot.initrd.enable && !h.boot.loader.systemd-boot.enable;
assert !h.boot.loader.grub.enable && !h.boot.loader.efi.canTouchEfiVariables;
assert c.networking.hostName == "my-tablet";
assert c.fileSystems."/".device == "/dev/disk/by-label/custom-root";
assert c.users.users.owner.uid == 1234;
assert c.services.displayManager.gdm.enable && c.services.desktopManager.gnome.enable;
assert c.services.pipewire.enable && c.services.y700-power-key.enable;
assert !c.services.openssh.enable;
assert c.services.displayManager.autoLogin.user == "owner";
assert d.services.displayManager.autoLogin.enable;
assert d.services.displayManager.autoLogin.user == "owner";
assert d.services.openssh.enable && !d.services.openssh.settings.PasswordAuthentication;
assert
  d.services.openssh.listenAddresses == [
    {
      addr = "192.168.42.2";
      port = 22;
    }
  ];
assert d.users.users.root.openssh.authorizedKeys.keys == [ ];
assert g.services.desktopManager.gnome.enable && !g.services.openssh.enable;
assert !(g.services ? y700-power-key);
assert !g.services.displayManager.autoLogin.enable;
assert base.services.desktopManager.gnome.enable;
assert desktop.users.users.y700.uid == 1000;
assert desktop.users.users.y700.initialHashedPassword == "";
assert desktop.services.displayManager.autoLogin.enable;
assert persistent.users.users.y700.initialHashedPassword == "!";
assert !persistent.services.displayManager.autoLogin.enable;
pkgs.runCommand "y700-nixos-module-contracts"
  {
    receipt = builtins.toJSON evaluated;
  }
  ''
    printf '%s\n' "$receipt" > "$out"
  ''
