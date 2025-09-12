#!/usr/bin/env bash

# Drumless Adaptive - Configurable drum removal with different modes
# Usage: drumless-adaptive.sh [mode] [intensity]
#   mode: light|medium|heavy|surgical (default: medium)
#   intensity: 0.0-1.0 (default: 0.7)

source ./lambdas/lib.sh

MODE=${1:-medium}
INTENSITY=${2:-0.7}

case "$MODE" in
  light)
    # Light drum reduction - preserves more of the original
    pal-sox \
      highpass 70 \
      bandreject 80 20 \
      bandreject 200 30 \
      equalizer 1000 500 2 \
      compand 0.01,0.1 6:-30,-20,-10 -3 -90 0.1 \
      gain -2
    ;;
    
  medium)
    # Balanced drum removal
    pal-sox \
      highpass 85 \
      bandreject 60 25 \
      bandreject 120 35 \
      bandreject 200 50 \
      bandreject 5000 2000 \
      equalizer 800 300 3 \
      equalizer 1500 400 3 \
      compand 0.005,0.05 6:-35,-25,-15,-5 -5 -90 0.05 \
      gain -2
    ;;
    
  heavy)
    # Aggressive drum removal
    pal-sox \
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
      lowpass 9000 \
      compand 0.001,0.01 6:-40,-30,-20,-10,0 -8 -90 0.001 \
      gain -1
    ;;
    
  surgical)
    # Very precise targeting of drum frequencies
    # Best for specific songs where you know the drum tuning
    pal-sox \
      highpass 95 \
      bandreject 55 15 \
      bandreject 62 10 \
      bandreject 80 15 \
      bandreject 120 20 \
      bandreject 160 20 \
      bandreject 200 25 \
      bandreject 220 20 \
      bandreject 250 20 \
      bandreject 800 100 \
      bandreject 2000 300 \
      bandreject 3500 500 \
      bandreject 5000 1000 \
      bandreject 7000 1500 \
      bandreject 9000 1500 \
      equalizer 400 100 4 \
      equalizer 700 150 5 \
      equalizer 1000 200 6 \
      equalizer 1400 300 5 \
      equalizer 2000 300 3 \
      lowpass 10000 \
      compand 0.001,0.005 6:-45,-35,-25,-15,-5,0 -10 -90 0.001 \
      gain 0
    ;;
    
  *)
    echo "Unknown mode: $MODE. Using medium." >&2
    exec "$0" medium "$INTENSITY"
    ;;
esac