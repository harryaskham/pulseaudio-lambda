{ packages, config, lib, pkgs, ... }:

rec {
  default = cpu;
  cpu = pkgs.callPackage ./ml.nix {accelerationType = "cpu";};
  rocm = pkgs.callPackage ./ml.nix {accelerationType = "rocm";};
  cuda = pkgs.callPackage ./ml.nix {accelerationType = "cuda";};
}
