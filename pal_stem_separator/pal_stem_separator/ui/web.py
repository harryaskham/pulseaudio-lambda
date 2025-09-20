#!/usr/bin/env python3
"""
Lightweight Web UI for the stream separator config (no Tk dependency).

Serves a single-page app with sliders and toggles that updates
the same JSON config as the TUI. Runs on localhost and prints the URL.
"""

from starlette.applications import Starlette
from starlette.responses import JSONResponse, HTMLResponse
from starlette.requests import Request
from starlette.routing import Route
import uvicorn
import json
import os
import threading
import time
import webbrowser

from pal_stem_separator.stream_separator_args import Args


def _serialize_args(args: Args) -> dict:
    return {
        "gains": args.gains,
        "muted": args.muted,
        "soloed": args.soloed,
        "chunk_secs": args.chunk_secs,
        "overlap_secs": args.overlap_secs,
        "device": args.device,
        "normalize": args.normalize,
        "checkpoint": args.checkpoint,
    }


async def get_config(request: Request):
    args = Args.read()
    return JSONResponse(_serialize_args(args))


async def update_config(request: Request):
    args = Args.read()
    payload = await request.json()
    action = payload.get("action")

    try:
        if action == "set_gain":
            i = int(payload["index"])
            v = float(payload["value"])
            args.gains[i] = max(0.0, min(200.0, v))
        elif action == "mute_toggle":
            i = int(payload["index"])
            args.toggle_mute(i)
        elif action == "solo_toggle":
            i = int(payload["index"])
            args.toggle_solo(i)
        elif action == "set_chunk":
            args.chunk_secs = float(payload["value"])
        elif action == "set_overlap":
            args.overlap_secs = float(payload["value"])
        elif action == "set_device":
            val = payload["value"].lower()
            args.device = "cuda" if val == "cuda" else "cpu"
        elif action == "set_normalize":
            args.normalize = bool(payload["value"])  # payload may be true/false
        elif action == "set_checkpoint":
            args.checkpoint = str(payload["value"])
        elif action == "reset_volumes":
            args.reset_volumes()
        elif action == "empty_queues":
            args.request_empty_queues()
        else:
            return JSONResponse({"error": f"Unknown action: {action}"}, status_code=400)

        args.save()
        return JSONResponse({"ok": True, "config": _serialize_args(args)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="wdth=device-width, initial-scale=1" />
  <title>PA&lambda;-stem-separator</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; }
    .container { max-width: 800px; margin: 0 auto; padding: 16px; }
    h1 { font-size: 20px; margin: 0 0 12px; }
    .section { border: 1px solid #ddd; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
    .section h2 { font-size: 16px; margin: 0 0 10px; color: #333; }
    .row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
    .row label { width: 120px; }
    input[type="range"] { flex: 1; }
    .stems { display: grid; grid-template-columns: 1fr; gap: 8px; }
    .buttons { display: flex; gap: 8px; }
    button { padding: 6px 10px; border-radius: 6px; border: 1px solid #999; background: #f5f5f5; cursor: pointer; }
    button.primary { background: #2563eb; color: white; border-color: #2563eb; }
    .status { color: #2563eb; font-size: 12px; min-height: 1.2em; }
    .muted { background: #ef4444; color: white; border-color: #ef4444; }
    .solo { background: #f59e0b; color: white; border-color: #f59e0b; }
    @media (min-width: 640px) { .stems { grid-template-columns: 1fr 1fr; } }
  </style>
  <script>
    let config = null;
    let saveTimer = null;

    async function loadConfig() {
      const r = await fetch('/api/config');
      config = await r.json();
      render();
    }

    function setStatus(msg) {
      document.getElementById('status').textContent = msg || '';
      if (msg) setTimeout(() => setStatus(''), 1500);
    }

    async function send(action, payload) {
      const r = await fetch('/api/update', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ action, ...payload }) });
      const data = await r.json();
      if (data.ok) { config = data.config; render(); setStatus('Saved'); } else { setStatus(data.error || 'Error'); }
    }

    function onGainChange(i, v) { debounce(() => send('set_gain', { index: i, value: v }), 150); }
    function onMute(i) { send('mute_toggle', { index: i }); }
    function onSolo(i) { send('solo_toggle', { index: i }); }
    function onChunk(v) { debounce(() => send('set_chunk', { value: v }), 150); }
    function onOverlap(v) { debounce(() => send('set_overlap', { value: v }), 150); }
    function onDevice(v) { send('set_device', { value: v }); }
    function onNormalize(v) { send('set_normalize', { value: v }); }
    function onCheckpoint(v) { debounce(() => send('set_checkpoint', { value: v }), 300); }
    function resetVolumes() { send('reset_volumes', {}); }
    function emptyQueues() { send('empty_queues', {}); }

    function debounce(fn, ms) {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(fn, ms);
    }

    function render() {
      if (!config) return;
      for (let i=0;i<4;i++) {
        const g = document.getElementById('gain_'+i);
        const gl = document.getElementById('gain_label_'+i);
        const m = document.getElementById('mute_'+i);
        const s = document.getElementById('solo_'+i);
        g.value = config.gains[i];
        gl.textContent = Math.round(config.gains[i]) + '%';
        m.classList.toggle('muted', !!config.muted[i]);
        s.classList.toggle('solo', !!config.soloed[i]);
      }
      document.getElementById('chunk_secs').value = config.chunk_secs;
      document.getElementById('chunk_label').textContent = config.chunk_secs.toFixed(1);
      document.getElementById('overlap_secs').value = config.overlap_secs;
      document.getElementById('overlap_label').textContent = config.overlap_secs.toFixed(1);
      document.getElementById('device_cpu').checked = config.device === 'cpu';
      document.getElementById('device_cuda').checked = config.device === 'cuda';
      document.getElementById('normalize').checked = !!config.normalize;
      document.getElementById('checkpoint').value = config.checkpoint || '';
    }

    window.addEventListener('DOMContentLoaded', loadConfig);
  </script>
  </head>
  <body>
    <div class="container">
      <h1>pa&lambda;-stem-separator</h1>
      <div id="status" class="status"></div>

      <div class="section">
        <h2>Volume Controls</h2>
        <div class="stems">
          <div>
            <div class="row"><label>Drums</label><input id="gain_0" type="range" min="0" max="200" step="1" oninput="onGainChange(0, this.value)"/><div id="gain_label_0">100%</div></div>
            <div class="buttons"><button id="mute_0" onclick="onMute(0)">Mute</button><button id="solo_0" onclick="onSolo(0)">Solo</button></div>
          </div>
          <div>
            <div class="row"><label>Bass</label><input id="gain_1" type="range" min="0" max="200" step="1" oninput="onGainChange(1, this.value)"/><div id="gain_label_1">100%</div></div>
            <div class="buttons"><button id="mute_1" onclick="onMute(1)">Mute</button><button id="solo_1" onclick="onSolo(1)">Solo</button></div>
          </div>
          <div>
            <div class="row"><label>Vocals</label><input id="gain_2" type="range" min="0" max="200" step="1" oninput="onGainChange(2, this.value)"/><div id="gain_label_2">100%</div></div>
            <div class="buttons"><button id="mute_2" onclick="onMute(2)">Mute</button><button id="solo_2" onclick="onSolo(2)">Solo</button></div>
          </div>
          <div>
            <div class="row"><label>Other</label><input id="gain_3" type="range" min="0" max="200" step="1" oninput="onGainChange(3, this.value)"/><div id="gain_label_3">100%</div></div>
            <div class="buttons"><button id="mute_3" onclick="onMute(3)">Mute</button><button id="solo_3" onclick="onSolo(3)">Solo</button></div>
          </div>
        </div>
        <div class="row"><button class="primary" onclick="resetVolumes()">Reset All Volumes</button></div>
      </div>

      <div class="section">
        <h2>Processing Settings</h2>
        <div class="row"><label>Chunk Size</label><input id="chunk_secs" type="range" min="0.1" max="30.0" step="0.1" oninput="onChunk(this.value)"/><div id="chunk_label">2.0</div></div>
        <div class="row"><label>Overlap</label><input id="overlap_secs" type="range" min="0.0" max="5.0" step="0.1" oninput="onOverlap(this.value)"/><div id="overlap_label">0.5</div></div>
        <div class="row"><label>Device</label>
          <div>
            <label><input type="radio" id="device_cpu" name="device" value="cpu" onchange="onDevice('cpu')"/> CPU</label>
            <label><input type="radio" id="device_cuda" name="device" value="cuda" onchange="onDevice('cuda')"/> CUDA</label>
          </div>
        </div>
        <div class="row"><label>Normalize</label><input type="checkbox" id="normalize" onchange="onNormalize(this.checked)"/></div>
        <div class="row"><button onclick="emptyQueues()">Empty Queues</button></div>
      </div>

      <div class="section">
        <h2>Model Checkpoint</h2>
        <div class="row" style="gap:6px;">
          <input id="checkpoint" type="text" style="flex:1;" placeholder="~/path/to/checkpoint.pt" oninput="onCheckpoint(this.value)"/>
        </div>
      </div>
    </div>
  </body>
  </html>
"""


async def index(request: Request):
    return HTMLResponse(HTML)


def make_app() -> Starlette:
    return Starlette(routes=[
        Route("/", index),
        Route("/api/config", get_config),
        Route("/api/update", update_config, methods=["POST"]),
    ])


class StreamSeparatorWebGUI:
    def __init__(self):
        self.app = make_app()

    def run(self):
        host = os.environ.get("PAL_UI_HOST", "127.0.0.1")
        port = int(os.environ.get("PAL_UI_PORT", "8765"))
        url = f"http://{host}:{port}"

        # Start server in a background thread
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)

        def serve():
            server.run()

        t = threading.Thread(target=serve, daemon=True)
        t.start()

        # Give server a moment to bind
        time.sleep(0.3)

        # Try to open a native window via pywebview if available; fallback to browser
        try:
            import webview  # type: ignore
            window_title = os.environ.get("PAL_UI_TITLE", "Stream Separator Configuration")
            webview.create_window(window_title, url)
            print(f"Web UI available in native window at {url}")
            webview.start()
        except Exception:
            print(f"Web UI available at {url}")
            # Open default browser if allowed
            try:
                if os.environ.get("PAL_UI_OPEN", "1") != "0":
                    webbrowser.open(url)
            except Exception:
                pass
            # Keep process alive while server runs
            try:
                while t.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
