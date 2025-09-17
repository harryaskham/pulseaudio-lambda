{
  description = "PulseAudio lambda for stem-separation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pyproject-nix = {
      url = "github:nix-community/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      pyproject-nix,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        inherit (nixpkgs) lib;
        pkgs = nixpkgs.legacyPackages.${system};

        hs-tasnet =
          let
            pname = "hs_tasnet";
            version = "0.2.29";
            format = "wheel";
          in pkgs.python3Packages.buildPythonPackage {
            pname = "hs_tasnet";
            inherit version format;
            src = pkgs.fetchPypi rec {
              inherit pname version format;
              sha256 = "sha256-J1cNtyIPlmMlEO3rYgcyH7kzv7Yl0sayL0KYhs1sl8U=";
              dist = python;
              python = "py3";
            };
          };

        python = pkgs.python3.override {
          packageOverrides = self: super: {
            inherit hs-tasnet;
          };
        };

        hacks = pkgs.callPackage pyproject-nix.build.hacks {};
        overlay = final: prev: {
          torch = hacks.nixpkgsPrebuilt {
            from = python.pkgs.torchWithoutCuda;
            prev = prev.torch.overrideAttrs(old: {
              passthru = old.passthru // {
                dependencies = lib.filterAttrs (name: _: ! lib.hasPrefix "nvidia" name) old.passthru.dependencies;
              };
            });
          };
        };
        project = pyproject-nix.lib.project.loadPyproject {
          projectRoot = ./.;
        };
        pythonEnv = python.withPackages (project.renderers.withPackages {
          inherit python;
          extraPackages = _: [
            hs-tasnet
          ];
        });

        pal-stem-separator =
          let arg = project.renderers.buildPythonPackage { inherit python; };
          in pythonEnv.pkgs.buildPythonPackage (arg // {
            buildInputs = (arg.buildInputs or []) ++ (with pkgs; [
              pkg-config
              jo
              jq
              libffi
              openssl
              stdenv.cc.cc
              stdenv.cc.cc.lib
              gcc.cc
              zlib
              zlib.dev
              portaudio
            ]);
          });
      in rec {
        packages = rec {
          default = pal-stem-separator;
          inherit pal-stem-separator;
        };
        devShells = pkgs.callPackage ./shells {};
      });
}
