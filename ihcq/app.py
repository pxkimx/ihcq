"""Local desktop UI: `ihcq app` (or double-click IHCQ.app).

A small HTTP server on 127.0.0.1 with one page.  Drop images, set options,
read scores, look at the QC overlays, download the session's results.  No
data leaves the machine; nothing is installed beyond ihcq itself.
"""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config

HOST, PORT = "127.0.0.1", 8765
OUT = Path(tempfile.mkdtemp(prefix="ihcq_"))
SESSION = {"rows": [], "lock": threading.Lock(), "server": None}


def _cfg_from_query(q: dict) -> Config:
    cfg = Config()
    g = lambda k, d=None: (q.get(k, [d]) or [d])[0]
    if g("compartment"): cfg.compartment = g("compartment")
    if g("backend"): cfg.backend = g("backend")
    if g("statistic"): cfg.cell_statistic = g("statistic")
    if g("segment_on"): cfg.segment_on = g("segment_on")
    if g("mpp"): cfg.mpp = float(g("mpp"))
    if g("radius"): cfg.nucleus_radius_px = int(float(g("radius")))
    for k in ("weak", "moderate", "strong"):
        if g(k): setattr(cfg.thresholds, k, float(g(k)))
    if any(g(k) for k in ("weak", "moderate", "strong")):
        cfg.profile_name = "app-thresholds"
    if g("white"):
        cfg.white_point = [float(v) for v in g("white").split(",")]
    if g("segment") == "0": cfg.segment = False
    return cfg.validate()


def _score(rgb: np.ndarray, cfg: Config, stem: str) -> dict:
    from .pipeline import analyze, write_overlays
    res = analyze(rgb, cfg)
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)[:60] or "image"
    stamp = f"{stem}_{int(time.time()*1000) % 100000}"
    paths = write_overlays(rgb, res, OUT, stamp)
    cells_url = None
    if len(res.cells):
        p = OUT / f"{stamp}_cells.csv"; res.cells.to_csv(p, index=False); cells_url = f"/out/{p.name}"
    row = {"image": stem, **res.summary}
    with SESSION["lock"]:
        SESSION["rows"].append(row)
        pd.DataFrame(SESSION["rows"]).to_csv(OUT / "session_results.csv", index=False)
    return {"summary": row, "qc": res.qc,
            "overlays": {k: f"/out/{v.name}" for k, v in paths.items()},
            "cells_csv": cells_url, "results_csv": "/out/session_results.csv", "n_session": len(SESSION["rows"])}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=lambda o: None).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/demo":
            from .synth import make_field
            q = urllib.parse.parse_qs(u.query)
            rgb, truth, ts, _ = make_field(n_cells=350, fractions=(0.4, 0.2, 0.25, 0.15), seed=int(time.time()) % 1000)
            out = _score(rgb, _cfg_from_query(q), "demo_field")
            out["truth"] = {"h_score": ts["true_h_score"], "pct_positive": ts["true_pct_positive"], "n_cells": ts["true_n_cells"]}
            return self._send(200, out)
        if u.path.startswith("/out/"):
            p = (OUT / Path(u.path[5:]).name)
            if not p.exists():
                return self._send(404, {"error": "not found"})
            ctype = "image/png" if p.suffix == ".png" else "text/csv"
            data = p.read_bytes()
            self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
            if p.suffix == ".csv":
                self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
            self.end_headers(); self.wfile.write(data); return
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/quit":
            self._send(200, {"ok": True})
            threading.Thread(target=SESSION["server"].shutdown, daemon=True).start()
            return
        if u.path == "/api/score":
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n)
            name = (q.get("name", ["image"]) or ["image"])[0]
            try:
                from .io import _to_rgb8
                from PIL import Image
                import io as _io
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(_io.BytesIO(raw)) as im:
                    rgb = _to_rgb8(np.array(im.convert("RGB")))
                cfg = _cfg_from_query(q)
                out = _score(rgb, cfg, Path(name).stem)
                return self._send(200, out)
            except Exception as e:
                return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "not found"})


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>ihcq</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f4f5f2;--card:#fff;--ink:#16191a;--mut:#6b746e;--line:#d6dcd3;--acc:#1b3fa0;--dab:#7a3b12;--warn:#a96d08;--bad:#c22f4c}
@media(prefers-color-scheme:dark){:root{--bg:#111416;--card:#1a1f22;--ink:#e8ede9;--mut:#8d978f;--line:#2c3336;--acc:#7fa4ff;--dab:#d9a06b;--warn:#e2a544;--bad:#ff7e93}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,system-ui,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:12px 20px;border-bottom:1px solid var(--line)}
header b{font-size:18px;letter-spacing:-.02em}header span{color:var(--mut);font-size:12px}header .sp{flex:1}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:7px 12px;border-radius:7px;cursor:pointer}
button.p{background:var(--acc);border-color:var(--acc);color:#fff}button:disabled{opacity:.5}
main{display:grid;grid-template-columns:320px 1fr;gap:16px;padding:16px 20px;max-width:1400px;margin:0 auto}
@media(max-width:860px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.card+.card{margin-top:12px}
h3{margin:0 0 10px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mut);font-weight:600}
label{display:block;font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em;margin:8px 0 3px}
input,select{width:100%;font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.row{display:flex;gap:8px}.row>*{flex:1;min-width:0}
.drop{border:2px dashed var(--line);border-radius:10px;padding:26px 14px;text-align:center;cursor:pointer;color:var(--mut)}
.drop.over,.drop:hover{border-color:var(--acc);color:var(--ink)}.drop b{display:block;color:var(--ink);font-size:15px;margin-bottom:4px}
.big{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.big div{border:1px solid var(--line);border-radius:8px;padding:10px 12px}.big b{display:block;font-size:30px;font-weight:600;letter-spacing:-.02em;line-height:1.1}
.big span{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.qc{margin-top:10px;font-size:13px}.qc div{padding:6px 10px;border-left:3px solid var(--warn);background:color-mix(in srgb,var(--warn) 10%,transparent);border-radius:0 6px 6px 0;margin-bottom:5px}
.tabs{display:flex;gap:6px;margin:12px 0 8px}.tabs button[aria-pressed=true]{background:var(--acc);border-color:var(--acc);color:#fff}
img.ov{width:100%;border:1px solid var(--line);border-radius:8px;background:#fff}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}th,td{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em}td.n,th.n{text-align:right}
.tw{overflow:auto}.mut{color:var(--mut);font-size:12.5px}.busy{color:var(--acc)}a{color:var(--acc)}
</style></head><body>
<header><b>ihcq</b><span>chromogenic IHC quantification · everything stays on this Mac</span><div class="sp"></div>
<button id="demo">Score a demo field</button><button id="quit" title="Stop the local server">Quit</button></header>
<main>
<section>
 <div class="card"><h3>Images</h3>
  <div class="drop" id="drop"><b>Drop IHC images here</b>PNG · JPG · TIFF — or click to choose. Several at once is fine.<input id="file" type="file" accept="image/*" multiple hidden></div>
  <p class="mut" id="status" style="margin:10px 0 0">Waiting for an image.</p></div>
 <div class="card"><h3>Analysis</h3>
  <label>Compartment</label><select id="compartment"><option value="nuclear">Nuclear (Ki-67, ER, PR, p53)</option><option value="membrane">Membrane (HER2, PD-L1)</option><option value="cytoplasm">Cytoplasm</option></select>
  <div class="row"><div><label>Pixel size (µm/px)</label><input id="mpp" type="number" step="0.01" placeholder="e.g. 0.25"></div><div><label>or nuclear radius (px)</label><input id="radius" type="number" step="1" placeholder="8"></div></div>
  <label>Nucleus finder</label><select id="backend"><option value="watershed">Classical (fast, no model)</option><option value="hybrid">Hybrid — StarDist + classical (best overall)</option><option value="stardist">StarDist only (precise on well-stained tissue)</option></select>
  <label>Per-cell statistic</label><select id="statistic"><option value="mean">Mean DAB OD</option><option value="median">Median</option><option value="p90">90th percentile (punctate / membrane)</option></select>
 </div>
 <div class="card"><h3>Intensity cut points (DAB OD)</h3>
  <div class="row"><div><label>0 / 1+</label><input id="weak" type="number" step="0.01" value="0.15"></div><div><label>1+ / 2+</label><input id="moderate" type="number" step="0.01" value="0.40"></div><div><label>2+ / 3+</label><input id="strong" type="number" step="0.01" value="0.80"></div></div>
  <p class="mut" style="margin:8px 0 0">Defaults are a starting point only. Calibrate on control tissue (<code>ihcq calibrate</code>) before reporting.</p></div>
 <div class="card"><h3>Session</h3><p class="mut" id="sess">No results yet.</p><p style="margin:8px 0 0"><a id="dl" href="/out/session_results.csv" download hidden>Download all results (CSV)</a></p></div>
</section>
<section>
 <div class="card" id="result"><h3>Result</h3><p class="mut">Drop an image, or press <em>Score a demo field</em> to see the output on a synthetic slide with known truth.</p></div>
 <div class="card"><h3>This session</h3><div class="tw"><table id="tbl"><thead><tr><th>image</th><th class="n">cells</th><th class="n">% +</th><th class="n">H-score</th><th class="n">Allred</th><th class="n">DAB area %</th><th>flags</th></tr></thead><tbody></tbody></table></div></div>
</section></main>
<script>
const $=s=>document.querySelector(s);const status=$('#status');
function opts(name){const p=new URLSearchParams();for(const k of['compartment','backend','statistic','mpp','radius','weak','moderate','strong']){const v=$('#'+k).value;if(v!=='')p.set(k,v)}if(name)p.set('name',name);return p.toString()}
function fmt(v,d=1){return (v===null||v===undefined||Number.isNaN(v))?'—':(typeof v==='number'?v.toFixed(d):v)}
function render(r){const s=r.summary;const R=$('#result');
 const truth=r.truth?`<p class="mut">Synthetic field — truth: H=${r.truth.h_score}, ${r.truth.pct_positive}% positive, ${r.truth.n_cells} cells.</p>`:'';
 R.innerHTML=`<h3>Result · ${s.image}</h3><div class="big">
  <div><b>${fmt(s.h_score,0)}</b><span>H-score</span></div><div><b>${fmt(s.pct_positive)}%</b><span>positive cells</span></div>
  <div><b>${fmt(s.allred_total,0)}</b><span>Allred</span></div><div><b>${fmt(s.dab_area_fraction_pct)}%</b><span>DAB area</span></div>
  <div><b>${fmt(s.n_cells,0)}</b><span>nuclei</span></div><div><b>${fmt(s.mean_dab_od_tissue,3)}</b><span>mean DAB OD</span></div></div>${truth}
  <div class="qc">${(r.qc||[]).map(f=>`<div>${f}</div>`).join('')}</div>
  <div class="tabs">${Object.keys(r.overlays).map((k,i)=>`<button data-k="${k}" aria-pressed="${i===0}">${{cells:'Cells by bin',positivity:'Positivity map',stains:'Stain separation'}[k]||k}</button>`).join('')}</div>
  <img class="ov" id="ov" src="${Object.values(r.overlays)[0]}">
  <p class="mut" style="margin-top:8px">${r.cells_csv?`<a href="${r.cells_csv}" download>Per-cell table (CSV)</a> · `:''}bins 1+/2+/3+ at ${s.thr_weak}/${s.thr_moderate}/${s.thr_strong} OD · ${s.compartment} · ${s.seconds}s</p>`;
 R.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{R.querySelectorAll('.tabs button').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');$('#ov').src=r.overlays[b.dataset.k]});
 const tr=document.createElement('tr');tr.innerHTML=`<td>${s.image}</td><td class="n">${fmt(s.n_cells,0)}</td><td class="n">${fmt(s.pct_positive)}</td><td class="n">${fmt(s.h_score)}</td><td class="n">${fmt(s.allred_total,0)}</td><td class="n">${fmt(s.dab_area_fraction_pct,2)}</td><td class="mut">${(r.qc||[]).length?r.qc.length+' flag'+(r.qc.length>1?'s':''):''}</td>`;
 $('#tbl tbody').prepend(tr);$('#sess').textContent=`${r.n_session} image${r.n_session>1?'s':''} scored.`;$('#dl').hidden=false}
async function scoreFiles(files){for(const f of files){status.innerHTML=`<span class="busy">Scoring ${f.name}…</span> ${$('#backend').value==='stardist'?'(first StarDist run downloads the model)':''}`;
 try{const r=await fetch('/api/score?'+opts(f.name),{method:'POST',body:f});const j=await r.json();if(!r.ok)throw new Error(j.error||r.statusText);render(j);status.textContent=`Scored ${f.name}.`}
 catch(e){status.innerHTML=`<span style="color:var(--bad)">${f.name}: ${e.message}</span>`}}}
const drop=$('#drop'),file=$('#file');drop.onclick=()=>file.click();file.onchange=()=>scoreFiles([...file.files]);
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',ev=>scoreFiles([...ev.dataTransfer.files].filter(f=>f.type.startsWith('image/')||/\.tiff?$/i.test(f.name))));
$('#demo').onclick=async()=>{status.innerHTML='<span class="busy">Scoring a synthetic field…</span>';const r=await fetch('/api/demo?'+opts());render(await r.json());status.textContent='Demo field scored.'};
$('#quit').onclick=async()=>{await fetch('/api/quit',{method:'POST'});document.body.innerHTML='<p style="padding:40px;font:15px system-ui">ihcq stopped. You can close this tab.</p>'};
</script></body></html>"""


def _port_open(host, port) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) == 0


def main(open_browser: bool = True, port: int = PORT):
    url = f"http://{HOST}:{port}/"
    if _port_open(HOST, port):
        print(f"ihcq is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return
    server = ThreadingHTTPServer((HOST, port), Handler)
    SESSION["server"] = server
    print(f"ihcq app at {url}   (outputs in {OUT})")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main(open_browser="--no-browser" not in sys.argv)
