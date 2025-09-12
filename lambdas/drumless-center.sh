#!/usr/bin/env bash

# Drumless Center - Uses center channel extraction to reduce drums
# Many drums are mixed in the center channel, so removing center content
# can significantly reduce drums while preserving stereo-panned instruments

source ./lambdas/lib.sh

# Center channel extraction approach:
# 1. Extract center channel (mono content)
# 2. Apply heavy filtering to the center channel
# 3. Mix back with reduced level
# 4. Apply frequency-specific drum filtering
# 5. Enhance stereo content that remains

MODE=${1:-balanced}

case "$MODE" in
  gentle)
    # Light center reduction
    pal-sox \
      remix 1,2 1,2 \
      highpass 80 \
      bandreject 100 40 \
      bandreject 200 50 \
      equalizer 1200 600 3 \
      gain -2
    ;;
    
  balanced)
    # Balanced approach - reduces center and applies filtering
    pal-sox \
      remix 1v0.7,2v0.7 1v0.7,2v0.7 \
      highpass 90 \
      bandreject 60 30 \
      bandreject 120 40 \
      bandreject 200 60 \
      bandreject 5000 2500 \
      equalizer 800 300 4 \
      equalizer 1500 400 4 \
      compand 0.01,0.1 6:-30,-20,-10 -4 -90 0.1 \
      gain -2
    ;;
    
  aggressive)
    # Heavy center extraction with drum frequency targeting
    pal-sox \
      remix 1v0.5,2v0.5 1v0.5,2v0.5 \
      highpass 100 \
      bandreject 60 40 \
      bandreject 100 60 \
      bandreject 150 60 \
      bandreject 200 80 \
      bandreject 250 60 \
      bandreject 4000 3000 \
      bandreject 8000 3000 \
      equalizer 600 200 5 \
      equalizer 1000 300 6 \
      equalizer 1500 400 5 \
      equalizer 2000 300 3 \
      lowpass 9000 \
      compand 0.001,0.01 6:-40,-30,-20,-10,0 -6 -90 0.001 \
      gain -1
    ;;
    
  *)
    echo "Unknown mode: $MODE. Use gentle, balanced, or aggressive." >&2
    exec "$0" balanced
    ;;
esac