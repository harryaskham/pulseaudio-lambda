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

    pal-stem-separator-tui-flake = {
      url = "path:./tui";
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
      pal-stem-separator-tui-flake,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        inherit (nixpkgs) lib;
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python312;

        hacks = pkgs.callPackage pyproject-nix.build.hacks {};
        pyprojectOverlay = final: prev:
          let
            fromNixpkgs1 = name: {
              ${name} = hacks.nixpkgsPrebuilt {
                from = python.pkgs.${name};
                prev = prev.${name};
              };
            };
            fromNixpkgsRenamed = lib.concatMapAttrs (pyName: nixName: {
              ${pyName} = hacks.nixpkgsPrebuilt {
                from = python.pkgs.${nixName};
                prev = prev.${pyName};
              };
            });
            fromNixpkgs = names: lib.mergeAttrsList (map fromNixpkgs1 names);
            patchElfs = names: lib.genAttrs names (name: prev.${name}.overrideAttrs (old: {
              autoPatchelfIgnoreMissingDeps = true;
            }));
          in {
            # Patch qt to find qt
            qtpy = prev.qtpy.overrideAttrs (old: {
              #nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.libsForQt5.wrapQtAppsHook ];
              dontWrapQtApps = true;
              propagatedBuildInputs = (old.propagatedBuildInputs or []) ++ [ pkgs.qt5.qtbase ];
            });

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
            
          } // (fromNixpkgs [
            "proxy-tools"
            "pycairo"
            "ninja"
            "setuptools"
            #"qtpy"
          ]) // (fromNixpkgsRenamed {
            "pygobject" = "pygobject3";
            "mesonpy" = "meson";
          }) // (patchElfs [
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

        deps = with pkgs; [
          pkg-config
          meson
          ninja
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
          # Py
          mypy
          ruff
          # Web GUI runtime deps for pywebview (GTK backend)
          qt5.qtbase
          qtcreator
          cairo
          gtk3
          webkitgtk_4_1
          pythonSet.pygobject
          gobject-introspection
          glib
          glib-networking
        ];

        setLD = extraDeps: ''export LD_LIBRARY_PATH="${lib.makeLibraryPath (deps ++ extraDeps)}:$LD_LIBRARY_PATH"'';

      in rec {
        devShells = {
          default = pkgs.mkShell {
            packages = with pkgs; [ pal-stem-separator-venv uv ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON_DOWNLOADS = "never";
            };

            propagatedBuildInputs = deps;

            shellHook = ''
              ${setLD []}
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
                pal-stem-separator-tui-py
              ];
            };

            pal-stem-separator = pkgs.runCommand "pal-stem-separator" {
              propagatedBuildInputs = deps ++ (with pkgs; [
                makeWrapper
                app
              ]);
              installPhase = ''
                mkdir -p $out/share/checkpoints
                cp blessed/over30s.50.ckpt $out/share/checkpoints/
              '';
            } ''

              mkdir -p $out/bin
              
              # Create a wrapper script that preloads portaudio
              cat > $out/bin/pal-stem-separator << 'EOF'
              #!/usr/bin/env bash
              #export LD_LIBRARY_PATH="${pkgs.portaudio}/lib:${pkgs.ffmpeg.lib}/lib:${pkgs.gtk3}/lib:${pkgs.webkitgtk_4_1}/lib:${pkgs.glib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              ${setLD []}
              export PATH="${pkgs.ffmpeg}/bin''${PATH:+:$PATH}"

              # Preload portaudio so sounddevice can find it
              export LD_PRELOAD="${pkgs.portaudio}/lib/libportaudio.so.2''${LD_PRELOAD:+:$LD_PRELOAD}"

              # GI and GTK environment for pywebview (GTK backend)
              export GI_TYPELIB_PATH="${pkgs.gobject-introspection}/lib/girepository-1.0:${pkgs.webkitgtk_4_1}/lib/girepository-1.0''${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
              export GIO_EXTRA_MODULES="${pkgs.glib-networking}/lib/gio/modules''${GIO_EXTRA_MODULES:+:$GIO_EXTRA_MODULES}"
              export XDG_DATA_DIRS="${pkgs.gsettings-desktop-schemas}/share:${pkgs.gtk3}/share''${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"

              # Ensure gi (PyGObject) is visible to the venv
              export PYTHONPATH="${pkgs.python312Packages.pygobject3}/lib/python3.12/site-packages''${PYTHONPATH:+:$PYTHONPATH}"

              # Set the default checkpoint path
              export PA_LAMBDA_CHECKPOINT=$out/share/checkpoints/over30s.50.ckpt
              exec ${app}/bin/pal-stem-separator "$@"
              EOF
              
              chmod +x $out/bin/pal-stem-separator
            '';

            pal-stem-separator-gui = pkgs.writeShellScriptBin "pal-stem-separator-gui" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator --gui --ui-only "$@"
            '';

            pal-stem-separator-tui = pal-stem-separator-tui-flake.packages.${system}.default;

            pal-stem-separator-tui-py = pkgs.writeShellScriptBin "pal-stem-separator-tui-py" ''
              exec ${pal-stem-separator}/bin/pal-stem-separator --tui --ui-only "$@"
            '';
          };
      });
}
