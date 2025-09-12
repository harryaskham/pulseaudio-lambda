#!/usr/bin/env bash

# Strip out drums
source ./lambdas/lib.sh
# Kicks at 80-150hz
# Snares at 120-250hz
# Cymbals at 400-500hz and higher at 5khz+
pal-sox \
  bandpass 1200 500 \
  compand 0.3,1 45:-70,-60,-8 -5 -90 0.3 \
  #vol +15dB \
