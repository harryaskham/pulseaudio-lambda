{
  description = "PulseAudio module for piping audio through external processes";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        
        pulseaudio-lambda = pkgs.stdenv.mkDerivation {
          pname = "pulseaudio-lambda";
          version = "0.1.0";
          
          src = ./.;
          
          nativeBuildInputs = with pkgs; [
            pkg-config
            gcc
            gnumake
          ];
          
          buildInputs = with pkgs; [
            makeWrapper
            pulseaudioFull
          ];
          
          buildPhase = ''
            ls -la
            ls -la src/
            make
          '';
          
          installPhase = ''
            runHook preInstall
            
            mkdir -p $out/bin
            cp pulseaudio-lambda $out/bin/
            
            mkdir -p $out/share/pulseaudio-lambda/lambdas
            cp -r lambdas/* $out/share/pulseaudio-lambda/lambdas/
            ${pkgs.busybox}/bin/chmod +x $out/share/pulseaudio-lambda/lambdas/*
            
            runHook postInstall
          '';

          postInstall = ''
            wrapProgram "$out/bin/pulseaudio-lambda" --set PATH "$PATH:$out/share/pulseaudio-lambda/lambdas"
          '';
        };
      in {
        packages.default = pulseaudio-lambda;
        devShells = pkgs.callPackage ./shells { inherit pulseaudio-lambda; };
      });
}
