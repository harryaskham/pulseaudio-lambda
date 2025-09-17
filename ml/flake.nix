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

        pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope overlay;


        pal-stem-separator-venv = pythonSet.mkVirtualEnv "pal-stem-separator-venv" { inherit python; };

        util = pkgs.callPackage pyproject-nix.build.util {};

        pal-stem-separator-app = util.mkApplication {
          venv = pal-stem-separator-venv;
          package = pythonSet.pulseaudio-lambda-stem-separator;
        };

        pal-stem-separator = pythonEnv.pkgs.buildPythonPackage
          (project.renderers.buildPythonPackage { inherit python; });
      in {
        packages = rec {
          default = pal-stem-separator;
          inherit pal-stem-separator;
          inherit pal-stem-separator-app;
        };
      });
}

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
