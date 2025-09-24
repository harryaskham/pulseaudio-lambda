{
  description = "TUI for controlling PulseAudio Lambda stem separation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pal-stem-separator = {
      #url = "path:./..";
      url = "github:harryaskham/pulseaudio-lambda?dir=pal_stem_separator&lfs=1";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pal-stem-separator-tui-flake.follows = "";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      pal-stem-separator,
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
            buildInputs = [ pkgs.makeWrapper ];
            postPatch = ''
              rm -rf vendor || true
            '';
            # Updated after adding bubbles/viewport
            vendorHash = "sha256-ZpLb3lZy3vmiHJbniWdJOxej+v3ZO6Isw4cR90/wRpc=";
            postInstall = ''
              # ensure consistent binary name
              if [ -d "$out/bin" ]; then
                for f in "$out/bin"/*; do
                  mv "$f" "$out/bin/pal-stem-separator-tui"
                done
              fi
            '';
            postFixup = ''
              wrapProgram $out/bin/pal-stem-separator-tui \
                --set PA_LAMBDA_CHECKPOINT ${pal-stem-separator.packages.${system}.pal-stem-separator-checkpoint}/share/checkpoints/over30s.50.ckpt
            '';
          };
        };
      });
}
