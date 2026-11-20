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
  customListener = debug.extendModules {
    modules = [
      { services.openssh.listenAddresses = [ { addr = "192.0.2.1"; } ]; }
    ];
  };
  nativeSsh = debug.extendModules {
    modules = [
      { nixpkgs.hostPlatform = lib.mkForce pkgs.stdenv.hostPlatform.system; }
    ];
  };
  generations = debug.extendModules {
    modules = [
      self.nixosModules.generation-boot
      {
        y700.generationBoot = {
          enable = true;
          artifacts = pkgs.writeTextDir "metadata.json" "{}";
          installer = pkgs.writeShellScriptBin "y700-install-generations" "exit 0";
        };
      }
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
  e = generations.config;
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
          generations
          gnomeOnly
          ;
      };
in
assert lib.all withoutDemoUser [
  h
  c
  d
  g
  e
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
assert d.services.openssh.listenAddresses == [ ];
assert d.services.openssh.ports == [ 22 ];
assert builtins.elem 22 d.networking.firewall.allowedTCPPorts;
assert customListener.config.services.openssh.listenAddresses == [
  { addr = "192.0.2.1"; port = null; }
];
assert d.users.users.root.openssh.authorizedKeys.keys == [ ];
assert g.services.desktopManager.gnome.enable && !g.services.openssh.enable;
assert e.boot.loader.external.enable && !e.boot.loader.systemd-boot.enable;
assert !e.boot.loader.efi.canTouchEfiVariables;
assert e.services.displayManager.autoLogin.user == "owner";
assert e.boot.bootspec.extensions."org.y700.board.v1".selection == "exact-system-and-generation";
assert e.y700.generationBoot.configurationLimit == 3 && !e.y700.generationBoot.usbDebug;
assert !(g.services ? y700-power-key);
assert !g.services.displayManager.autoLogin.enable;
assert base.services.desktopManager.gnome.enable;
assert desktop.users.users.y700.uid == 1000;
assert desktop.users.users.y700.initialHashedPassword == "";
assert desktop.services.displayManager.autoLogin.enable;
assert persistent.users.users.y700.initialHashedPassword == "!";
assert persistent.services.displayManager.autoLogin.enable;
assert persistent.fileSystems."/".fsType == "btrfs";
assert desktop.fileSystems."/".fsType == "ext4";
pkgs.runCommand "y700-nixos-module-contracts"
  {
    nativeBuildInputs = [ pkgs.openssh.out ];
    receipt = builtins.toJSON evaluated;
  }
  ''
    sshd -G -f ${nativeSsh.config.environment.etc."ssh/sshd_config".source} > sshd-effective.conf
    grep -Fxi 'listenaddress [::]:22' sshd-effective.conf
    grep -Fxi 'listenaddress 0.0.0.0:22' sshd-effective.conf
    grep -Fxi 'passwordauthentication no' sshd-effective.conf
    grep -Fxi 'kbdinteractiveauthentication no' sshd-effective.conf
    printf '%s\n' "$receipt" > "$out"
  ''
