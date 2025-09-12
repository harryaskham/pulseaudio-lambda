#!/usr/bin/env bash

# Bandpass emphasising speech
source ./lambdas/lib.sh
# 50hz - 8050hz
pal-sox bandpass 4050 4000
