/* IHCq · image viewer, ROI drawing, heat and tumour layers, cell table, live histogram
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
/* ---------- viewer ---------- */
const cv = $("#cv"), ctx = cv.getContext("2d"), viewer = $("#viewer"), tip = $("#tip");
function loadImg(src) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; }); }
async function loadImages(j) { const [o, c, p] = await Promise.all([loadImg(j.original), loadImg(j.overlays.cells || j.original), loadImg(j.overlays.positivity)]); state.imgs = { original: o, cells: c, positivity: p, cap: c.height - o.height }; }
function fitView() { const r = viewer.getBoundingClientRect(); cv.width = Math.round(r.width * devicePixelRatio); cv.height = Math.round(r.height * devicePixelRatio); const im = state.imgs.original; if (!im) return; state.base = Math.min(cv.width / im.width, cv.height / im.height); state.zoom = 1; state.pan = { x: (cv.width - im.width * state.base) / 2, y: (cv.height - im.height * state.base) / 2 }; }
function clampPan() { const im = state.imgs.original; if (!im) return; const sc = state.base * state.zoom, w = im.width * sc, h = im.height * sc;
  if (w <= cv.width) state.pan.x = (cv.width - w) / 2; else state.pan.x = Math.min(0, Math.max(cv.width - w, state.pan.x));
  if (h <= cv.height) state.pan.y = (cv.height - h) / 2; else state.pan.y = Math.min(0, Math.max(cv.height - h, state.pan.y)); }
function drawViewer() {
  const im = state.imgs.original; if (!im) return; clampPan(); const sc = state.base * state.zoom;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = css("--bg2"); ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.imageSmoothingEnabled = sc < 2;
  ctx.setTransform(sc, 0, 0, sc, state.pan.x, state.pan.y);
  ctx.drawImage(im, 0, 0);
  if (state.layer === "heat") { ctx.globalAlpha = $("#opacity").value / 100; const sm = ctx.imageSmoothingEnabled; ctx.imageSmoothingEnabled = true; ctx.drawImage(heatCanvas(), 0, 0, im.width, im.height); ctx.imageSmoothingEnabled = sm; ctx.globalAlpha = 1; }
  else if (state.imgs[state.layer]) { ctx.globalAlpha = $("#opacity").value / 100; const ov = state.imgs[state.layer]; ctx.drawImage(ov, 0, state.imgs.cap, im.width, im.height, 0, 0, im.width, im.height); ctx.globalAlpha = 1; }
  if (state.layer === "tumour") { const j0 = state.results[state.cur]; ctx.lineWidth = 2 / sc;
    for (const c of j0.cells) { if (c[6] < 0) continue; const r = Math.sqrt(c[2] / Math.PI) + 2; ctx.beginPath(); ctx.arc(c[0], c[1], r, 0, 7); ctx.strokeStyle = c[6] ? "#30d158" : "rgba(160,160,170,.7)"; ctx.stroke(); } }
  const K = state.clicks[state.cur]; if (K) { for (const [k, col] of [["tumour", "#30d158"], ["stroma", "#8e8e93"]]) for (const [x, y] of K[k]) { ctx.beginPath(); ctx.arc(x, y, 6 / sc, 0, 7); ctx.fillStyle = col; ctx.fill(); ctx.lineWidth = 2 / sc; ctx.strokeStyle = "#fff"; ctx.stroke(); } }
  if (typeof drawMeasure === "function") drawMeasure(sc);
  // ROI polygons
  const R = state.rois[state.cur] || { include: [], exclude: [] };
  const poly = (pts, col, dash, close) => { if (pts.length < 1) return; ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); if (close) ctx.closePath(); ctx.lineWidth = 2.5 / sc; ctx.strokeStyle = col; ctx.setLineDash(dash ? [8 / sc, 5 / sc] : []); ctx.stroke(); ctx.setLineDash([]); if (close) { ctx.fillStyle = col; ctx.globalAlpha = .10; ctx.fill(); ctx.globalAlpha = 1; } pts.forEach(p => { ctx.beginPath(); ctx.arc(p[0], p[1], 3.5 / sc, 0, 7); ctx.fillStyle = col; ctx.fill(); }); };
  R.include.forEach((p, i) => { poly(p, "#3dd68c", false, true); const cx = p.reduce((a, q) => a + q[0], 0) / p.length, cy = p.reduce((a, q) => a + q[1], 0) / p.length; ctx.beginPath(); ctx.arc(cx, cy, 11 / sc, 0, 7); ctx.fillStyle = REGCOL[i % REGCOL.length]; ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = `600 ${12 / sc}px -apple-system, system-ui`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(String(i + 1), cx, cy); ctx.textAlign = "left"; ctx.textBaseline = "alphabetic"; });
  R.exclude.forEach(p => poly(p, "#ff5c72", true, true));
  $("#roi-compare").disabled = !R.include.length;
  if (state.drawing) poly(state.drawing.pts, state.drawing.tool === "include" ? "#3dd68c" : "#ff5c72", true, false);
  const j = state.results[state.cur];
  if ($("#show-hot").checked && j && j.summary.hotspot_xy) { const [hx, hy] = j.summary.hotspot_xy; const rr = Math.sqrt((j.summary.hotspot_window || 500) / Math.max(1, j.cells.length)) * Math.sqrt(im.width * im.height) * 0.56; ctx.beginPath(); ctx.arc(hx, hy, rr, 0, 7); ctx.lineWidth = 3 / sc; ctx.strokeStyle = "#ff4d5e"; ctx.setLineDash([6 / sc, 4 / sc]); ctx.stroke(); ctx.setLineDash([]); ctx.font = `bold ${13 / sc}px ${css("--mono")}`; ctx.fillStyle = "#ff4d5e"; ctx.fillText(`hotspot ${fmt(j.summary.hotspot_pct_positive)}%`, hx - rr, hy - rr - 6 / sc); }
  if (state.hover) { const [x, y, a] = state.hover; const r = Math.sqrt(a / Math.PI) + 3; ctx.lineWidth = 2 / sc; ctx.strokeStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); }
  $("#zoom-label").textContent = Math.round(state.zoom * 100) + "%";
}
function heatCanvas() {
  const j = state.results[state.cur]; const im = state.imgs.original;
  if (state.heat && state.heat.id === j.id && state.heat.th === JSON.stringify(state.th)) return state.heat.c;
  const f = 4, w = Math.ceil(im.width / f), h = Math.ceil(im.height / f); const acc = new Float32Array(w * h), tot = new Float32Array(w * h);
  const r = Math.max(6, Math.round(Math.sqrt(im.width * im.height / Math.max(1, j.cells.length)) * 2.2 / f)); const r2 = r * r;
  for (const c of j.cells) { const cx = c[0] / f, cy = c[1] / f, pos = binOf(c[3]) > 0 ? 1 : 0;
    for (let y = Math.max(0, cy - r | 0); y <= Math.min(h - 1, cy + r | 0); y++) for (let x = Math.max(0, cx - r | 0); x <= Math.min(w - 1, cx + r | 0); x++) { const d2 = (x - cx) ** 2 + (y - cy) ** 2; if (d2 > r2) continue; const wgt = 1 - d2 / r2; acc[y * w + x] += wgt * pos; tot[y * w + x] += wgt; } }
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d"); const id = g.createImageData(w, h); const d = id.data;
  for (let i = 0; i < w * h; i++) { if (tot[i] < 0.6) continue; const v = acc[i] / tot[i]; const t = Math.min(1, v); const rr = t < .5 ? 79 + (246 - 79) * t * 2 : 246 + (255 - 246) * (t - .5) * 2, gg = t < .5 ? 131 + (201 - 131) * t * 2 : 201 - (201 - 77) * (t - .5) * 2, bb = t < .5 ? 255 - (255 - 69) * t * 2 : 69 - (69 - 94) * (t - .5) * 2; d[i * 4] = rr; d[i * 4 + 1] = gg; d[i * 4 + 2] = bb; d[i * 4 + 3] = 60 + 80 * Math.min(1, tot[i] / 3); }
  g.putImageData(id, 0, 0); state.heat = { id: j.id, th: JSON.stringify(state.th), c }; return c;
}
/* ROI tools */
$$("#roi-tools button").forEach(b => b.onclick = () => { const t = b.dataset.tool; if (t === "clear") { state.rois[state.cur] = { include: [], exclude: [] }; state.drawing = null; state.tool = null; $$("#roi-tools button").forEach(x => x.setAttribute("aria-pressed", "false")); $("#roi-apply").disabled = false; $("#roi-apply").textContent = "Score full field"; drawViewer(); return; } state.tool = state.tool === t ? null : t; state.drawing = null; $$("#roi-tools button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.tool === state.tool))); viewer.style.cursor = state.tool ? "crosshair" : "grab"; });
function imgPoint(e) { const r = cv.getBoundingClientRect(); const sc = state.base * state.zoom; return [((e.clientX - r.left) * devicePixelRatio - state.pan.x) / sc, ((e.clientY - r.top) * devicePixelRatio - state.pan.y) / sc]; }
viewer.addEventListener("click", e => { if (e.target.closest(".vfloat")) return; if (state.mtool && !state.space) return; if (state.teach && state.cur) { const p = imgPoint(e); const K = state.clicks[state.cur] = state.clicks[state.cur] || { tumour: [], stroma: [] }; K[state.teach].push([Math.round(p[0]), Math.round(p[1])]); updateClickCount(); return drawViewer(); } if (state.pick && state.cur) { const p = imgPoint(e); return finishPick(p[0], p[1]); } if (!state.tool || !state.cur) return; const p = imgPoint(e); if (!state.drawing) state.drawing = { tool: state.tool, pts: [] }; state.drawing.pts.push([Math.round(p[0]), Math.round(p[1])]); drawViewer(); });
viewer.addEventListener("dblclick", e => { if (state.mtool) return; if (!state.drawing) return; e.preventDefault(); const d = state.drawing; state.drawing = null; if (d.pts.length >= 3) { const R = state.rois[state.cur] = state.rois[state.cur] || { include: [], exclude: [] }; R[d.tool].push(d.pts.slice(0, -1)); $("#roi-apply").disabled = false; $("#roi-apply").textContent = "Score inside ROI"; toast(`${d.tool === "include" ? "ROI" : "Exclusion"} closed — ${d.pts.length - 1} points`); } drawViewer(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && state.drawing) { state.drawing = null; drawViewer(); } });
$("#roi-apply").onclick = async () => { const j = state.results[state.cur]; if (!j) return; const R = state.rois[state.cur] || { include: [], exclude: [] }; const b = $("#roi-apply"); b.disabled = true; b.textContent = "Scoring…";
  try { const r = await fetch(`/api/roi?id=${j.id}`, { method: "POST", body: JSON.stringify(R) }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = j.truth; nj.note = j.note; add(nj); await show(nj.id); toast(R.include.length || R.exclude.length ? `Scored inside ROI (${fmt((nj.summary.roi_fraction || 0) * 100, 0)}% of tissue)` : "Scored the full field"); }
  catch (err) { toast(err.message, true); } finally { b.textContent = "Score inside ROI"; } };
$("#show-hot").onchange = drawViewer;
$("#roi-compare").onclick = async () => { const j = state.results[state.cur]; const R = state.rois[state.cur] || { include: [] }; if (!R.include.length) return toast("Draw at least one ＋ ROI first", true);
  try { const r = await fetch(`/api/regions?id=${j.id}`, { method: "POST", body: JSON.stringify({ include: R.include }) }); const d = await r.json(); if (!r.ok) throw new Error(d.error);
    $("#rtab tbody").innerHTML = d.regions.map(g => `<tr><td><span class="bdot" style="background:${REGCOL[(g.region - 1) % REGCOL.length]}"></span>Region ${g.region}</td><td class="n">${fmt(g.n_cells, 0)}</td><td class="n"><b>${fmt(g.pct_positive)}</b></td><td class="n">${g.pct_positive_ci95 ? g.pct_positive_ci95.join("–") : "—"}</td><td class="n">${fmt(g.h_score)}</td><td class="n">${fmt(g.irs, 0)}</td><td class="n">${fmt(g.pct_3plus)}</td><td class="n">${fmt(g.dab_area_fraction_pct)}</td><td class="n">${g.cells_per_mm2 != null ? fmt(g.cells_per_mm2, 0) + " /mm²" : fmt(g.cells_per_tissue_px1e4, 2) + " /10⁴px"}</td></tr>`).join("");
    $("#reg-test").innerHTML = d.test ? `${d.test.test}: <span class="pval ${d.test.p < .05 ? "sig" : "ns"}">${d.test.p < .001 ? "p < 0.001" : "p = " + d.test.p.toFixed(3)}</span>` : (d.regions.length === 2 ? "" : "draw exactly two regions for a significance test");
    $("#regions").hidden = false; state.showRegionNums = true; drawViewer(); } catch (err) { toast(err.message, true); } };
const REGCOL = ["#0a84ff", "#bf5af2", "#30d158", "#ff9f0a", "#ff375f", "#64d2ff"];
$$("#layers button").forEach(b => b.onclick = () => setLayer(b.dataset.layer));
function setLayer(l) { state.layer = l; $$("#layers button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.layer === l))); drawViewer(); }
$("#opacity").oninput = drawViewer; $("#fit").onclick = () => { fitView(); drawViewer(); };
viewer.addEventListener("wheel", e => { e.preventDefault(); const r = cv.getBoundingClientRect(); const mx = (e.clientX - r.left) * devicePixelRatio, my = (e.clientY - r.top) * devicePixelRatio; const f = Math.exp(-e.deltaY * 0.0015); const nz = Math.min(12, Math.max(1, state.zoom * f)); const k = nz / state.zoom; state.pan.x = mx - (mx - state.pan.x) * k; state.pan.y = my - (my - state.pan.y) * k; state.zoom = nz; if (nz === 1) fitView(); drawViewer(); }, { passive: false });
let drag = null; viewer.addEventListener("pointerdown", e => { if ((state.mtool && !state.space) || state.tool || state.pick || state.teach || e.target.closest(".vfloat")) return; drag = { x: e.clientX, y: e.clientY, px: state.pan.x, py: state.pan.y }; viewer.setPointerCapture(e.pointerId); });
viewer.addEventListener("pointerup", () => drag = null);
viewer.addEventListener("pointermove", e => {
  if (drag) { state.pan.x = drag.px + (e.clientX - drag.x) * devicePixelRatio; state.pan.y = drag.py + (e.clientY - drag.y) * devicePixelRatio; drawViewer(); return; }
  const j = state.results[state.cur]; if (!j || !j.cells.length) return;
  const r = cv.getBoundingClientRect(); const sc = state.base * state.zoom; const ix = ((e.clientX - r.left) * devicePixelRatio - state.pan.x) / sc, iy = ((e.clientY - r.top) * devicePixelRatio - state.pan.y) / sc;
  let best = null, bd = 1e9; for (const c of j.cells) { const d = (c[0] - ix) ** 2 + (c[1] - iy) ** 2; if (d < bd) { bd = d; best = c; } }
  if (best && bd < Math.max(64, best[2])) { const b = binOf(best[3]); state.hover = best; tip.hidden = false; tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px"; tip.innerHTML = `<i style="background:var(${BIN[b]})"></i>${BINNAME[b]} · DAB ${best[3].toFixed(3)} · hema ${best[4].toFixed(2)} · ${best[2]} px${best[7] >= 0 ? ` · membrane ${["none", "incomplete", "complete"][best[7]]}${best[8] != null ? " " + Math.round(best[8] * 100) + "%" : ""}` : ""}${best[6] >= 0 ? ` · ${best[6] ? "tumour" : "stroma"}` : ""}`; }
  else { state.hover = null; tip.hidden = true; }
  drawViewer();
});
viewer.addEventListener("pointerleave", () => { state.hover = null; tip.hidden = true; drawViewer(); });
new ResizeObserver(() => { if (state.cur) { fitView(); drawViewer(); } }).observe(viewer);

/* ---------- per-cell table linked to the viewer ---------- */
function renderCells() {
  const j = state.results[state.cur]; const tb = $("#ctab tbody"); if (!j) return;
  let rows = j.cells.map((c, i) => ({ i: i + 1, x: c[0], y: c[1], area: c[2], dab: c[3], hema: c[4], bin: binOf(c[3]), tum: c[6], mem: c[8] == null ? -1 : c[8], memc: c[7], ref: c }));
  const nAll = rows.length;
  if (state.cfilter !== "all") rows = rows.filter(r => r.bin === +state.cfilter);
  const { c, dir } = state.csort; rows.sort((a, b) => (a[c] > b[c] ? 1 : a[c] < b[c] ? -1 : 0) * dir);
  const LIMIT = 600; const shown = rows.slice(0, LIMIT);
  $("#cell-count").textContent = `${rows.length}${rows.length !== nAll ? " of " + nAll : ""}${rows.length > LIMIT ? " · first " + LIMIT + " shown" : ""}`;
  tb.innerHTML = shown.map(r => `<tr data-x="${r.x}" data-y="${r.y}"><td class="n">${r.i}</td><td><span class="bdot" style="background:var(${BIN[r.bin]})"></span>${BINNAME[r.bin]}</td><td class="n">${r.dab.toFixed(3)}</td><td class="n">${r.hema.toFixed(3)}</td><td class="n">${r.area}</td><td>${r.tum === 1 ? "tumour" : r.tum === 0 ? '<span class="mut">stroma</span>' : "—"}</td><td>${r.memc >= 0 ? ["none", "incomplete", "complete"][r.memc] + (r.mem >= 0 ? ` <span class="mut">${Math.round(r.mem * 100)}%</span>` : "") : "—"}</td><td class="n">${r.x.toFixed(0)}</td><td class="n">${r.y.toFixed(0)}</td></tr>`).join("");
  $$("#ctab th").forEach(th => th.classList.toggle("sorted", th.dataset.c === c));
}
$$("#ctab th").forEach(th => th.onclick = () => { const c = th.dataset.c; state.csort = { c, dir: state.csort.c === c ? -state.csort.dir : (c === "i" || c === "x" || c === "y" ? 1 : -1) }; renderCells(); });
$$("#cell-filter button").forEach(b => b.onclick = () => { state.cfilter = b.dataset.f; $$("#cell-filter button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); renderCells(); });
$("#ctab tbody").addEventListener("click", e => { const tr = e.target.closest("tr"); if (!tr) return; const x = +tr.dataset.x, y = +tr.dataset.y; const j = state.results[state.cur];
  state.zoom = Math.max(state.zoom, 4); const sc = state.base * state.zoom; state.pan.x = cv.width / 2 - x * sc; state.pan.y = cv.height / 2 - y * sc;
  state.hover = j.cells.find(c => c[0] === x && c[1] === y) || null; $$("#ctab tr.hl").forEach(r => r.classList.remove("hl")); tr.classList.add("hl"); drawViewer(); });

/* ---------- histogram with draggable cut points ---------- */
const hist = $("#hist"), hctx = hist.getContext("2d");
function binOf(v) { const t = state.th; return (v >= t.weak) + (v >= t.moderate) + (v >= t.strong); }
function histGeom() { const W = hist.width, H = hist.height, pad = { l: 34, r: 10, t: 12, b: 24 }; const j = state.results[state.cur]; const vals = j.cells.map(c => c[3]); const xmax = Math.max(1.0, ...vals) * 1.05; return { W, H, pad, vals, xmax, X: v => pad.l + v / xmax * (W - pad.l - pad.r) }; }
function drawHist() {
  const j = state.results[state.cur]; if (!j) return; hist.width = hist.clientWidth * devicePixelRatio; hist.height = 190 * devicePixelRatio; hctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const W = hist.clientWidth, H = 190, pad = { l: 34, r: 10, t: 26, b: 24 }; const vals = j.cells.map(c => c[3]);
  hctx.clearRect(0, 0, W, H);
  if (!vals.length) { hctx.fillStyle = css("--mut"); hctx.font = "12px " + css("--ui"); hctx.fillText("no nuclei in this field — pixel metrics only", pad.l, H / 2); return; }
  const xmax = Math.max(1.0, ...vals) * 1.05, nb = 60, bw = xmax / nb, counts = new Array(nb).fill(0);
  for (const v of vals) counts[Math.min(nb - 1, Math.floor(v / bw))]++;
  const ymax = Math.max(...counts); const X = v => pad.l + v / xmax * (W - pad.l - pad.r), Y = c => H - pad.b - c / ymax * (H - pad.t - pad.b);
  hctx.strokeStyle = css("--line2"); hctx.lineWidth = 1; hctx.beginPath(); hctx.moveTo(pad.l, H - pad.b); hctx.lineTo(W - pad.r, H - pad.b); hctx.stroke();
  for (let i = 0; i < nb; i++) { const v0 = i * bw; const b = binOf(v0 + bw / 2); hctx.fillStyle = css(BIN[b]); hctx.globalAlpha = .85; const x0 = X(v0), x1 = X(v0 + bw); hctx.fillRect(x0 + .5, Y(counts[i]), Math.max(1, x1 - x0 - 1), H - pad.b - Y(counts[i])); }
  hctx.globalAlpha = 1; hctx.fillStyle = css("--mut"); hctx.font = "10px " + css("--mono"); hctx.textAlign = "center";
  for (let v = 0; v <= xmax; v += xmax > 2 ? .5 : .25) hctx.fillText(v.toFixed(2), X(v), H - 8);
  hctx.save(); hctx.translate(10, H / 2); hctx.rotate(-Math.PI / 2); hctx.fillText("cells", 0, 0); hctx.restore();
  hctx.textAlign = "right"; hctx.fillText("DAB OD in scoring compartment", W - pad.r, 11);
  [["weak", 1], ["moderate", 2], ["strong", 3]].forEach(([k, b]) => { const x = X(state.th[k]); hctx.strokeStyle = css(BIN[b]); hctx.lineWidth = 2; hctx.setLineDash([4, 3]); hctx.beginPath(); hctx.moveTo(x, pad.t); hctx.lineTo(x, H - pad.b); hctx.stroke(); hctx.setLineDash([]); hctx.fillStyle = css(BIN[b]); hctx.beginPath(); hctx.moveTo(x - 6, pad.t); hctx.lineTo(x + 6, pad.t); hctx.lineTo(x, pad.t + 7); hctx.fill(); hctx.fillStyle = css("--ink"); hctx.font = "bold 10px " + css("--mono"); hctx.textAlign = "center"; hctx.fillText(state.th[k].toFixed(2), x, pad.t + 18); });
  state.histX = X; state.histInv = px => (px - pad.l) / (W - pad.l - pad.r) * xmax;
}
let hdrag = null;
hist.addEventListener("pointerdown", e => { const px = e.offsetX; let best = null, bd = 14; for (const k of ["weak", "moderate", "strong"]) { const d = Math.abs(state.histX(state.th[k]) - px); if (d < bd) { bd = d; best = k; } } if (best) { hdrag = best; hist.setPointerCapture(e.pointerId); } });
hist.addEventListener("pointermove", e => { if (!hdrag) return; let v = Math.max(0.01, state.histInv(e.offsetX)); const t = state.th; if (hdrag === "weak") v = Math.min(v, t.moderate - .01); if (hdrag === "moderate") v = Math.max(t.weak + .01, Math.min(v, t.strong - .01)); if (hdrag === "strong") v = Math.max(t.moderate + .01, v); t[hdrag] = +v.toFixed(3); $("#" + hdrag).value = t[hdrag]; drawHist(); live(); });
hist.addEventListener("pointerup", () => { if (hdrag) renderCells(); hdrag = null; });
function allred(bins) { const n = bins.length; if (!n) return null; const pos = bins.filter(b => b > 0); const f = pos.length / n; const ps = f === 0 ? 0 : f <= .01 ? 1 : f <= .1 ? 2 : f <= 1 / 3 ? 3 : f <= 2 / 3 ? 4 : 5; const is = pos.length ? Math.round(pos.reduce((a, b) => a + b, 0) / pos.length) : 0; return ps + is; }
function live() {
  if (state.layer === "heat") drawViewer();
  const j = state.results[state.cur]; if (!j || !j.cells.length) { $("#live").innerHTML = ""; $("#binbar").innerHTML = ""; return; }
  const bins = j.cells.map(c => binOf(c[3])); const n = bins.length; const p = [0, 1, 2, 3].map(k => bins.filter(b => b === k).length / n * 100);
  const H = p[1] + 2 * p[2] + 3 * p[3];
  const changed = Math.abs(state.th.weak - j.thresholds.weak) + Math.abs(state.th.moderate - j.thresholds.moderate) + Math.abs(state.th.strong - j.thresholds.strong) > 1e-6;
  $("#live").innerHTML = `<div><b>${H.toFixed(0)}</b><small>H-score${changed ? " · live" : ""}</small></div><div><b>${(100 - p[0]).toFixed(1)}%</b><small>positive</small></div><div><b>${allred(bins)}</b><small>Allred</small></div><div><b>${p[3].toFixed(1)}%</b><small>3+ cells</small></div>`;
  $("#binbar").innerHTML = p.map((v, k) => `<span style="width:${v}%;background:var(${BIN[k]})" title="${BINNAME[k]}: ${v.toFixed(1)}%"></span>`).join("");
  $("#apply").disabled = !changed;
}
$("#apply").onclick = applyTh; $("#reset-th").onclick = () => { const j = state.results[state.cur]; if (!j) return; state.th = { ...j.thresholds }; ["weak", "moderate", "strong"].forEach(k => $("#" + k).value = state.th[k]); drawHist(); live(); };
async function applyTh() {
  const j = state.results[state.cur]; if (!j) return; $("#apply").disabled = true; $("#apply").textContent = "Re-binning…";
  try { const r = await fetch(`/api/rebin?id=${j.id}&weak=${state.th.weak}&moderate=${state.th.moderate}&strong=${state.th.strong}`, { method: "POST" }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = j.truth; nj.note = j.note; add(nj); await show(nj.id); toast("Cut points applied. Session table updated."); }
  catch (err) { toast(err.message, true); } finally { $("#apply").textContent = "Apply cut points to this image"; }
}
