#!/usr/bin/env bash

# Identity lambda - passes audio through unchanged
pacat -p --raw | pacat -r --raw --latency-msec=1
