#!/usr/bin/env bash

# Bandpass emphasising whispers
source ./lambdas/lib.sh
pal-sox bandpass -c 2.5k 1.5k
