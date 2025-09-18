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
            # Special case: tkinter is part of Python stdlib but needs special handling
            tkinter = python.pkgs.tkinter;
            
            # Patch stempeg to find ffmpeg binaries
            stempeg = prev.stempeg.overrideAttrs (old: {
              postInstall = (old.postInstall or "") + ''
                if [ -f $out/lib/python*/site-packages/stempeg/cmds.py ]; then
                  substituteInPlace $out/lib/python*/site-packages/stempeg/cmds.py \
                    --replace 'FFMPEG_PATH = None' 'FFMPEG_PATH = "${pkgs.ffmpeg}/bin/ffmpeg"' \
                    --replace 'FFPROBE_PATH = None' 'FFPROBE_PATH = "${pkgs.ffmpeg}/bin/ffprobe"'
                fi
              '';
            });
            
            # Ignore missing CUDA dependencies for PyTorch ecosystem
            torch = prev.torch.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            });
            torchaudio = prev.torchaudio.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            });
            torchcodec = prev.torchcodec.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            });
            sounddevice = prev.sounddevice.overrideAttrs (old: {
              nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.autoPatchelfHook ];
              buildInputs = (old.buildInputs or []) ++ [ pkgs.portaudio ];
              postInstall = (old.postInstall or "") + ''
                # Patch sounddevice to directly use our portaudio library
                substituteInPlace $out/lib/python*/site-packages/sounddevice.py \
                  --replace "for _libname in (" "for _libname in ('${pkgs.portaudio}/lib/libportaudio.so.2'," \
                  --replace "raise OSError('PortAudio library not found')" "_libname = '${pkgs.portaudio}/lib/libportaudio.so.2'"
              '';
            });
            numba = prev.numba.overrideAttrs (old: { 
              autoPatchelfIgnoreMissingDeps = true; 
            });
            
            # Ignore all NVIDIA/CUDA packages
          } // (lib.genAttrs [
            "nvidia-cublas-cu12"
            "nvidia-cuda-cupti-cu12"
            "nvidia-cuda-nvrtc-cu12"
            "nvidia-cuda-runtime-cu12"
            "nvidia-cudnn-cu12"
            "nvidia-cufft-cu12"
            "nvidia-cufile-cu12"
            "nvidia-curand-cu12"
            "nvidia-cusolver-cu12"
            "nvidia-cusparse-cu12"
            "nvidia-cusparselt-cu12"
            "nvidia-nccl-cu12"
            "nvidia-nvjitlink-cu12"
            "nvidia-nvtx-cu12"
            "triton"
          ] (name: prev.${name}.overrideAttrs (old: {
            autoPatchelfIgnoreMissingDeps = true;
          }))) // allFromNixpkgs [
            "tkinter"
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
            pal-stem-separator = pkgs.runCommand "pal-stem-separator" {
              buildInputs = [ pkgs.makeWrapper ];
              propagatedBuildInputs = with pkgs; [
                portaudio
                ffmpeg
                ffmpeg.lib
              ];
            } ''
              mkdir -p $out/bin
              
              # Create a wrapper script that preloads portaudio
              cat > $out/bin/pal-stem-separator << 'EOF'
              #!/usr/bin/env bash
              export LD_LIBRARY_PATH="${pkgs.portaudio}/lib:${pkgs.tk}/lib:${pkgs.tcl}/lib:${pkgs.ffmpeg.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              export PATH="${pkgs.ffmpeg}/bin''${PATH:+:$PATH}"
              export PYTHONPATH="${pkgs.python3Packages.tkinter}/${python.sitePackages}''${PYTHONPATH:+:$PYTHONPATH}"
              
              # Preload portaudio so sounddevice can find it
              export LD_PRELOAD="${pkgs.portaudio}/lib/libportaudio.so.2''${LD_PRELOAD:+:$LD_PRELOAD}"
              
              exec ${app}/bin/pal-stem-separator "$@"
              EOF
              
              chmod +x $out/bin/pal-stem-separator
            '';

            pal-stem-separator-gui = pkgs.writeShellScriptBin "pal-stem-separator-gui" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator --gui --ui-only "$@"
            '';

            pal-stem-separator-tui = pkgs.writeShellScriptBin "pal-stem-separator-tui" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator --tui --ui-only "$@"
            '';
          };
      });
}
