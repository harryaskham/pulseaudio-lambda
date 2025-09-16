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
            make pulseaudio-lambda
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

        pulseaudio-lambda-module = pkgs.stdenv.mkDerivation {
          pname = "pulseaudio-lambda-module";
          version = "0.1.0";
          
          src = ./.;
          
          nativeBuildInputs = with pkgs; [
            pkg-config
            gcc
            gnumake
          ];
          
          buildInputs = with pkgs; [
            pulseaudioFull
            pulseaudioFull.dev
          ];
          
          buildPhase = ''
            # Set PA_CFLAGS to include pulsecore headers
            export PA_CFLAGS="$(pkg-config --cflags libpulse) -I${pkgs.pulseaudioFull.dev}/include/pulsecore -I${pkgs.pulseaudioFull.dev}/include"
            make module-lambda.so
          '';
          
          installPhase = ''
            runHook preInstall
            
            mkdir -p $out/lib/pulse-${pkgs.pulseaudioFull.version}/modules
            cp module-lambda.so $out/lib/pulse-${pkgs.pulseaudioFull.version}/modules/
            
            runHook postInstall
          '';
        };
      in {
        packages = {
          default = pulseaudio-lambda;
          binary = pulseaudio-lambda;
          module = pulseaudio-lambda-module;
        };
        devShells = pkgs.callPackage ./shells { inherit pulseaudio-lambda; };
      });
}
