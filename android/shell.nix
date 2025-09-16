{
  pkgs ? import <nixpkgs> {
    config.android_sdk.accept_license = true;
    config.allowUnfree = true;
  }
}:

let
  jdk = pkgs.openjdk17;
  buildToolsVersion = "34.0.0";
  androidComposition = pkgs.androidenv.composeAndroidPackages {
    buildToolsVersions = [ buildToolsVersion ];
    platformVersions = [
      "34"
      "35"
      "latest"
    ];
    systemImageTypes = [ "google_apis_playstore" ];
    abiVersions = [
      "armeabi-v7a"
    ];
  };
  gradle = pkgs.gradle.override { java = jdk; };
in
pkgs.mkShell {
  inherit buildToolsVersion;
  buildInputs = [
    jdk
    androidComposition.androidsdk
    gradle
  ];
  shellHook = ''
    export ANDROID_SDK_ROOT=${androidComposition.androidsdk}/libexec/android-sdk
    export ANDROID_HOME="$ANDROID_SDK_ROOT"
  '';
}
