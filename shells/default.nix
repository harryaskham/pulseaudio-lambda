{ pulseaudio-lambda, config, lib, pkgs, ... }:

rec {
  default = dev;
  dev = pkgs.callPackage ./dev.nix { inherit pulseaudio-lambda; };
  ml = pkgs.callPackage ./ml.nix {
    accelerationType = "rocm";
  };
}
