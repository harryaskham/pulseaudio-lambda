#!/usr/bin/env bash

# Volume adjustment lambda using sox
# Uses environment variables provided by pulseaudio-lambda

# Check if environment variables are set
if [ -z "$PA_LAMBDA_SAMPLE_RATE" ] || [ -z "$PA_LAMBDA_CHANNELS" ]; then
    echo "Error: PA_LAMBDA_* environment variables not set" >&2
    exit 1
fi

# Volume level (0.0 to 1.0, default 0.5 = half volume)
VOLUME=${1:-0.5}

exec sox -t raw -r "$PA_LAMBDA_SAMPLE_RATE" -e "$PA_LAMBDA_SIGNED" -b "$PA_LAMBDA_BITS" -c "$PA_LAMBDA_CHANNELS" - -t raw - vol "$VOLUME"