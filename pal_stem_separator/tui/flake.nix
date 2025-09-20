{
  description = "TUI for controlling PulseAudio Lambda stem separation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        inherit (nixpkgs) lib;
        pkgs = nixpkgs.legacyPackages.${system};
      in rec {
        devShells = {
          default = pkgs.mkShell {
            packages = [ self.packages.${system}.pal-stem-separator-tui ];
          };
        };

        packages = rec {
          default = pal-stem-separator-tui;
          pal-stem-separator-tui = pkgs.buildGoModule {
            pname = "pal-stem-separator-tui";
            version = "0.1.0";
            src = ./.;
            vendorHash = "sha256:${lib.fakeSha256}";
          };
        };
      });
}
