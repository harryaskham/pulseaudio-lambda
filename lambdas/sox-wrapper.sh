#!/usr/bin/env bash

# Wrapper that handles sox's buffering by using a fifo
# This decouples input and output timing

FIFO=$(mktemp -u)
mkfifo "$FIFO"

# Cleanup on exit
trap "rm -f $FIFO" EXIT

# Start sox in background reading from FIFO
sox -t raw -r "$PA_LAMBDA_SAMPLE_RATE" -e "$PA_LAMBDA_SIGNED" -b "$PA_LAMBDA_BITS" -c "$PA_LAMBDA_CHANNELS" \
    "$FIFO" -t raw - &
SOX_PID=$!

# Copy stdin to FIFO
cat > "$FIFO"

# Wait for sox to finish
wait $SOX_PID