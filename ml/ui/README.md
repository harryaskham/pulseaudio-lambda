# Stream Separator UI

This directory contains a configuration UI for the PulseAudio Lambda Stream Separator. The UI can run in two modes:

## Features

- **Volume Controls**: Adjust gain for each stem (Drums, Bass, Vocals, Other) from 0% to 200%
- **Processing Settings**: Configure chunk size (0.1-60 seconds) and overlap (0-5 seconds)
- **Device Selection**: Choose between CPU and CUDA processing
- **Checkpoint Path**: Set the path to the ML model checkpoint file
- **Auto-save**: Automatically saves changes to the config file

## Modes

### GUI Mode (Graphical)
- Uses tkinter (built into Python)
- Full graphical interface with sliders and controls
- Works on any system with a display

### TUI Mode (Terminal)
- Uses textual library for a modern terminal interface
- Full mouse support for sliders and controls
- Works over SSH and in any terminal

## Installation

```bash
# Install all dependencies including textual for TUI mode
cd ml
uv sync

# Or if using pip:
pip install -e .

# GUI mode uses built-in tkinter, no additional dependencies needed
```

## Usage

```bash
# Auto-detect best mode (GUI if display available, otherwise TUI)
python stream_separator_ui.py

# Force GUI mode
python stream_separator_ui.py --mode gui

# Force TUI mode
python stream_separator_ui.py --mode tui

# Enable debug logging
python stream_separator_ui.py --debug
```

## Configuration

The UI reads and writes to the config file at:
- `$PA_LAMBDA_CONFIG_DIR/stream_separator_config.json` (if environment variable is set)
- `~/.config/pulseaudio-lambda/stream_separator_config.json` (default)

The stream separator automatically watches this file for changes, so adjustments in the UI are reflected immediately in the running audio processing.

## Keyboard Shortcuts

### TUI Mode
- `q`: Quit
- `s`: Save configuration
- Arrow keys: Navigate sliders
- Tab: Navigate between controls

### GUI Mode
- Standard GUI controls and mouse interaction