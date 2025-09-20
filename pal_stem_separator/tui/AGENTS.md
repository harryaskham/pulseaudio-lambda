Agent Notes: TUI

- Role: Interactive terminal UI (Bubble Tea + Lip Gloss) for configuring and monitoring the PulseAudio Lambda stem separator.
- Reads/writes config: `~/.config/pulseaudio-lambda/stream_separator_config.json` (or `PA_LAMBDA_CONFIG_DIR`). Saves are debounced.
- Reads live stats: `~/.config/pulseaudio-lambda/stream_separator_stats.json` and renders latency, throughput, and real‑time factor.
- Build/run: `nix run ./tui` launches the Go TUI (alt-screen); quit with `q`.

UI Overview

- Live Stats: latency bar (green/amber/red), input/output kB/s, and processing speed bar (RTF).
- Stem Volumes: four sliders (Drums, Bass, Vocals, Other) with Mute/Solo toggles and reset.
- Processing: chunk size, overlap, device (CPU/CUDA), normalization, and an "Empty Queues" action.
- Model: checkpoint path text input.
- Save: explicit save button and hotkey.

Focus/Keys

- Arrows: navigate/adjust. Enter/Space: toggle selected control. `s`: save, `r`: reset volumes, `e`: empty queues, `q`: quit.

Notes for Contributors

- Stats are polled every 1s via a Bubble Tea tick; the TUI computes simple rates from deltas and renders compact bars with Lip Gloss.
- Avoid new module dependencies; vendor includes Bubble Tea + Bubbles textinput + Lip Gloss. Keep indicators custom/lightweight.
- Config/stat paths also respect `PA_LAMBDA_CONFIG_DIR`.
