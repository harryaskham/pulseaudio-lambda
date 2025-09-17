{ packages, config, lib, pkgs, ... }:

rec {
  default = dev;
  dev = pkgs.callPackage ./dev.nix { inherit packages; };
}
