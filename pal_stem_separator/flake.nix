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

        python = pkgs.python312;
        # python = pkgs.python312.override (old: {
        #   interpreter = old.withPackages (ps: with ps; [
        #     tkinter
        #   ]);
        # });

        hacks = pkgs.callPackage pyproject-nix.build.hacks {};
        pyprojectOverlay = final: prev:
          let
            fromNixpkgs1 = name: {
              ${name} = hacks.nixpkgsPrebuilt {
                from = python.pkgs.${name};
                prev = prev.${name};
              };
            };
            fromNixpkgs = names: lib.mergeAttrsList (map fromNixpkgs1 names);
            patchElfs = names: lib.genAttrs names (name: prev.${name}.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            }));
          in {
            tkinter = fromNixpkgs1 "tkinter";

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

            # Patch in portaudio for sounddevice
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
            
          } // (patchElfs [
            "torch"
            "torchaudio"
            "torchcodec"
            "executorch"
            "antlr4"
            "numba"
            #"pytorch-triton-rocm"
            #"executorch"
            # Ignore all NVIDIA/CUDA packages
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
          ]);

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
          pythonSet.mkVirtualEnv "pal_stem_separator" workspace.deps.default;

      in rec {
        devShells = {
          default = pkgs.mkShell {
            packages = with pkgs; [
              pal-stem-separator-venv
              uv
              tk
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = (pythonSet.python.withPackages (ps: [ps.tkinter])).interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              export LD_LIBRARY_PATH="${pkgs.portaudio}/lib:${pkgs.tk}/lib:${pkgs.tcl}/lib:${pkgs.ffmpeg.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              unset PYTHONPATH
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

            all = pkgs.symlinkJoin {
              name = "pal-stem-separator-all";
              paths = [
                pal-stem-separator
                pal-stem-separator-gui
                pal-stem-separator-tui
              ];
            };

            pal-stem-separator = pkgs.runCommand "pal-stem-separator" {
              propagatedBuildInputs = with pkgs; [
                makeWrapper
                app
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
                ffmpeg
                ffmpeg.lib
                tk
              ];
            } ''
              mkdir -p $out/bin
              
              # Create a wrapper script that preloads portaudio
              cat > $out/bin/pal-stem-separator << 'EOF'
              #!/usr/bin/env bash
              export LD_LIBRARY_PATH="${pkgs.portaudio}/lib:${pkgs.tk}/lib:${pkgs.tcl}/lib:${pkgs.ffmpeg.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              export PATH="${pkgs.ffmpeg}/bin''${PATH:+:$PATH}"

              # Preload portaudio so sounddevice can find it
              export LD_PRELOAD="${pkgs.portaudio}/lib/libportaudio.so.2''${LD_PRELOAD:+:$LD_PRELOAD}"
              
              exec ${app}/bin/pal-stem-separator "$@"
              EOF
              
              chmod +x $out/bin/pal-stem-separator
            '';

            pal-stem-separator-gui = pkgs.writeShellScriptBin "pal-stem-separator-gui" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator-cli --gui --ui-only "$@"
            '';

            pal-stem-separator-tui = pkgs.writeShellScriptBin "pal-stem-separator-tui" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator-cli --tui --ui-only "$@"
            '';
          };
      });
}
