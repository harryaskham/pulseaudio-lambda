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
import subprocess
import signal


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


async def get_stats(request: Request):
    args = Args.read()
    try:
        with open(args.stats_path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    return JSONResponse(data)

# --- Service control and logs ---

def _service_cmdlines_match(cmdline: bytes) -> bool:
    try:
        parts = [p for p in cmdline.split(b"\x00") if p]
        for p in parts:
            s = p.decode(errors="ignore")
            base = os.path.basename(s)
            if base == "pal-stem-separator" or s.endswith("/pal-stem-separator"):
                return True
            if s == "stem-separator" or s == "stem-separator --debug":
                return True
    except Exception:
        pass
    return False


def _find_service_pids() -> list[int]:
    pids: list[int] = []
    try:
        for e in os.scandir("/proc"):
            if not e.is_dir() or not e.name.isdigit():
                continue
            try:
                with open(os.path.join("/proc", e.name, "cmdline"), "rb") as f:
                    if _service_cmdlines_match(f.read()):
                        pids.append(int(e.name))
            except Exception:
                continue
    except Exception:
        pass
    return pids


def _service_running() -> bool:
    if _find_service_pids():
        return True
    try:
        subprocess.run(["pgrep", "-f", "pal-stem-separator$"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _start_service():
    try:
        subprocess.Popen(["pulseaudio-lambda", "pal-stem-separator"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


def _stop_service():
    sent = False
    for pid in _find_service_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            sent = True
        except Exception:
            pass
    try:
        subprocess.Popen(["pkill", "-f", "pal-stem-separator$"])  # nosec
        sent = True
    except Exception:
        pass
    return sent


async def service_status(request: Request):
    return JSONResponse({"running": _service_running()})


async def service_action(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    action = (payload.get("action") or "").lower()
    if action == "start":
        ok = _start_service()
        return JSONResponse({"ok": ok, "running": _service_running()})
    if action == "stop":
        ok = _stop_service()
        return JSONResponse({"ok": ok, "running": _service_running()})
    return JSONResponse({"error": "unknown action"}, status_code=400)


async def get_logs(request: Request):
    args = Args.get_live() if hasattr(Args, 'get_live') else Args.read()
    config_dir = Args.get_config_dir(args)
    log_path = os.path.join(config_dir, "stream_separator.log")
    try:
        q = request.query_params
        offset = int(q.get("offset", "0"))
    except Exception:
        offset = 0
    data = ""
    new_offset = offset
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            if offset < 0 or offset > end:
                offset = max(0, end - 8192)
            f.seek(offset)
            chunk = f.read()
            data = chunk.decode(errors="ignore")
            new_offset = offset + len(chunk)
    except FileNotFoundError:
        data = ""
        new_offset = 0
    return JSONResponse({"data": data, "offset": new_offset})


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
    .logs { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; background: #111827; color: #e5e7eb; border-radius: 6px; padding: 8px; height: 180px; overflow: auto; }
  </style>
  <script>
    let config = null;
    let saveTimer = null;
    let prevStats = null;
    let prevStatsAt = 0;
    let statsHist = []; // { t, in, out, proc }

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

    // --- Service ---
    async function refreshService() {
      try {
        const r = await fetch('/api/service/status');
        const s = await r.json();
        const svc = document.getElementById('svc_state');
        const btn = document.getElementById('svc_btn');
        if (s.running) { svc.textContent='Running'; svc.style.color='#22c55e'; btn.textContent='Stop'; btn.onclick=stopService; }
        else { svc.textContent='Stopped'; svc.style.color='#ef4444'; btn.textContent='Start'; btn.onclick=startService; }
      } catch {}
    }
    async function startService() { await fetch('/api/service', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'start'})}); refreshService(); showLogs(); }
    async function stopService() { await fetch('/api/service', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'stop'})}); refreshService(); }

    // --- Logs ---
    let logOffset = 0;
    let logsTimer = null;
    let followTail = true;
    function toggleLogs() { const wrap = document.getElementById('logs_wrap'); const btn = document.getElementById('logs_btn'); if (wrap.style.display==='none') { showLogs(); } else { hideLogs(); } }
    function showLogs() { const wrap = document.getElementById('logs_wrap'); wrap.style.display='block'; document.getElementById('logs_btn').textContent='Hide Logs'; followTail=true; if (!logsTimer) { pollLogs(); logsTimer=setInterval(pollLogs, 1000); } }
    function hideLogs() { const wrap = document.getElementById('logs_wrap'); wrap.style.display='none'; document.getElementById('logs_btn').textContent='Show Logs'; if (logsTimer) { clearInterval(logsTimer); logsTimer=null; } }
    async function pollLogs() { try { const r = await fetch(`/api/logs?offset=${logOffset}`); const data = await r.json(); const el = document.getElementById('logs'); const atBottom=(el.scrollTop+el.clientHeight)>=(el.scrollHeight-2); if (data.data && data.data.length) { el.textContent += data.data; } logOffset = data.offset||logOffset; if (followTail && (atBottom || el.textContent.length===0)) { el.scrollTop=el.scrollHeight; } } catch {} }
    function onLogsScroll() { const el = document.getElementById('logs'); const atBottom=(el.scrollTop+el.clientHeight)>=(el.scrollHeight-2); followTail = atBottom; }

    window.addEventListener('DOMContentLoaded', () => { loadConfig(); refreshService(); });

    // --- Stats ---
    function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
    function fmtLatency(s) { return `${(s||0).toFixed(2)} s`; }
    function fmtRTF(v) { return `RTF ${(v||0).toFixed(2)}x`; }
    function fmtBytes(b) {
      const abs = Math.abs(b||0);
      if (abs >= 1024*1024*1024) return `${(b/(1024*1024*1024)).toFixed(2)} GB`;
      if (abs >= 1024*1024) return `${(b/(1024*1024)).toFixed(2)} MB`;
      if (abs >= 1024) return `${(b/1024).toFixed(2)} kB`;
      return `${Math.round(b||0)} B`;
    }
    function fmtRate(bytesPerSec) {
      const abs = Math.abs(bytesPerSec||0);
      if (abs >= 1024*1024) return `${(bytesPerSec/(1024*1024)).toFixed(1)} MB/s`;
      if (abs >= 1024) return `${(bytesPerSec/1024).toFixed(1)} kB/s`;
      return `${Math.round(bytesPerSec||0)} B/s`;
    }

    async function loadStats() {
      try {
        const r = await fetch('/api/stats');
        const stats = await r.json();
        const now = Date.now() / 1000;
        // Update history (30s window)
        statsHist.push({ t: now, in: stats.input_bytes||0, out: stats.output_bytes||0, proc: stats.processed_secs||0 });
        // prune
        const cutoff = now - 30.0;
        while (statsHist.length && statsHist[0].t < cutoff) statsHist.shift();

        let inBps = 0, outBps = 0, rtf = 0;
        if (statsHist.length >= 2) {
          const last = statsHist[statsHist.length-1];
          let j = 0;
          while (j < statsHist.length-1) {
            if ((last.in - statsHist[j].in) > 0 || (last.out - statsHist[j].out) > 0) break;
            j++;
          }
          if (j >= statsHist.length-1) j = statsHist.length-2;
          const first = statsHist[j];
          const dt = Math.max(0.001, last.t - first.t);
          inBps = Math.max(0, (last.in - first.in) / dt);
          outBps = Math.max(0, (last.out - first.out) / dt);
          rtf = Math.max(0, (last.proc - first.proc) / dt);
        }

        // Update DOM
        document.getElementById('in_rate').textContent = fmtRate(inBps);
        document.getElementById('out_rate').textContent = fmtRate(outBps);

        // Latency bar with chunk-relative threshold
        const lat = stats.latency_secs || 0;
        const latRatio = clamp(lat / 45.0, 0, 1);
        const latEl = document.getElementById('latency_bar_fill');
        latEl.style.width = `${Math.round(latRatio*100)}%`;
        const chunk = (config && typeof config.chunk_secs === 'number') ? config.chunk_secs : 2.0;
        latEl.style.background = (lat < 1.2*chunk) ? '#22c55e' : (lat >= 45.0 ? '#ef4444' : '#f59e0b');
        document.getElementById('latency_label').textContent = fmtLatency(lat);

        // RTF label
        document.getElementById('rtf_label').textContent = fmtRTF(rtf);

        // Chunk marker position
        const cm = document.getElementById('chunk_marker');
        if (cm && config && typeof config.chunk_secs === 'number') {
          const cr = clamp(config.chunk_secs / 45.0, 0, 1);
          cm.style.left = `${Math.round(cr*100)}%`;
          cm.style.display = 'block';
        }

        // Raw totals
        const raw = document.getElementById('raw_totals');
        if (raw) {
          raw.innerHTML = `
            <div>Input: ${fmtBytes(stats.input_bytes)} &nbsp; ${(stats.input_samples||0).toLocaleString()} samples &nbsp; ${(stats.input_secs||0).toFixed(2)} s</div>
            <div>Processed: ${fmtBytes(stats.processed_bytes)} &nbsp; ${(stats.processed_samples||0).toLocaleString()} samples &nbsp; ${(stats.processed_secs||0).toFixed(2)} s</div>
            <div>Output: ${fmtBytes(stats.output_bytes)} &nbsp; ${(stats.output_samples||0).toLocaleString()} samples &nbsp; ${(stats.output_secs||0).toFixed(2)} s</div>
          `;
        }
        prevStats = stats;
        prevStatsAt = now;
      } catch (_e) {
        // ignore
      }
    }
    setInterval(loadStats, 1000);
  </script>
  </head>
  <body>
    <div class="container">
      <h1>pa&lambda;-stem-separator</h1>
      <div id="status" class="status"></div>

      <div class="section">
        <h2>Service</h2>
        <div class="row"><label>Status</label><div><span id="svc_state">-</span> &nbsp; <button id="svc_btn" class="primary" onclick="startService()">Start</button> &nbsp; <button id="logs_btn" onclick="toggleLogs()">Show Logs</button></div></div>
        <div id="logs_wrap" style="display:none;">
          <div id="logs" class="logs" onscroll="onLogsScroll()"></div>
        </div>
      </div>

      <div class="section">
        <h2>Live Stats</h2>
        <div class="row"><label>Latency</label>
          <div style="flex:1; display:flex; align-items:center; gap:8px;">
            <div style="flex:1; height:10px; background:#eee; border-radius:6px; overflow:hidden; position:relative;">
              <div id="latency_bar_fill" style="height:100%; width:0%; background:#22c55e"></div>
              <div id="chunk_marker" style="position:absolute; top:-2px; bottom:-2px; width:2px; background:#81A1C1; display:none;"></div>
            </div>
            <div id="latency_label" style="width:70px; text-align:right;">0.00 s</div>
          </div>
        </div>
        <div class="row"><label>Throughput</label>
          <div>In <span id="in_rate">0 B/s</span> &nbsp; Out <span id="out_rate">0 B/s</span> &nbsp; <span id="rtf_label">RTF 0.00x</span></div>
        </div>
        <div class="row"><label>Raw Totals</label>
          <div id="raw_totals" style="display:flex; flex-direction:column; gap:4px; font-size: 13px;"></div>
        </div>
      </div>

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
        Route("/api/stats", get_stats),
        Route("/api/service/status", service_status),
        Route("/api/service", service_action, methods=["POST"]),
        Route("/api/logs", get_logs),
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
