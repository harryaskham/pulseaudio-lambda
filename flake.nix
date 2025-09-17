{
  description = "PulseAudio module for piping audio through external processes";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pal-stem-separator = {
      url = "path:./ml";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, pal-stem-separator, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        pal-stem-separator-pkg = pal-stem-separator.packages.${system}.default;

        pulseaudio-lambda-cli = pkgs.stdenv.mkDerivation {
          pname = "pulseaudio-lambda-cli";
          version = "0.1.0";
          
          src = ./.;
          
          nativeBuildInputs = with pkgs; [
            pkg-config
            gcc
            gnumake
          ];
          
          buildInputs = with pkgs; [
            makeWrapper
          ];

          propagatedBuildInputs = with pkgs; [
            pal-stem-separator-pkg
            pulseaudioFull
            pulseaudioFull.dev
            ffmpeg
            ffmpeg.lib
            portaudio
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
            pkg-config
            pulseaudioFull
            pulseaudioFull.dev
          ];
          
          preConfigure = ''
            tar -xvf ${pkgs.pulseaudioFull.src}
            mv pulseaudio-* pulseaudio-src
            chmod +w -Rv pulseaudio-src
            cp ${pkgs.pulseaudioFull.dev}/include/pulse/config.h pulseaudio-src
            appendToVar configureFlags "PULSE_DIR=$(realpath ./pulseaudio-src)"
          '';
          
          buildPhase = ''
            export PA_CFLAGS="$(pkg-config --cflags libpulse) -I$PULSE_DIR/include/pulsecore -I$PULSE_DIR/include"
            make module-lambda.so
          '';
          
          installPhase = ''
            runHook preInstall

            mkdir -p $out/lib/pulseaudio/modules $out/libexec/pulsaudio-lambda-module $out/etc/xdg/autostart
            cp module-lambda.so $out/lib/pulseaudio/modules/
            install -m 755 module-lambda.so $out/lib/pulseaudio/modules/

            runHook postInstall
          '';
        };

        pulseaudio-lambda = pkgs.symlinkJoin {
          name = "pulseaudio-lambda";
          paths = [
            pulseaudio-lambda-cli
          ];
          buildInputs = [ pkgs.makeWrapper ];
          propagatedBuildInputs = with pkgs; [
            ffmpeg
            ffmpeg.lib
            portaudio
            pal-stem-separator-pkg
          ];
          postBuild = ''
            wrapProgram $out/bin/pulseaudio-lambda \
              --prefix LD_LIBRARY_PATH : "${pkgs.tk}/lib:${pkgs.tcl}/lib:${pkgs.ffmpeg.lib}/lib:${pkgs.portaudio}/lib" \
              --prefix PATH : "${pkgs.ffmpeg}/bin"
          '';
        };

        packages = {
          default = pulseaudio-lambda;
          inherit pulseaudio-lambda pulseaudio-lambda-cli pulseaudio-lambda-module;
        };
      in {
        inherit packages;
        devShells = pkgs.callPackage ./shells { inherit packages; };
      });
}
