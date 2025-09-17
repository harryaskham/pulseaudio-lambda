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
        python = pkgs.python3;
        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "sdist";
        };
        hacks = pkgs.callPackage pyproject-nix.build.hacks {};
        pyprojectOverrides = _final: _prev: {
          #inherit hs-tasnet;
          torch = hacks.nixpkgsPrebuilt {
            from = pkgs.python3Packages.torchWithoutCuda;
            prev = _prev.torch;
          };
        };
        pythonSet =
          (pkgs.callPackage pyproject-nix.build.packages {
            inherit python;
          }).overrideScope
            (
              lib.composeManyExtensions [
                pyproject-build-systems.overlays.default
                overlay
                pyprojectOverrides
              ]
            );
        pulseaudio-lambda-pal-stem-separator-venv =
          pythonSet.mkVirtualEnv "pulseaudio-lambda-pal-stem-separator-venv" workspace.deps.default;
      in {
        packages.default = pulseaudio-lambda-pal-stem-separator-venv;
        apps.default = {
          type = "app";
          program = "${pulseaudio-lambda-pal-stem-separator-venv}/bin/pal-stem-separator";
        };
        # Devshell still managed by parent flake
        # TODO: move here
        #devShells = {};
      });
}

        #hs-tasnet =
        #  let version = "0.2.29";
        #  in pkgs.python3Packages.toPythonPackage {
        #    src = pkgs.fetchFromGitHub {
        #      owner = "lucidrains";
        #      repo = "HS-TasNet";
        #      rev = "refs/tags/${version}";
        #      hash = "sha256-vtYSOfUmOvULLBULtabL15D82QxC2I00RbvCDrCoI3w=";
        #    };
        #  };
        #project = pyproject-nix.lib.project.loadPyproject {
        #  projectRoot = ./.;
        #};
        #hacks = pkgs.callPackage pyproject-nix.build.hacks {};
        #overlay = final: prev: {
        #  torch = hacks.nixpkgsPrebuilt {
        #    from = pkgs.python3Packages.torchWithoutCuda;
        #    prev = prev.torch;
        #  };
        #  #inherit hs-tasnet;
        #};

        #pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
        #  inherit python;
        #}).overrideScope overlay;

        ## Returns an attribute set that can be passed to `buildPythonPackage`.
        #attrs = project.renderers.buildPythonPackage { inherit python; };
        #pulseaudio-lambda-stem-separator = python.pkgs.buildPythonPackage (attrs // {
        #  env.CUSTOM_ENVVAR = "hello";
        #});
      #in {
      #  packages = {
      #    default = pulseaudio-lambda-stem-separator;
      #    inherit pulseaudio-lambda-stem-separator;
      #  };
      #});
