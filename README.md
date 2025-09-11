# pulseaudio-lambda

A plugin system for applying arbitrary functions over waveforms to PulseAudio streams.

This module allows you to write audio filters as arbitrary binaries that operate over stdin/stdout, and chain them between PulseAudio sources and sinks to act as real-time audio filters.