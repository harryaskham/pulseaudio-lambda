#!/usr/bin/env bash

# Fixed sox lambda that should work with direct stdin/stdout
# Uses unbuffered I/O and proper streaming parameters

# Volume level
VOLUME=${1:-0.5}

# Force unbuffered I/O
exec stdbuf -i0 -o0 -e0 sox \
    -t raw \
    -r "$PA_LAMBDA_SAMPLE_RATE" \
    -e "$PA_LAMBDA_SIGNED" \
    -b "$PA_LAMBDA_BITS" \
    -c "$PA_LAMBDA_CHANNELS" \
    -V1 \
    - \
    -t raw \
    - \
    vol "$VOLUME"