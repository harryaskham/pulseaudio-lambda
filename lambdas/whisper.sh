#!/usr/bin/env bash

# Bandpass emphasising whispers
#pacat --raw -r --latency-msec=1 \
cat | \
sox \
  -t raw \
  -r "$PA_LAMBDA_SAMPLE_RATE" \
  -e "$PA_LAMBDA_SIGNED" \
  -b "$PA_LAMBDA_BITS" \
  -c "$PA_LAMBDA_CHANNELS" \
  - \
  -t raw \
  - \
  #| pacat -p --latency-msec=1
  #bandpass -c 2.5k 1.5k \
