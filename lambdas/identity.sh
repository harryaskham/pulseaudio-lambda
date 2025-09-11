#!/usr/bin/env bash

# Identity lambda - passes audio through unchanged
pacat -r --latency-msec=1 | pacat -p --latency-msec=1
