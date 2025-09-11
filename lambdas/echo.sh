#!/usr/bin/env bash

# Echo effect lambda using sox with environment variables
# Usage: echo.sh [gain_in] [gain_out] [delay] [decay]
# Example: echo.sh 0.8 0.9 1000 0.3

GAIN_IN=${1:-0.8}
GAIN_OUT=${2:-0.9}
DELAY=${3:-1000}    # delay in milliseconds
DECAY=${4:-0.3}     # echo decay (0.0 to 1.0)

# Use all environment variables for complete format specification
exec sox -t raw \
    -r "$PA_LAMBDA_SAMPLE_RATE" \
    -e "$PA_LAMBDA_SIGNED" \
    -b "$PA_LAMBDA_BITS" \
    -c "$PA_LAMBDA_CHANNELS" \
    - \
    -t raw \
    - \
    echo "$GAIN_IN" "$GAIN_OUT" "$DELAY" "$DECAY"
