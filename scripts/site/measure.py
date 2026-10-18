#!/usr/bin/env python3
"""Measure pulseaudio-lambda end to end in a private, headless PulseAudio server.

    python3 scripts/site/measure.py PATH/TO/pulseaudio-lambda [LAMBDA...]

Starts `pulseaudio -n` with its own runtime directory and three null sinks: `in`, `mix`, and
`both`, a combined sink that forwards to `in` and `mix` at once. The bridge reads `in.monitor`,
runs a lambda, and writes to `mix`. A short click played into `both` therefore reaches `mix`
twice: directly, and again after a trip through the bridge. One recorder on `mix.monitor` sees
both, so the gap between the two clicks is the bridge's latency, with no clock to align.

Writes scripts/site/data/latency.json. Needs pulseaudio and pacat/parec on PATH; no audio
hardware, no session bus and none of the user's audio configuration are touched.
"""
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RATE, CH = 44100, 2
REPEATS = 3  # each lambda is measured this many times, each in a fresh server
FMT = ["--raw", "--format=s16le", f"--rate={RATE}", f"--channels={CH}"]


def click(seconds_before=0.3, seconds_after=1.2):
    frames = [0] * int(RATE * seconds_before) + [26000] * 8 + [0] * int(RATE * seconds_after)
    return b"".join(struct.pack("<hh", v, v) for v in frames)


def peaks(raw):
    vals = [abs(struct.unpack_from("<h", raw, i)[0]) for i in range(0, len(raw) - 3, 4)]
    top = max(vals) if vals else 0
    out, last = [], -RATE
    for i, v in enumerate(vals):
        if top and v > top * 0.3 and i - last > RATE // 50:  # a new click, at least 20 ms after the last
            out.append(i)
            last = i
    return out


def measure(bridge, lam, env, tmp):
    procs = []
    try:
        pa = subprocess.Popen(["pulseaudio", "-n", "--daemonize=no", "--exit-idle-time=-1", "--log-target=stderr",
                               "-L", "module-native-protocol-unix",
                               "-L", f"module-null-sink sink_name=in rate={RATE}",
                               "-L", f"module-null-sink sink_name=mix rate={RATE}",
                               "-L", "module-combine-sink sink_name=both slaves=in,mix",
                               ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append(pa)
        for _ in range(50):
            if subprocess.run(["pactl", "info"], env=env, capture_output=True).returncode == 0:
                break
            time.sleep(0.1)
        br = subprocess.Popen([bridge, "--source=in.monitor", "--sink=mix", "--name=bridge", lam], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(br)
        time.sleep(2.0)
        rec_path = os.path.join(tmp, "mix.raw")
        with open(rec_path, "wb") as f:
            rec = subprocess.Popen(["parec", "-d", "mix.monitor", *FMT], env=env, stdout=f)
            procs.append(rec)
            time.sleep(0.5)
            subprocess.run(["pacat", "-d", "both", *FMT], input=click(), env=env, check=True)
            time.sleep(1.5)
            rec.terminate()
            rec.wait()
        ps = peaks(Path(rec_path).read_bytes())
        gap = round((ps[1] - ps[0]) / RATE * 1000, 1) if len(ps) >= 2 else None
        return {"lambda": lam, "clicks_seen": len(ps), "latency_ms": gap}
    finally:
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM) if p.args and p.args[0] == bridge else p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()


def main():
    bridge = os.path.abspath(sys.argv[1])
    lambdas = sys.argv[2:] or ["cat", "lambdas/pal-delay 0.5", "lambdas/pal-delay 1"]
    results = []
    for lam in [l for l in lambdas for _ in range(REPEATS)]:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(tmp, "home"),
                   "XDG_RUNTIME_DIR": os.path.join(tmp, "run"), "PULSE_RUNTIME_PATH": os.path.join(tmp, "run", "pulse")}
            for d in ("home", "run"):
                os.makedirs(os.path.join(tmp, d), mode=0o700)
            r = measure(bridge, lam, env, tmp)
            print(r, flush=True)
            results.append(r)
    (HERE / "data").mkdir(exist_ok=True)
    summary = []
    for lam in lambdas:
        runs = [r["latency_ms"] for r in results if r["lambda"] == lam and r["latency_ms"] is not None]
        summary.append({"lambda": lam, "runs_ms": runs, "median_ms": sorted(runs)[len(runs) // 2] if runs else None})
    (HERE / "data" / "latency.json").write_text(json.dumps(summary, indent=1) + "\n")


if __name__ == "__main__":
    main()
