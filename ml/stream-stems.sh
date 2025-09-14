#/usr/bin/env bash

checkpoint="./experiments/full0/checkpoints/hs_tasnet.ema.ckpt.10.pt"
gains=("100,m,m,m" "m,100,m,m" "m,m,100,m" "m,m,m,100")
pa_source="vsink.monitor"
#pa_sink="bluez_output.A0_0C_E2_45_D8_C5.1"
pa_sink="alsa_output.pci-0000_c5_00.6.analog-stereo"
device="cpu"

pids=()
for gain in $gains; do
  echo "launching stream for $gain"
  (../pulseaudio-lambda \
    --source="$pa_source" \
    --sink="$pa_sink" \
    "python stream_separator.py --chunk-secs 10 --stem-gain $gain --checkpoint=$checkpoint --device=$device") \
    &
  pids+=("$!")
done

trap ctrl_c INT

function ctrl_c() {
  for pid in $pids; do
    kill -9 $pid
  done
  pgrep -f "python stream_separator.py" | xargs -I{} kill -9 {}
  exit 0
}

wait
