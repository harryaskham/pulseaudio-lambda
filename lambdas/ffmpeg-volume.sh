#!/usr/bin/env bash

# FFmpeg-based volume control (often handles streaming better than sox)
VOLUME=${1:-0.5}

exec ffmpeg -f s16le -ar "$PA_LAMBDA_SAMPLE_RATE" -ac "$PA_LAMBDA_CHANNELS" -i - \
            -f s16le -ar "$PA_LAMBDA_SAMPLE_RATE" -ac "$PA_LAMBDA_CHANNELS" \
            -af "volume=$VOLUME" \
            -y pipe:1 2>/dev/null