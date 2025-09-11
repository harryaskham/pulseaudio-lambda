#!/usr/bin/env bash

# Debug lambda to test sox directly
echo "Testing sox with format: -r $PA_LAMBDA_SAMPLE_RATE -e $PA_LAMBDA_SIGNED -b $PA_LAMBDA_BITS -c $PA_LAMBDA_CHANNELS" >&2

# Try sox directly with verbose output
exec sox -V1 \
    -t raw -r "$PA_LAMBDA_SAMPLE_RATE" -e "$PA_LAMBDA_SIGNED" -b "$PA_LAMBDA_BITS" -c "$PA_LAMBDA_CHANNELS" \
    - \
    -t raw \
    - \
    vol 0.5