#!/usr/bin/env bash

# Drumless - Advanced drum removal/reduction filter
# Targets specific drum frequencies while preserving melodic content

source ./lambdas/lib.sh

# Drum frequency analysis:
# - Kick drum: 40-100 Hz (fundamental), 2-5 kHz (beater attack)  
# - Snare: 120-250 Hz (fundamental), 2-4 kHz (snare wires), 800Hz (body)
# - Hi-hats: 3-8 kHz (primary), 8-12 kHz (shimmer)
# - Cymbals: 300-600 Hz (body), 4-12 kHz (crash/ride)
# - Toms: 80-250 Hz (depending on size)

# Multi-stage approach:
# 1. Remove low frequency kick drum energy
# 2. Notch out snare fundamental frequencies
# 3. Reduce high frequency transients (cymbals/hi-hats)
# 4. Preserve and boost mid-range (vocals/melodic instruments)
# 5. Apply dynamic compression to smooth out remaining transients

pal-sox \
  highpass 90 \
  bandreject 60 30 \
  bandreject 120 40 \
  bandreject 200 60 \
  bandreject 250 50 \
  bandreject 5000 3000 \
  bandreject 8000 2000 \
  equalizer 300 100 3 \
  equalizer 600 200 4 \
  equalizer 1000 300 5 \
  equalizer 1500 400 4 \
  equalizer 2500 300 2 \
  lowpass 10000 \
  compand 0.002,0.01 6:-40,-30,-20,-10,0 -6 -90 0.002 \
  gain -1
