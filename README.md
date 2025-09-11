# PulseAudio Lambda

A bridge for applying arbitrary functions (lambdas) to real-time audio streams via stdin/stdout.

PulseAudio Lambda allows you to write audio processors in any programming language and integrate them seamlessly into your audio pipeline. Write fast filters in Rust, AI-powered processors in Python, or simple effects in bash - all through a unified stdin/stdout interface.

## ✅ MVP Status - WORKING!

The MVP is complete and verified working! You can now:
- ✅ Route audio from any PulseAudio source through external processes  
- ✅ Write lambdas in any language that can read stdin/write stdout
- ✅ Process real-time audio with minimal latency
- ✅ Use simple command-line interface for testing and deployment

## Quick Start

### Prerequisites

- PulseAudio installed and running
- Nix (recommended) or standard build tools

### Using Nix (Recommended)

```bash
# Enter development environment
nix develop

# Build the bridge
make

# Test with identity lambda (passthrough)
./pulseaudio-lambda ./lambdas/identity.sh
```

### Manual Build

```bash
# Install dependencies (Ubuntu/Debian)
sudo apt install build-essential pkg-config libpulse-dev libpulse-simple-dev

# Build
make

# Run
./pulseaudio-lambda ./lambdas/identity.sh
```

## Usage

### Basic Usage

```bash
# Use default audio devices
./pulseaudio-lambda /path/to/your/lambda

# Specify source and sink
./pulseaudio-lambda \
  --source=alsa_input.pci-0000_00_1f.3.analog-stereo \
  --sink=alsa_output.pci-0000_00_1f.3.analog-stereo \
  /path/to/your/lambda
```

### Finding Audio Devices

```bash
# List available sources (microphones, line inputs)
pactl list sources short

# List available sinks (speakers, headphones) 
pactl list sinks short
```

## Writing Lambdas

### Interface Specification

Lambdas are executables that:
- **Input**: Raw PCM audio data on stdin (S16LE, 44.1kHz, stereo by default)
- **Output**: Processed PCM audio data on stdout (same format)
- **Processing**: Must handle streaming data (not batch)
- **Environment**: Audio format parameters available as environment variables

### Environment Variables

The lambda process receives these environment variables:
- `PA_LAMBDA_SAMPLE_RATE`: Sample rate in Hz (e.g., "44100")  
- `PA_LAMBDA_CHANNELS`: Number of channels (e.g., "2" for stereo)
- `PA_LAMBDA_BUFFER_SIZE`: Buffer size in samples (e.g., "1024")
- `PA_LAMBDA_SAMPLE_FORMAT`: Sample format (currently "s16le")
- `PA_LAMBDA_BYTES_PER_SAMPLE`: Bytes per sample (e.g., "2" for S16LE)
- `PA_LAMBDA_BYTES_PER_FRAME`: Bytes per frame (channels × bytes_per_sample)
- `PA_LAMBDA_SIGNED`: Sample signedness ("signed" or "unsigned")
- `PA_LAMBDA_BITS`: Bits per sample (e.g., "16" for S16LE)

### Examples

#### Identity (Passthrough)
```bash
#!/usr/bin/env bash
# Simply pass audio through unchanged
exec cat
```

#### Volume Control (bash + sox)
```bash
#!/usr/bin/env bash  
# Volume adjustment using environment variables
# Usage: volume.sh [level] (level: 0.0 to 1.0, default 0.5)

# Use environment variables provided by pulseaudio-lambda
VOLUME=${1:-0.5}

exec sox -t raw -r "$PA_LAMBDA_SAMPLE_RATE" -e "$PA_LAMBDA_SIGNED" -b "$PA_LAMBDA_BITS" -c "$PA_LAMBDA_CHANNELS" - -t raw - vol "$VOLUME"
```

#### Python Audio Processor
```python
#!/usr/bin/env python3
import sys
import struct
import numpy as np
import os

# Get audio format from environment variables
SAMPLE_RATE = int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100'))
CHANNELS = int(os.environ.get('PA_LAMBDA_CHANNELS', '2'))
BUFFER_SIZE = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
BYTES_PER_FRAME = int(os.environ.get('PA_LAMBDA_BYTES_PER_FRAME', '4'))

# Calculate read size
READ_SIZE = BUFFER_SIZE * BYTES_PER_FRAME

# Disable buffering for real-time processing
sys.stdin = sys.stdin.buffer
sys.stdout = sys.stdout.buffer

try:
    while True:
        # Read buffer from stdin
        data = sys.stdin.read(READ_SIZE)
        if not data:
            break
            
        # Convert to numpy array for processing
        samples = np.frombuffer(data, dtype=np.int16)
        
        # Your processing here (example: simple gain)
        processed = (samples * 0.8).astype(np.int16)
        
        # Write back to stdout
        sys.stdout.write(processed.tobytes())
        sys.stdout.flush()
        
except BrokenPipeError:
    pass  # Clean shutdown when pipeline closes
```

## Architecture

```
Audio Application → PulseAudio Source → pulseaudio-lambda → Lambda Process → PulseAudio Sink → Audio Output
```

The bridge:
1. Connects to specified PulseAudio source and sink
2. Spawns your lambda process with stdin/stdout pipes
3. Continuously reads audio from source → lambda stdin
4. Reads processed audio from lambda stdout → sink
5. Handles process lifecycle and cleanup

## Project Status

### ✅ Completed (MVP)
- [x] Core audio bridge functionality
- [x] Stdin/stdout lambda interface  
- [x] Command-line interface
- [x] Nix development environment
- [x] Build system (Makefile)
- [x] Identity lambda example
- [x] Real-time audio processing verified

### 🔄 In Progress
- [ ] Additional lambda examples (volume, filters, AI processing)
- [ ] Performance optimization and latency tuning
- [ ] Comprehensive test suite
- [ ] Documentation expansion

### 📋 Future Enhancements
- [ ] PulseAudio module implementation (alternative to client)
- [ ] Format negotiation (different sample rates, bit depths)
- [ ] Multi-channel support beyond stereo
- [ ] Lambda process monitoring and restart
- [ ] Configuration file support
- [ ] Audio quality metrics and monitoring

## Contributing

This project uses a GitHub project board for tracking work. Check out the [issues](https://github.com/harryaskham/pulseaudio-lambda/issues) and [project board](https://github.com/users/harryaskham/projects/2) for current development status.

## License

[Add your license here]