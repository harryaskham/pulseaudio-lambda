#!/usr/bin/env bash

# Bandpass emphasising whispers
pacat -r --latency-msec=1 \
  | sox \
      -t raw \
      -r "$PA_LAMBDA_SAMPLE_RATE" \
      -e "$PA_LAMBDA_SIGNED" \
      -b "$PA_LAMBDA_BITS" \
      -c "$PA_LAMBDA_CHANNELS" \
      - \
      -t raw \
      - \
      bandpass 2.5k 1.5k \
      vol 24dB 0.05 \
  | pacat -p --latency-msec=1
