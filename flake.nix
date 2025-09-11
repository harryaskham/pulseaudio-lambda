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
            chmod +x $out/share/pulseaudio-lambda/lambdas/*
            
            runHook postInstall
          '';
        };
      in {
        packages.default = pulseaudio-lambda;
        
        devShells.default = pkgs.mkShell {
          inputsFrom = [ pulseaudio-lambda ];
          
          packages = with pkgs; [
            # Development tools
            gdb
            valgrind
            bear  # For compile_commands.json
            
            # Audio tools for testing
            sox
            ffmpeg
            pavucontrol
            
            # Documentation
            man-pages
            man-pages-posix
          ];
          
          shellHook = ''
            echo "PulseAudio Lambda Development Environment"
            echo "==========================================="
            echo ""
            echo "Build with: make"
            echo "Test with: make test"
            echo "Clean with: make clean"
            echo ""
            echo "Load module: pactl load-module module-lambda source_name=lambda_source sink_name=lambda_sink lambda_command=/path/to/lambda"
            echo ""
          '';
        };
      });
}
