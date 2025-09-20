# paλ-stem-separator

- `pal-stem-separator` operates on stdin/out and applies a stem separation ML model to raw PCM data
- `pal-stem-separator-{gui,tui}` used to live-control stem volume
- Exposed in `pulseaudio-lambda` as `stem-separator` for use as a PulseAudio module via:
  - `pulseaudio-lambda stem-separator`