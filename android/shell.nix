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
  gradle_wrapped = pkgs.runCommandLocal "gradle-wrapped" {
    nativeBuildInputs = with pkgs; [ makeBinaryWrapper ];
  } ''
    mkdir -p $out/bin
    ln -s ${gradle}/bin/gradle $out/bin/gradle
    wrapProgram $out/bin/gradle \
    --add-flags "-Dorg.gradle.project.android.aapt2FromMavenOverride=''${ANDROID_SDK_ROOT}/build-tools/$buildToolsVersion/aapt2"
  '';
in
pkgs.mkShell {
  inherit buildToolsVersion;
  buildInputs = [
    jdk
    androidComposition.androidsdk
    gradle_wrapped
  ];
}
