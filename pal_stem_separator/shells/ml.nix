let
  # venvType
  venvTypeNone = "venv-none";
  venvTypeVirtualenv = "virtualenv";
  venvTypeUv = "uv";

  # accelerationType
  accelerationTypeROCm = "rocm";
  accelerationTypeCUDA = "cuda";
in {
  pkgs ? import <nixpkgs> {},
  pythonConfig ? {
    project = builtins.pathExists ../pyproject.toml;
    package = pkgs.python313;
    venvType = venvTypeUv;
    indexUrl = "https://download.pytorch.org/whl/rocm6.4";
  },
  accelerationType ? accelerationTypeROCm,
  torchConfig ? {
    version = {
      torch = "2.8.0";
      torchaudio = "2.8.0";
    };
  },
  rocmConfig ? {
    gfxVersion = "11.0.0";
    target = "gfx1100";
    devices = "0,1";
  },
  shellHookBefore ? "",
  shellHookAfter ? "",
  extraEnvironment ? {},
}:

with pkgs.lib;

let
  # Virtual environment
  venv = rec {
    pythonFlag = {
      ${venvTypeVirtualenv} = "-p python${pythonConfig.package.version}";
      ${venvTypeUv} = "-p ${pythonConfig.package.version}";
    }.${pythonConfig.venvType};

    indexFlag = {
      ${venvTypeVirtualenv} = "--index-url ${pythonConfig.indexUrl}";
      ${venvTypeUv} = "--index ${pythonConfig.indexUrl} --index-strategy unsafe-best-match";
    }.${pythonConfig.venvType};

    extraFlag = {
      ${venvTypeVirtualenv} = "";
      ${venvTypeUv} = "--extra ${accelerationType}";
    }.${pythonConfig.venvType};

    createCommand = {
      ${venvTypeVirtualenv} = "python -m venv ${pythonFlag} ${indexFlag}";
      ${venvTypeUv} = "uv venv ${pythonFlag} ${indexFlag}";
    }.${pythonConfig.venvType};

    installCommand = {
      ${venvTypeVirtualenv} = "pip install -U --pre ${indexFlag}";
      ${venvTypeUv} =
        if pythonConfig.project
        then "uv add ${pythonFlag} ${indexFlag}"
        else "uv pip install ${pythonFlag} ${indexFlag}";
    }.${pythonConfig.venvType};

    dir = ".venv";
    shellHook = optionalString (pythonConfig.venvType != venvTypeNone) ''
      if test ! -d ${dir}; then
        ${createCommand} ${dir}
      fi
      source ./${dir}/bin/activate
    '';
  };

  torchShellHook = ''
    ${venv.installCommand} ${
      concatStringsSep " "
        (mapAttrsToList
          (name: version: "${name}==${version}")
          (filterAttrs (_: v: v != null) torchConfig.version))
    }
  '';

  # Acceleration-specific setup
  acceleration = {
    null = {};
    cpu = {};

    ${accelerationTypeROCm} = {
      packages = with pkgs; [
        zlib
        zlib.dev
        zstd
        stdenv.cc.cc
        stdenv.cc.cc.lib
      ];
      extraEnvironment = {
        HIP_VISIBLE_DEVICES = rocmConfig.devices;
        HCC_AMDGPU_TARGET = rocmConfig.target;
        HSA_OVERRIDE_GFX_VERSION = rocmConfig.gfxVersion;
        GPUS_ARCH = rocmConfig.target;
        PYTORCH_ROCM_ARCH = rocmConfig.target;
      };
    };

    ${accelerationTypeCUDA} = {
      packages = with pkgs; [
        cudaPackages.cudatoolkit
        linuxPackages.nvidia_x11
        stdenv.cc.cc
        stdenv.cc.cc.lib
      ];
      extraEnvironment = {
        EXTRA_LDFLAGS = "-L/lib -L${linuxPackages.nvidia_x11}/lib";
        EXTRA_CCFLAGS = "-I/usr/include";
      };
      shellHook = with pkgs; ''
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$NIX_LD_LIBRARY_PATH"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$CUDA_PATH"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/run/opengl-driver/lib"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${linuxPackages.nvidia_x11}/lib"
        export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${ncurses5}/lib"
      '';
    };
  }.${accelerationType};

  pyPkgs = ps: with ps; [
    pip
    virtualenv
    uv

    torch
  ];
in pkgs.mkShell (rec {
  buildInputs = (with pkgs; [
    pkg-config
    (pythonConfig.package.withPackages pyPkgs)
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
  ]) ++ (acceleration.packages or []);

  UV_INDEX_FLAG = venv.indexFlag;
  UV_PYTHON_FLAG = venv.pythonFlag;

  shellHook = ''
    ${shellHookBefore}
    export GITSTATUS_LOG_LEVEL=DEBUG
    ${venv.shellHook}
    ${acceleration.shellHook or ""}
    ${optionalString (torchConfig != null) torchShellHook}

    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:${pkgs.ffmpeg.lib}/lib"

    function uv-nix() {
      uv $@ $UV_PYTHON_FLAG
    }
    ${optionalString (!pythonConfig.project) "${venv.installCommand} -r requirements.txt"}
    ${shellHookAfter}
  '';

} // extraEnvironment // (acceleration.extraEnvironment or {}))
