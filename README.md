# PulseAudio Lambda

A bridge for applying arbitrary stdin/stdout transformations to PCM data from pulseaudio.
Makes it straightforward to do polyglot sound processing i.e. write a fast CPU filter in Rust, chain it with some Python ML model, etc, without needing to update PulseAudio's modules.

Usage is: `pulseaudio-lambda --source=... --sink=... <command>` where `command` should spawn
a process that takes PCM data from stdin and outputs PCM data to stdout. It will execute with the sample rate, channels, etc stored in the env. See the `lambdas` directory for examples.

## Example: Stem Separation

Main use-case for me is doing live stem-separation to remove drums from system audio for playing along, which is just:

`pulseaudio-lambda stem-separator`

or 

`nix run github:harryaskham/pulseaudio-lambda -- stem-separator`

(TODO: add video)

## In progress

- [ ] Android + Torchscript frontend
- [ ] Larger dataset -> better stem separation model
