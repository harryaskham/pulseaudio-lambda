#!/usr/bin/env bash

# Test lambda using dd to see if raw streaming works
echo "Testing raw streaming with dd" >&2
exec dd bs="$PA_LAMBDA_BYTES_PER_FRAME" 2>/dev/null