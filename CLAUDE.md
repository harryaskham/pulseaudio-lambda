# AGENT.md

This file provides guidance to ML Agents when working with code in this repository.

## Build and Development Commands

### Nix Development Environment (Recommended)
```bash
nix develop               # Enter development environment with all dependencies
make                      # Build the pulseaudio-lambda client executable  
make clean               # Clean build artifacts
nix build                # Build the full Nix package
```

### Manual Build (Non-Nix)
```bash
# Install dependencies first (Ubuntu/Debian):
# sudo apt install build-essential pkg-config libpulse-dev libpulse-simple-dev

make                      # Build client executable
make module              # Build PulseAudio module (requires pulsecore headers)
make test                # Test build and show usage instructions
make help                # Show all available targets
```

### Testing
```bash
# Basic functionality test
./pulseaudio-lambda ./lambdas/identity.sh

# List available audio devices
pactl list sources short    # Find audio sources
pactl list sinks short      # Find audio sinks

# Specify devices explicitly
./pulseaudio-lambda --source=SOURCE_NAME --sink=SINK_NAME ./lambdas/LAMBDA_SCRIPT

# Test lambda examples
./pulseaudio-lambda ./lambdas/drumless.sh       # Drum removal filter
./pulseaudio-lambda ./lambdas/speech.sh         # Speech enhancement
```

## Architecture Overview

### Core Components

**pulseaudio-lambda** - Main executable that bridges PulseAudio with external processes:
- `src/pulseaudio-lambda.c` - Client implementation using PulseAudio Simple API
- `src/module-lambda.c` - Alternative PulseAudio module implementation (requires pulsecore)

**Lambda Interface** - External processes that process audio via stdin/stdout:
- Raw PCM audio format (S16LE, configurable sample rate/channels)
- Environment variables provide audio format parameters
- `lambdas/lib.sh` contains `pal-sox()` helper function for sox-based effects

### Audio Flow Architecture
```
Audio Source → PulseAudio → pulseaudio-lambda → Lambda Process → PulseAudio → Audio Sink
                           (via stdin/stdout pipes)
```

### Key Technical Details

**Non-blocking I/O Implementation**: The bridge uses non-blocking pipes with retry logic to handle lambda processes that buffer internally (like sox). This prevents deadlocks when lambdas don't produce immediate 1:1 input/output.

**Lambda Environment Variables**: Each lambda process receives comprehensive audio format information:
- `PA_LAMBDA_SAMPLE_RATE`, `PA_LAMBDA_CHANNELS`, `PA_LAMBDA_BITS`, `PA_LAMBDA_SIGNED`, etc.
- Enables dynamic configuration without hardcoded parameters

**Real-time Processing Constraints**: 
- Lambdas must handle streaming data, not batch processing
- Avoid sox effects that require full stream analysis (like `gain -n` for normalization)
- Use `pal-sox` helper function for consistent sox parameter handling

### Lambda Development

**Lambda Interface Specification**:
- Read raw PCM data from stdin
- Write processed PCM data to stdout  
- Use environment variables for audio format parameters
- Handle `BrokenPipeError` gracefully for clean shutdown

**Common Patterns**:
```bash
# Basic sox-based lambda
source ./lambdas/lib.sh
pal-sox EFFECT_PARAMETERS

# Multi-effect chain
pal-sox highpass 100 bandreject 200 50 vol 0.8
```

### Build System

**Dual Target Architecture**: 
- Default `make` builds client executable (pulseaudio-lambda)  
- `make module` builds PulseAudio module (requires pulsecore headers)
- Client approach is recommended for development and deployment

**Nix Integration**:
- `flake.nix` provides complete development environment
- Includes audio tools (sox, ffmpeg) and development tools (gdb, valgrind)
- Package output includes both executable and lambda examples

## Important Constraints

**Sox Effects for Real-time Processing**: Only use sox effects that can process audio in real-time without analyzing the entire stream first. Effects like `gain -n` (normalization) will cause the lambda to block indefinitely in streaming mode.

**Lambda Process Management**: The bridge handles lambda process lifecycle, including spawning, pipe setup, and cleanup. Lambda processes should not attempt to manage their own audio device connections.

**Audio Format Limitations**: Currently hardcoded to S16LE format. Multi-format support is planned but not yet implemented.
