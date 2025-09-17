{ packages, config, lib, pkgs, ... }:

rec {
  default = dev;
  dev = pkgs.callPackage ./dev.nix { inherit packages; };
  ml = pkgs.callPackage ./ml.nix {
    accelerationType = "rocm";
  };
}
