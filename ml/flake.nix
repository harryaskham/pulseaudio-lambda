{
  description = "PulseAudio lambda for stem-separation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pyproject-nix = {
      url = "github:nix-community/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      uv2nix,
      pyproject-nix,
      pyproject-build-systems,
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
        pyprojectOverlay = final: prev:
          let
            fromNixpkgs = name: {
              ${name} = hacks.nixpkgsPrebuilt {
                from = python.pkgs.${name};
                prev = prev.${name};
              };
            };
            allFromNixpkgs = names: lib.mergeAttrsList (map fromNixpkgs names);
          in {
            inherit hs-tasnet;
            torch = hacks.nixpkgsPrebuilt {
              from = python.pkgs.torchWithoutCuda;
              prev = prev.torch.overrideAttrs(old: {
                passthru = old.passthru // {
                  dependencies = lib.filterAttrs (name: _: ! lib.hasPrefix "nvidia" name) old.passthru.dependencies;
                };
              });
            };
          } // allFromNixpkgs [
            "numba"
            "torchaudio"
            "torchvision"
            "triton"
          ];

        pythonBase = pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        };

        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };


        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        pythonSet = pythonBase.overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.wheel
            overlay
            pyprojectOverlay
          ]
        );

        pal-stem-separator-venv =
          pythonSet.mkVirtualEnv "pal_stem_separator"
            (workspace.deps.default // { torch = []; });
      in {
        devShells = {
          default = pkgs.mkShell {
            buildInputs = with pkgs; [
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
            ];

            packages = [
              pal-stem-separator-venv
              pkgs.uv
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        };

        packages =
          let
            inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;
          in rec {
            pal-stem-separator = mkApplication {
              venv = pal-stem-separator-venv;
              package = pythonSet.pal_stem_separator;
            };
            default = pal-stem-separator;
          };
      });
}
/*


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
*/
