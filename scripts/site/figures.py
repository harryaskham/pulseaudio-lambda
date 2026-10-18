"""Figures and generated regions for the pulseaudio-lambda site.

data/latency.json comes from measure.py: the bridge run in a private PulseAudio server."""
import html
import json
from pathlib import Path

from diagrams import graph

DATA = Path(__file__).resolve().parent / "data"
METRICS = {"sans": 1.0, "mono": 0.6}


def bridge():
    return graph(
        "bridge", "Audio through a command",
        "How pulseaudio-lambda moves audio. It records from a PulseAudio source (by default the monitor of a virtual sink "
        "it creates, called Lambda Input, so any application can be routed into it) in buffers of 1,024 frames of 16-bit "
        "stereo at 44.1 kHz. Each buffer is written to the standard input of a command run with sh -c. In the same cycle "
        "the bridge makes one non-blocking read of up to one buffer from the command's standard output and plays whatever "
        "it got to the sink. The command learns the format from PA_LAMBDA_ environment variables.",
        940, 300,
        nodes=[
            dict(id="app", x=95, y=70, label="any app", sub="routed to Lambda Input", kind="muted", w=170),
            dict(id="src", x=95, y=200, label="source", sub="a monitor, or --source", kind="b", w=170),
            dict(id="br1", x=330, y=200, label="bridge: read", sub="1,024 frames (23 ms)", kind="ink", w=190),
            dict(id="cmd", x=505, y=80, label="sh -c LAMBDA", sub=["PCM on stdin → stdout", "PA_LAMBDA_* in env"], kind="accent", w=200, mono=True),
            dict(id="br2", x=690, y=200, label="bridge: play", sub="one read per cycle", kind="ink", w=190),
            dict(id="sink", x=870, y=200, label="sink", sub="--sink", kind="b", w=120),
        ],
        edges=[
            {"from": "app", "to": "src", "kind": "muted", "out": "b", "in": "t"},
            {"from": "src", "to": "br1", "kind": "b"},
            {"from": "br1", "to": "cmd", "kind": "accent", "out": "t", "in": "l", "label": "stdin", "at": 0.7},
            {"from": "cmd", "to": "br2", "kind": "accent", "out": "r", "in": "t", "label": "stdout", "at": 0.3},
            {"from": "br2", "to": "sink", "kind": "b"},
        ],
    )


def stems():
    return graph(
        "stems", "Taking the drums out",
        "The stem-separator lambda. It reads raw PCM from standard input in chunks of 2 seconds plus 0.5 seconds of "
        "overlap by default, puts the end of the previous chunk in front for context, and runs an HS-TasNet model that "
        "splits the audio into four stems: drums, bass, vocals and other. Each stem gets its gain, mute or solo from a "
        "configuration file that a terminal or graphical controller edits while it runs. A quarter of a second is trimmed "
        "from each edge so consecutive chunks meet in the middle of their overlap, and the mix goes to standard output.",
        940, 300,
        nodes=[
            dict(id="in", x=90, y=150, label="stdin", sub="s16le PCM", kind="file", w=140),
            dict(id="chunk", x=280, y=150, label="chunker", sub=["2 s + 0.5 s overlap", "previous tail in front"], kind="ink", w=190),
            dict(id="model", x=495, y=150, label="HS-TasNet", sub="four stems", kind="accent", w=170),
            dict(id="d", x=690, y=45, label="drums", kind="b", w=110),
            dict(id="b", x=690, y=115, label="bass", kind="b", w=110),
            dict(id="v", x=690, y=185, label="vocals", kind="b", w=110),
            dict(id="o", x=690, y=255, label="other", kind="b", w=110),
            dict(id="mix", x=860, y=150, label="mix", sub=["gains · mute · solo", "trim, stdout"], kind="ink", w=150),
        ],
        edges=[
            {"from": "in", "to": "chunk", "kind": "ink"},
            {"from": "chunk", "to": "model", "kind": "ink"},
            *[{"from": "model", "to": s, "kind": "b", "out": "r", "in": "l", "oy": oy, "mid": 595}
              for s, oy in (("d", -18), ("b", -6), ("v", 6), ("o", 18))],
            *[{"from": s, "to": "mix", "kind": "b", "out": "r", "in": "l", "iy": iy, "mid": 768}
              for s, iy in (("d", -24), ("b", -8), ("v", 8), ("o", 24))],
        ],
    )


FIGS = {"bridge": bridge, "stems": stems}


def latency():
    rows = []
    label = {"cat": "<code>cat</code>, which copies its input straight through",
             "lambdas/pal-delay 0.5": "<code>pal-delay 0.5</code>: sleeps 0.5 s, then copies",
             "lambdas/pal-delay 1": "<code>pal-delay 1</code>: sleeps 1 s, then copies"}
    for r in json.loads((DATA / "latency.json").read_text()):
        runs = ", ".join(f"{v:.0f}" for v in r["runs_ms"])
        rows.append(f'<tr><td>{label.get(r["lambda"], html.escape(r["lambda"]))}</td>'
                    f'<td class="num">{r["median_ms"]:.0f} ms</td><td class="runs">{runs}</td></tr>')
    return ('<table class="lat"><caption>Click to click, through the bridge (scripts/site/measure.py)</caption>'
            '<thead><tr><th scope="col">Lambda</th><th scope="col" class="num">Median</th><th scope="col">Runs (ms)</th></tr></thead>'
            '<tbody>' + "".join(rows) + "</tbody></table>")


GEN = {"latency": latency}
