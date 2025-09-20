Agents Overview

- Repo UIs
  - Go TUI (`./tui`): Bubble Tea/Lip Gloss terminal UI. Built/run via `nix run ./tui`. Edits config and displays live stats.
  - Web GUI (`pal_stem_separator/ui/web.py`): Starlette single-page UI. Exposes `/api/config`, `/api/update`, and `/api/stats`; opens a browser or native window when launched via the app entrypoint.
  - Textual TUI (`pal_stem_separator/ui/tui.py`): Rich terminal UI for configuration (no stats panel).

- Config/Stats Files (respect `PA_LAMBDA_CONFIG_DIR`)
  - `stream_separator_config.json`: user settings (gains, mute/solo, chunk/overlap, device, normalize, checkpoint, etc.).
  - `stream_separator_stats.json`: cumulative stats and latest latency written by the streaming pipeline.

- Runtime
  - The main app (`app/main.py`) spawns audio I/O + inference threads and a stats aggregator that writes `stream_separator_stats.json`.
  - UIs read/write the config; stats are read-only for display.

- Development Notes
  - Keep Go TUI dependencies minimal; indicators use Lip Gloss (no extra Bubbles beyond textinput).
  - Web GUI polls `/api/stats` every 1s and renders basic bars and labels.
  - If you change the stats schema, update both UIs accordingly.
