#!/usr/bin/env bash

exec sox \
  -t raw \
  -r "$PA_LAMBDA_SAMPLE_RATE" \
  -e "$PA_LAMBDA_SIGNED" \
  -b "$PA_LAMBDA_BITS" \
  -c "$PA_LAMBDA_CHANNELS" \
  - \
  -t raw \
  -
