#!/usr/bin/env bash

# Debug lambda to test I/O behavior
echo "Lambda started, reading from stdin..." >&2

# Use dd to copy data through with small buffer size to test streaming
exec dd bs=4096 2>/dev/null