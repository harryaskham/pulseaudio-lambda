#!/usr/bin/env bash

# Sox with real-time streaming optimizations
# Forces immediate output with minimal buffering

exec stdbuf -i0 -o0 -e0 sox \
  -t raw \
  -r "$PA_LAMBDA_SAMPLE_RATE" \
  -e "$PA_LAMBDA_SIGNED" \
  -b "$PA_LAMBDA_BITS" \
  -c "$PA_LAMBDA_CHANNELS" \
  --buffer 128 \
  --multi-threaded \
  --no-show-progress \
  - \
  -t raw \
  - \
  2>/dev/null