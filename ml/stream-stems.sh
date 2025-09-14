#/usr/bin/env bash

checkpoint="./experiments/full0/checkpoints/hs_tasnet.ema.ckpt.10.pt"

mode="$1"
case "$mode" in
  solo)
    m="m"
    s="100"
    ;;
  mute)
    m="100"
    s="m"
  ;;
esac

gains=()
gains+=("$s,$m,$m,$m") 
gains+=("$m,$s,$m,$m") 
gains+=("$m,$m,$s,$m") 
gains+=("$m,$m,$m,$s") 

pa_source="vsink.monitor"
pa_sink="bluez_output.A0_0C_E2_45_D8_C5.1"
#pa_sink="alsa_output.pci-0000_c5_00.6.analog-stereo"
#device="cpu"
device="cuda"
chunk_secs="10"
export HIP_VISIBLE_DEVICES=1

function mk-lambda-cmd() {
  gain="$1"
  cat << EOF
python stream_separator.py \
  --chunk-secs "$chunk_secs" \
  --stem-gain "$gain" \
  --checkpoint="$checkpoint" \
  --device="$device"
EOF
}

function mk-cmd() {
  gain="$1"
  cat << EOF
  ../pulseaudio-lambda \
    --source="$pa_source" \
    --sink="$pa_sink" \
    "$(mk-lambda-cmd "$gain")"
EOF
}

pids=()
for gain in "${gains[@]}"; do
  echo "launching stream for $gain"
  bash -c "$(mk-cmd "$gain")" &
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
