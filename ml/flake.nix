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

        # Base Python interpreter
        python = pkgs.python3;

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
            hs-tasnet = pkgs.python3Packages.buildPythonPackage {
              pname = "hs_tasnet";
              version = "0.2.29";
              format = "wheel";
              src = pkgs.fetchPypi {
                pname = "hs_tasnet";
                version = "0.2.29";
                format = "wheel";
                sha256 = "sha256-J1cNtyIPlmMlEO3rYgcyH7kzv7Yl0sayL0KYhs1sl8U=";
                dist = "py3";
                python = "py3";
              };
            };
            tkinter = python.pkgs.tkinter;
            torch = hacks.nixpkgsPrebuilt {
              from = python.pkgs.torchWithoutCuda;
              prev = prev.torch.overrideAttrs(old: {
                passthru = old.passthru // {
                  dependencies = lib.filterAttrs (name: _: ! lib.hasPrefix "nvidia" name) old.passthru.dependencies;
                };
              });
            };
            torchcodec = prev.torchcodec.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.autoPatchelfHook ];
              buildInputs = (old.buildInputs or []) ++ [ 
                pkgs.ffmpeg 
                python.pkgs.torch
                pkgs.stdenv.cc.cc.lib
              ];
              autoPatchelfIgnoreMissingDeps = true;
            });
            sounddevice = prev.sounddevice.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.autoPatchelfHook ];
              buildInputs = (old.buildInputs or []) ++ [ 
                pkgs.portaudio
              ];
            });
          } // allFromNixpkgs [
            "numba"
            "torchaudio"
            "torchvision"
            "triton"
            "einops"
            "sounddevice"
            "soundfile"
            "accelerate"
            "scipy"
            "scikit-learn"
            "matplotlib"
            "loguru"
            "matplotlib"
            "librosa"
            "einx"
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
            workspace.deps.default;
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
              tk
            ];

            packages = [
              pal-stem-separator-venv
              pkgs.python3Packages.tkinter
              pkgs.uv
              pkgs.tk
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${pkgs.ffmpeg.lib}/lib"
              #unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        };

        packages =
          let
            inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;
            app = mkApplication {
              venv = pal-stem-separator-venv;
              package = pythonSet.pal-stem-separator;
            };
          in rec {
            default = pal-stem-separator;
            pal-stem-separator = pkgs.symlinkJoin {
              name = "pal-stem-separator";
              paths = [ app ];
              buildInputs = [ pkgs.makeWrapper ];
              postBuild = ''
                wrapProgram $out/bin/pal-stem-separator \
                  --set PYTHONPATH "${pkgs.python3Packages.tkinter}/${python.sitePackages}:$PYTHONPATH" \
                  --prefix LD_LIBRARY_PATH : "${pkgs.tk}/lib:${pkgs.tcl}/lib"
              '';
            };
          };
      });
}
