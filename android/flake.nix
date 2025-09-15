{
  description = "Android app for PulseAudio Lambda stem separation";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    android-nixpkgs.url = "github:tadfisher/android-nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, android-nixpkgs }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        android-sdk = android-nixpkgs.packages.${system}.androidsdk (sdk:
          sdk
            .platforms "android-33"
            .build-tools "33.0.2"
            .platform-tools
            .cmdline-tools-latest
        );
      in {
        devShell = pkgs.mkShell {
          packages = [
            pkgs.openjdk17
            pkgs.gradle
            android-sdk
          ];
          ANDROID_SDK_ROOT = "${android-sdk}/libexec/android-sdk";
        };
      });
}
