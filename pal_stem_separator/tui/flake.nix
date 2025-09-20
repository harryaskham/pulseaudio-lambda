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
            packages = [
              pkgs.go
            ];
          };
        };

        packages = rec {
          default = pal-stem-separator-tui;
          pal-stem-separator-tui = pkgs.buildGoModule {
            pname = "pal-stem-separator-tui";
            version = "0.1.0";
            src = ./.;
            subPackages = [ "." ];
            postPatch = ''
              rm -rf vendor || true
            '';
            vendorHash = "sha256-JGQ/UHaGj8t8G/stfcTTnGtifw8ZfbxCzByzH5METyo=";
            postInstall = ''
              # ensure consistent binary name
              if [ -d "$out/bin" ]; then
                for f in "$out/bin"/*; do
                  mv "$f" "$out/bin/pal-stem-separator-tui"
                done
              fi
            '';
          };
        };
      });
}
