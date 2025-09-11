#!/usr/bin/env bash

# Wrapper that uses pacat to handle sox buffering
# This mimics your working manual pipeline

# Use pacat to handle the audio format conversion that sox expects
exec pacat -r --raw --format="$PA_LAMBDA_SAMPLE_FORMAT" --rate="$PA_LAMBDA_SAMPLE_RATE" --channels="$PA_LAMBDA_CHANNELS" | \
     sox -t raw -r "$PA_LAMBDA_SAMPLE_RATE" -e "$PA_LAMBDA_SIGNED" -b "$PA_LAMBDA_BITS" -c "$PA_LAMBDA_CHANNELS" - -t raw - | \
     pacat -p --raw --format="$PA_LAMBDA_SAMPLE_FORMAT" --rate="$PA_LAMBDA_SAMPLE_RATE" --channels="$PA_LAMBDA_CHANNELS"