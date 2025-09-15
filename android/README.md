# Android Stem Separation App

This directory contains an Android application that wraps the PulseAudio Lambda
stem separation model and applies it to system audio. It exposes individual
volume controls for **drums**, **guitar**, **vocals**, and **other** stems.

The app captures system playback using Android's `AudioPlaybackCaptureConfiguration`
API (available on Android 10+) and processes the stream with a TorchScript
model. The resulting stems are mixed back together according to the selected
volumes and sent to the output device, effectively acting as a virtual audio
device.

## Development environment

Dependencies are managed with [Nix](https://nixos.org). To enter a shell with
the Android SDK, JDK, and Gradle, run:

```bash
nix develop
```

Inside the shell you can build and install the app using Gradle:

```bash
gradle assembleDebug
```

The stem separation model is expected at `app/src/main/assets/separation.pt` and
should be generated from the existing desktop model.
