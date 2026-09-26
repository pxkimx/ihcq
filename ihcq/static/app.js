/* ihcq desktop UI */
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const BIN = ["--b0", "--b1", "--b2", "--b3"], BINNAME = ["0", "1+", "2+", "3+"];
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : (typeof v === "number" ? v.toFixed(d) : String(v));
const state = { results: {}, order: [], cur: null, th: { weak: .15, moderate: .40, strong: .80 }, layer: "cells", zoom: 1, pan: { x: 0, y: 0 }, imgs: {}, hover: null, sort: { k: "image", dir: 1 } };

/* ---------- theme ---------- */
try { const t = localStorage.getItem("ihcq-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
$("#theme").onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); const nx = cur === "light" ? "dark" : "light"; document.documentElement.dataset.theme = nx; try { localStorage.setItem("ihcq-theme", nx); } catch (e) {} drawAll(); };
if (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: light)").matches) document.documentElement.dataset.theme = "light";

/* ---------- toast ---------- */
let toastT; function toast(msg, bad = false) { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, bad ? 6000 : 2600); }

/* ---------- tabs ---------- */
$$("#tabs button").forEach(b => b.onclick = () => showView(b.dataset.view));
function showView(v) { $$("#tabs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.view === v))); $$(".view").forEach(s => s.hidden = s.id !== "view-" + v); if (v === "session") renderSession(); if (v === "calibrate") renderCalib(); }

/* ---------- presets & settings ---------- */
const PRESETS = {
  nuclear: { compartment: "nuclear", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: true, ring: 3 },
  membrane: { compartment: "membrane", statistic: "p90", weak: .15, moderate: .40, strong: .80, segment: true, ring: 3 },
  cyto: { compartment: "cytoplasm", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: true, ring: 4 },
  pale: { compartment: "membrane", statistic: "p90", weak: .12, moderate: .20, strong: .36, segment: true, ring: 3 },
  pixels: { compartment: "nuclear", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: false, ring: 3 },
};
$("#preset").onchange = e => { const p = PRESETS[e.target.value]; for (const k of ["compartment", "statistic"]) $("#" + k).value = p[k]; for (const k of ["weak", "moderate", "strong", "ring"]) $("#" + k).value = p[k]; $("#segment").checked = p.segment; syncTh(); };
function settingsQuery(name) { const p = new URLSearchParams(); for (const k of ["compartment", "backend", "statistic", "mpp", "radius", "ring", "weak", "moderate", "strong"]) { const v = $("#" + k).value; if (v !== "") p.set(k, v); } if (!$("#segment").checked) p.set("segment", "0"); if (name) p.set("name", name); return p.toString(); }
function syncTh() { state.th = { weak: +$("#weak").value, moderate: +$("#moderate").value, strong: +$("#strong").value }; if (state.cur) { drawHist(); live(); } }
["weak", "moderate", "strong"].forEach(k => $("#" + k).oninput = syncTh);
$("#save-profile").onclick = () => { const cfg = { compartment: $("#compartment").value, cell_statistic: $("#statistic").value, backend: $("#backend").value, ring_px: +$("#ring").value || 3, mpp: $("#mpp").value ? +$("#mpp").value : null, nucleus_radius_px: $("#radius").value ? +$("#radius").value : null, segment: $("#segment").checked, thresholds: { weak: +$("#weak").value, moderate: +$("#moderate").value, strong: +$("#strong").value }, profile_name: "app-profile" }; const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" })); a.download = "ihcq_profile.json"; a.click(); toast("Profile saved — usable with  ihcq score --profile"); };
$("#load-profile").onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const c = JSON.parse(await f.text()); if (c.compartment) $("#compartment").value = c.compartment; if (c.cell_statistic) $("#statistic").value = c.cell_statistic; if (c.backend) $("#backend").value = c.backend; if (c.ring_px) $("#ring").value = c.ring_px; $("#mpp").value = c.mpp ?? ""; $("#radius").value = c.nucleus_radius_px ?? ""; if (c.segment !== undefined) $("#segment").checked = !!c.segment; if (c.thresholds) { $("#weak").value = c.thresholds.weak; $("#moderate").value = c.thresholds.moderate; $("#strong").value = c.thresholds.strong; } syncTh(); toast("Profile loaded: " + (c.profile_name || f.name)); } catch (err) { toast("Not a profile: " + err.message, true); } e.target.value = ""; };

/* ---------- upload queue ---------- */
const drop = $("#drop"), file = $("#file"), queue = $("#queue");
drop.onclick = () => file.click(); drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } };
file.onchange = () => { enqueue([...file.files]); file.value = ""; };
["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
document.addEventListener("drop", e => enqueue([...e.dataTransfer.files].filter(f => f.type.startsWith("image/") || /\.tiff?$/i.test(f.name))));
let running = false; const pending = [];
function enqueue(files) { for (const f of files) { const li = document.createElement("li"); li.innerHTML = `<span class="nm">${f.name}</span><span class="st">queued</span>`; queue.prepend(li); pending.push({ f, li }); } pump(); }
async function pump() {
  if (running) return; running = true;
  while (pending.length) {
    const { f, li } = pending.shift(); const st = $(".st", li); st.textContent = $("#backend").value === "watershed" ? "scoring" : "scoring · model"; st.className = "st busy";
    try { const r = await fetch("/api/score?" + settingsQuery(f.name), { method: "POST", body: f }); const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); st.textContent = "H " + fmt(j.summary.h_score, 0); st.className = "st done"; li.onclick = () => show(j.id); li.dataset.id = j.id; add(j); show(j.id); }
    catch (err) { st.textContent = "failed"; st.className = "st err"; li.title = err.message; toast(f.name + ": " + err.message, true); }
  }
  running = false;
}
/* demo menu */
const menu = $("#demo-menu"); $("#demo").onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; }; document.addEventListener("click", () => menu.hidden = true);
$("#demo").ondblclick = () => $$("button", menu)[0].click();
$$("button", menu).forEach(b => b.onclick = async () => { menu.hidden = true; if (b.dataset.kind === "real" && $("#preset").value !== "membrane" && $("#preset").value !== "pale") { $("#preset").value = "membrane"; $("#preset").dispatchEvent(new Event("change")); toast("Preset switched to Membrane marker for this stain"); } const li = document.createElement("li"); li.innerHTML = `<span class="nm">demo · ${b.textContent}</span><span class="st busy">scoring</span>`; queue.prepend(li); try { const r = await fetch(`/api/demo?kind=${b.dataset.kind}&` + settingsQuery()); const j = await r.json(); if (!r.ok) throw new Error(j.error); $(".st", li).textContent = "H " + fmt(j.summary.h_score, 0); $(".st", li).className = "st done"; li.onclick = () => show(j.id); li.dataset.id = j.id; add(j); show(j.id); } catch (err) { $(".st", li).textContent = "failed"; $(".st", li).className = "st err"; toast(err.message, true); } });
$("#quit").onclick = async () => { await fetch("/api/quit", { method: "POST" }); document.body.innerHTML = '<p style="padding:40px;font:15px system-ui">ihcq stopped. You can close this tab.</p>'; };

/* ---------- re-analyze / group / downloads ---------- */
$("#reanalyze").onclick = async () => { const j = state.results[state.cur]; if (!j) return; const b = $("#reanalyze"); b.disabled = true; b.textContent = "Re-analyzing…";
  try { const r = await fetch(`/api/reanalyze?id=${j.id}&` + settingsQuery(), { method: "POST" }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = j.truth; nj.note = j.note; add(nj); await show(nj.id); toast("Re-analyzed with the current settings"); }
  catch (err) { toast(err.message, true); } finally { b.textContent = "Re-analyze current image with these settings"; b.disabled = !state.cur; } };
["compartment", "backend", "statistic", "mpp", "radius", "ring", "segment"].forEach(k => $("#" + k).addEventListener("change", () => { if (state.cur) { const b = $("#reanalyze"); b.classList.add("primary"); b.textContent = "Re-analyze current image with these settings ↻"; } }));
async function setGroup(id, g) { const j = state.results[id]; if (!j) return; j.summary.group = g; await fetch("/api/group", { method: "POST", body: JSON.stringify({ id, group: g }) }); }
$("#group").addEventListener("change", e => { if (state.cur) { setGroup(state.cur, e.target.value.trim()); toast(e.target.value.trim() ? `Grouped as “${e.target.value.trim()}”` : "Group cleared"); } });
const dlm = $("#dl-menu"); $("#dl-btn").onclick = e => { e.stopPropagation(); dlm.hidden = !dlm.hidden; }; document.addEventListener("click", () => dlm.hidden = true);

/* ---------- results ---------- */
function add(j) { if (!state.results[j.id]) state.order.push(j.id); state.results[j.id] = j; $("#tab-count").textContent = state.order.length; $("#tab-count").hidden = false; }
async function show(id) {
  const j = state.results[id]; if (!j) return; state.cur = id; const s = j.summary;
  $$("#queue li").forEach(li => li.setAttribute("aria-current", String(li.dataset.id === id)));
  $("#empty").hidden = true; $("#result").hidden = false;
  $("#r-name").textContent = `${s.image} · ${s.width}×${s.height} · ${s.compartment} · ${s.seconds}s`;
  const st = $("#r-stain"); const kind = s.second_stain; st.className = "stain " + (kind === "dab" ? "" : kind === "eosin" ? "bad" : "unk");
  st.innerHTML = `<i></i>${kind === "dab" ? "Second stain is <b>DAB</b> — chromogenic IHC" : kind === "eosin" ? "Second stain is <b>eosin</b> — this is H&amp;E; DAB scores are not valid" : "Second stain <b>unrecognised</b> — check the stain separation"} <span class="mut">${s.second_stain_angle_to_dab}° from DAB · ${s.second_stain_angle_to_eosin}° from eosin</span>`;
  state.th = { ...j.thresholds }; $("#weak").value = state.th.weak; $("#moderate").value = state.th.moderate; $("#strong").value = state.th.strong;
  renderTiles(s); renderQC(j.qc);
  $("#stains").src = j.overlays.stains; $("#dl-cells").href = j.cells_csv || "#"; $("#dl-cells").style.visibility = j.cells_csv ? "visible" : "hidden";
  $("#truth").textContent = j.truth ? `Synthetic field — truth: H = ${j.truth.h_score}, ${j.truth.pct_positive}% positive, ${j.truth.n_cells} nuclei.` : (j.note || "");
  $("#group").value = s.group || ""; $("#reanalyze").disabled = false;
  $("#dl-orig").href = j.original; $("#dl-orig").download = s.image + "_original.png";
  $("#dl-cells-img").href = j.overlays.cells || "#"; $("#dl-cells-img").download = s.image + "_labelled_nuclei.png";
  $("#dl-pos").href = j.overlays.positivity; $("#dl-pos").download = s.image + "_positivity.png";
  $("#dl-stains").href = j.overlays.stains; $("#dl-stains").download = s.image + "_stain_separation.png";
  await loadImages(j); state.zoom = 1; state.pan = { x: 0, y: 0 }; fitView(); drawViewer(); drawHist(); live();
}
function tile(v, label, sub, color) { return `<div class="tile" style="--tc:${color}"><b>${v}</b><small>${label}</small>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }
function renderTiles(s) {
  const seg = s.n_cells !== undefined && s.n_cells !== null;
  $("#tiles").innerHTML =
    (seg ? tile(fmt(s.h_score, 0), "H-score", "0 – 300", `var(${BIN[Math.min(3, Math.floor((s.h_score || 0) / 100) + 1)]})`) : "") +
    (seg ? tile(fmt(s.pct_positive) + "%", "positive cells", `${s.n_cells} nuclei`, "var(--b2)") : "") +
    (seg ? tile(fmt(s.allred_total, 0), "Allred", `PS ${fmt(s.allred_ps, 0)} + IS ${fmt(s.allred_is, 0)}`, "var(--b3)") : "") +
    tile(fmt(s.dab_area_fraction_pct) + "%", "DAB area", "of tissue footprint", "var(--dab)") +
    tile(fmt(s.mean_dab_od_tissue, 3), "mean DAB OD", `p95 ${fmt(s.p95_dab_od_tissue, 2)}`, "var(--acc)") +
    (seg ? tile(fmt(s.cells_per_mm2 ?? s.cells_per_tissue_px1e4, s.cells_per_mm2 ? 0 : 2), s.cells_per_mm2 ? "nuclei / mm²" : "nuclei / 10⁴ px", `median r ${fmt(s.median_nucleus_radius_px)} px`, "var(--b0)") : "") +
    tile(fmt(s.tissue_fraction * 100, 0) + "%", "tissue in field", `white ${s.white_point_source}`, "var(--ok)");
}
function renderQC(flags) { $("#qc").innerHTML = (flags || []).map(f => `<div class="${/NOT meaningful|not valid/i.test(f) ? "bad" : ""}">${f}</div>`).join(""); }

/* ---------- viewer ---------- */
const cv = $("#cv"), ctx = cv.getContext("2d"), viewer = $("#viewer"), tip = $("#tip");
function loadImg(src) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; }); }
async function loadImages(j) { const [o, c, p] = await Promise.all([loadImg(j.original), loadImg(j.overlays.cells || j.original), loadImg(j.overlays.positivity)]); state.imgs = { original: o, cells: c, positivity: p, cap: c.height - o.height }; }
function fitView() { const r = viewer.getBoundingClientRect(); cv.width = Math.round(r.width * devicePixelRatio); cv.height = Math.round(r.height * devicePixelRatio); const im = state.imgs.original; if (!im) return; state.base = Math.min(cv.width / im.width, cv.height / im.height); state.zoom = 1; state.pan = { x: (cv.width - im.width * state.base) / 2, y: (cv.height - im.height * state.base) / 2 }; }
function drawViewer() {
  const im = state.imgs.original; if (!im) return; const sc = state.base * state.zoom;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = css("--bg2"); ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.imageSmoothingEnabled = sc < 2;
  ctx.setTransform(sc, 0, 0, sc, state.pan.x, state.pan.y);
  ctx.drawImage(im, 0, 0);
  if (state.layer !== "original") { ctx.globalAlpha = $("#opacity").value / 100; const ov = state.imgs[state.layer]; ctx.drawImage(ov, 0, state.imgs.cap, im.width, im.height, 0, 0, im.width, im.height); ctx.globalAlpha = 1; }
  if (state.hover) { const [x, y, a] = state.hover; const r = Math.sqrt(a / Math.PI) + 3; ctx.lineWidth = 2 / sc; ctx.strokeStyle = "#fff"; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); }
  $("#zoom-label").textContent = Math.round(state.zoom * 100) + "%";
}
$$("#layers button").forEach(b => b.onclick = () => setLayer(b.dataset.layer));
function setLayer(l) { state.layer = l; $$("#layers button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.layer === l))); drawViewer(); }
$("#opacity").oninput = drawViewer; $("#fit").onclick = () => { fitView(); drawViewer(); };
viewer.addEventListener("wheel", e => { e.preventDefault(); const r = cv.getBoundingClientRect(); const mx = (e.clientX - r.left) * devicePixelRatio, my = (e.clientY - r.top) * devicePixelRatio; const f = Math.exp(-e.deltaY * 0.0015); const nz = Math.min(12, Math.max(0.5, state.zoom * f)); const k = nz / state.zoom; state.pan.x = mx - (mx - state.pan.x) * k; state.pan.y = my - (my - state.pan.y) * k; state.zoom = nz; drawViewer(); }, { passive: false });
let drag = null; viewer.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, px: state.pan.x, py: state.pan.y }; viewer.setPointerCapture(e.pointerId); });
viewer.addEventListener("pointerup", () => drag = null);
viewer.addEventListener("pointermove", e => {
  if (drag) { state.pan.x = drag.px + (e.clientX - drag.x) * devicePixelRatio; state.pan.y = drag.py + (e.clientY - drag.y) * devicePixelRatio; drawViewer(); return; }
  const j = state.results[state.cur]; if (!j || !j.cells.length) return;
  const r = cv.getBoundingClientRect(); const sc = state.base * state.zoom; const ix = ((e.clientX - r.left) * devicePixelRatio - state.pan.x) / sc, iy = ((e.clientY - r.top) * devicePixelRatio - state.pan.y) / sc;
  let best = null, bd = 1e9; for (const c of j.cells) { const d = (c[0] - ix) ** 2 + (c[1] - iy) ** 2; if (d < bd) { bd = d; best = c; } }
  if (best && bd < Math.max(64, best[2])) { const b = binOf(best[3]); state.hover = best; tip.hidden = false; tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px"; tip.innerHTML = `<i style="background:var(${BIN[b]})"></i>${BINNAME[b]} · DAB ${best[3].toFixed(3)} · hema ${best[4].toFixed(2)} · ${best[2]} px`; }
  else { state.hover = null; tip.hidden = true; }
  drawViewer();
});
viewer.addEventListener("pointerleave", () => { state.hover = null; tip.hidden = true; drawViewer(); });
new ResizeObserver(() => { if (state.cur) { fitView(); drawViewer(); } }).observe(viewer);

/* ---------- histogram with draggable cut points ---------- */
const hist = $("#hist"), hctx = hist.getContext("2d");
function binOf(v) { const t = state.th; return (v >= t.weak) + (v >= t.moderate) + (v >= t.strong); }
function histGeom() { const W = hist.width, H = hist.height, pad = { l: 34, r: 10, t: 12, b: 24 }; const j = state.results[state.cur]; const vals = j.cells.map(c => c[3]); const xmax = Math.max(1.0, ...vals) * 1.05; return { W, H, pad, vals, xmax, X: v => pad.l + v / xmax * (W - pad.l - pad.r) }; }
function drawHist() {
  const j = state.results[state.cur]; if (!j) return; hist.width = hist.clientWidth * devicePixelRatio; hist.height = 190 * devicePixelRatio; hctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const W = hist.clientWidth, H = 190, pad = { l: 34, r: 10, t: 12, b: 24 }; const vals = j.cells.map(c => c[3]);
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
  hctx.textAlign = "left"; hctx.fillText("DAB OD in scoring compartment", pad.l, 9);
  [["weak", 1], ["moderate", 2], ["strong", 3]].forEach(([k, b]) => { const x = X(state.th[k]); hctx.strokeStyle = css(BIN[b]); hctx.lineWidth = 2; hctx.setLineDash([4, 3]); hctx.beginPath(); hctx.moveTo(x, pad.t); hctx.lineTo(x, H - pad.b); hctx.stroke(); hctx.setLineDash([]); hctx.fillStyle = css(BIN[b]); hctx.beginPath(); hctx.moveTo(x - 6, pad.t); hctx.lineTo(x + 6, pad.t); hctx.lineTo(x, pad.t + 7); hctx.fill(); hctx.fillStyle = css("--ink"); hctx.font = "bold 10px " + css("--mono"); hctx.textAlign = "center"; hctx.fillText(state.th[k].toFixed(2), x, pad.t + 18); });
  state.histX = X; state.histInv = px => (px - pad.l) / (W - pad.l - pad.r) * xmax;
}
let hdrag = null;
hist.addEventListener("pointerdown", e => { const px = e.offsetX; let best = null, bd = 14; for (const k of ["weak", "moderate", "strong"]) { const d = Math.abs(state.histX(state.th[k]) - px); if (d < bd) { bd = d; best = k; } } if (best) { hdrag = best; hist.setPointerCapture(e.pointerId); } });
hist.addEventListener("pointermove", e => { if (!hdrag) return; let v = Math.max(0.01, state.histInv(e.offsetX)); const t = state.th; if (hdrag === "weak") v = Math.min(v, t.moderate - .01); if (hdrag === "moderate") v = Math.max(t.weak + .01, Math.min(v, t.strong - .01)); if (hdrag === "strong") v = Math.max(t.moderate + .01, v); t[hdrag] = +v.toFixed(3); $("#" + hdrag).value = t[hdrag]; drawHist(); live(); });
hist.addEventListener("pointerup", () => hdrag = null);
function allred(bins) { const n = bins.length; if (!n) return null; const pos = bins.filter(b => b > 0); const f = pos.length / n; const ps = f === 0 ? 0 : f <= .01 ? 1 : f <= .1 ? 2 : f <= 1 / 3 ? 3 : f <= 2 / 3 ? 4 : 5; const is = pos.length ? Math.round(pos.reduce((a, b) => a + b, 0) / pos.length) : 0; return ps + is; }
function live() {
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

/* ---------- session ---------- */
function renderSession() {
  const rows = state.order.map(id => state.results[id].summary); const tb = $("#stbl tbody"); tb.innerHTML = "";
  const k = state.sort.k, dir = state.sort.dir; const sorted = [...state.order].sort((a, b) => { const x = state.results[a].summary[k], y = state.results[b].summary[k]; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
  $$("#stbl th").forEach(th => th.classList.toggle("sorted", th.dataset.k === k));
  for (const id of sorted) { const s = state.results[id].summary, q = state.results[id].qc || []; const tr = document.createElement("tr"); tr.setAttribute("aria-current", String(id === state.cur)); tr.onclick = () => { showView("score"); show(id); };
    tr.innerHTML = `<td>${s.image}</td><td><input class="grp" value="${s.group || ""}" placeholder="group"></td><td class="n">${fmt(s.n_cells, 0)}</td><td class="n">${fmt(s.pct_positive)}</td><td class="n">${fmt(s.pct_1plus)}</td><td class="n">${fmt(s.pct_2plus)}</td><td class="n">${fmt(s.pct_3plus)}</td><td class="n"><b>${fmt(s.h_score)}</b></td><td class="n">${fmt(s.allred_total, 0)}</td><td class="n">${fmt(s.dab_area_fraction_pct, 2)}</td><td class="n">${fmt(s.mean_dab_od_tissue, 3)}</td><td><span class="chip ${s.second_stain === "dab" ? "ok" : s.second_stain === "eosin" ? "bad" : "warn"}">${s.second_stain}</span></td><td class="n">${s.thr_weak}/${s.thr_moderate}/${s.thr_strong}</td><td>${q.length ? `<span class="chip warn" title="${q.join("\n")}">${q.length} flag${q.length > 1 ? "s" : ""}</span>` : ""}</td>`;
    const gi = $("input.grp", tr); gi.onclick = e => e.stopPropagation(); gi.onchange = async e => { await setGroup(id, e.target.value.trim()); renderStats(); }; tb.appendChild(tr); }
  renderStats();
  // stacked composition
  const st = $("#stack"); const n = rows.length; if (!n) { st.innerHTML = '<p class="mut">Nothing scored yet.</p>'; $("#hplot").innerHTML = ""; return; }
  const rh = 18, W = 520, L = 130; let svg = `<svg viewBox="0 0 ${W} ${n * rh + 22}">`;
  rows.forEach((s, i) => { let x = L; const y = i * rh + 4; svg += `<text x="${L - 6}" y="${y + 12}" text-anchor="end" font-size="10" font-family="${css("--mono")}" fill="${css("--ink2")}">${s.image.slice(0, 18)}</text>`; [s.pct_0 ?? (100 - (s.pct_positive || 0)), s.pct_1plus, s.pct_2plus, s.pct_3plus].forEach((v, k) => { const w = (v || 0) / 100 * (W - L - 40); svg += `<rect x="${x}" y="${y}" width="${Math.max(0, w)}" height="${rh - 5}" fill="${css(BIN[k])}" rx="2"><title>${BINNAME[k]}: ${fmt(v)}%</title></rect>`; x += w; }); });
  svg += `<text x="${L}" y="${n * rh + 18}" font-size="9" fill="${css("--mut")}">0%</text><text x="${W - 40}" y="${n * rh + 18}" font-size="9" fill="${css("--mut")}" text-anchor="end">100% of nuclei</text></svg>`; st.innerHTML = svg;
  // H-score plot
  let hp = `<svg viewBox="0 0 ${W} ${n * rh + 22}">`; [0, 100, 200, 300].forEach(v => { const x = L + v / 300 * (W - L - 40); hp += `<line x1="${x}" y1="2" x2="${x}" y2="${n * rh + 4}" stroke="${css("--line2")}"/><text x="${x}" y="${n * rh + 18}" font-size="9" text-anchor="middle" fill="${css("--mut")}">${v}</text>`; });
  rows.forEach((s, i) => { const y = i * rh + 4 + (rh - 5) / 2; const x = L + Math.min(300, s.h_score || 0) / 300 * (W - L - 40); const col = css(BIN[Math.min(3, Math.floor((s.h_score || 0) / 100) + 1)]); hp += `<text x="${L - 6}" y="${y + 4}" text-anchor="end" font-size="10" font-family="${css("--mono")}" fill="${css("--ink2")}">${s.image.slice(0, 18)}</text><line x1="${L}" y1="${y}" x2="${x}" y2="${y}" stroke="${col}" stroke-width="2" opacity=".5"/><circle cx="${x}" cy="${y}" r="5" fill="${col}"><title>H = ${fmt(s.h_score)}</title></circle>`; });
  $("#hplot").innerHTML = hp + "</svg>";
}
const PAL = ["--acc", "--dab", "--b0", "--ok", "--b3", "--b1"];
async function renderStats() {
  const m = $("#stat-metric").value; const r = await fetch("/api/stats?metric=" + m); const st = await r.json();
  const names = Object.keys(st.groups); const box = $("#boxplot"), tbl = $("#stat-table");
  if (!names.length) { box.innerHTML = ""; tbl.innerHTML = '<span class="mut">Assign groups to see statistics.</span>'; renderCor(); return; }
  const W = 520, H = 230, L = 46, B = 34; const all = names.flatMap(n => st.groups[n].values); const lo = Math.min(...all), hi = Math.max(...all); const span = (hi - lo) || 1; const Y = v => H - B - (v - lo) / span * (H - B - 14);
  let svg = `<svg viewBox="0 0 ${W} ${H}">`; const gw = (W - L - 10) / names.length;
  [lo, lo + span / 2, hi].forEach(v => { svg += `<line x1="${L}" y1="${Y(v)}" x2="${W - 10}" y2="${Y(v)}" stroke="${css("--line2")}"/><text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end" font-size="9" fill="${css("--mut")}" font-family="${css("--mono")}">${fmt(v, 1)}</text>`; });
  names.forEach((n, i) => { const g = st.groups[n], col = css(PAL[i % PAL.length]), cx = L + gw * (i + .5), bw = Math.min(46, gw * .5);
    if (g.n >= 3) svg += `<rect x="${cx - bw / 2}" y="${Y(g.q3)}" width="${bw}" height="${Math.max(1, Y(g.q1) - Y(g.q3))}" fill="${col}" opacity=".25" rx="3"/><line x1="${cx - bw / 2}" y1="${Y(g.median)}" x2="${cx + bw / 2}" y2="${Y(g.median)}" stroke="${col}" stroke-width="2.5"/><line x1="${cx}" y1="${Y(g.min)}" x2="${cx}" y2="${Y(g.q1)}" stroke="${col}"/><line x1="${cx}" y1="${Y(g.q3)}" x2="${cx}" y2="${Y(g.max)}" stroke="${col}"/>`;
    g.values.forEach((v, k) => { const jx = ((k * 7919) % 17 - 8) / 8 * bw * .35; svg += `<circle cx="${cx + jx}" cy="${Y(v)}" r="4" fill="${col}" stroke="${css("--card")}" stroke-width="1"><title>${n}: ${v}</title></circle>`; });
    svg += `<text x="${cx}" y="${H - 12}" text-anchor="middle" font-size="11" font-weight="600" fill="${css("--ink2")}">${n}</text><text x="${cx}" y="${H - 1}" text-anchor="middle" font-size="9" fill="${css("--mut")}">n=${g.n} · mean ${fmt(g.mean, 1)}${g.sd != null ? " ± " + fmt(g.sd, 1) : ""}</text>`; });
  box.innerHTML = svg + "</svg>";
  const P = p => `<span class="pval ${p < .05 ? "sig" : "ns"}">${p < .001 ? "p < 0.001" : "p = " + p.toFixed(3)}</span>`;
  let html = `<div class="stat-grid">${names.map(n => { const g = st.groups[n]; return `<div><small>${n}</small><b>${fmt(g.mean, 2)}</b><span class="mut">± ${fmt(g.sd, 2)} SD · median ${fmt(g.median, 2)} · n ${g.n}</span></div>`; }).join("")}</div>`;
  const t = st.tests;
  if (t.welch_t) html += `<p>Welch t-test t = ${t.welch_t.stat}, ${P(t.welch_t.p)} &nbsp;·&nbsp; Mann–Whitney U = ${t.mann_whitney.stat}, ${P(t.mann_whitney.p)} &nbsp;·&nbsp; Cohen's d = ${fmt(t.cohens_d, 2)}</p>`;
  if (t.anova) { html += `<p>One-way ANOVA F = ${t.anova.stat}, ${P(t.anova.p)} &nbsp;·&nbsp; Kruskal–Wallis H = ${t.kruskal.stat}, ${P(t.kruskal.p)}</p><p class="mut">Pairwise Mann–Whitney, Bonferroni: ${Object.entries(t.pairwise_mann_whitney_bonferroni).map(([k, v]) => `${k} ${P(v)}`).join(" · ")}</p>`; }
  html += `<p class="mut" style="margin-top:6px">${st.note}</p>`; tbl.innerHTML = html; renderCor();
}
async function renderCor() {
  const x = $("#cor-x").value, y = $("#cor-y").value; const r = await fetch(`/api/correlate?x=${x}&y=${y}`); const c = await r.json();
  const sc = $("#scatter"), ct = $("#cor-table"); if (c.points.length < 2) { sc.innerHTML = ""; ct.innerHTML = '<span class="mut">Score at least three images.</span>'; return; }
  const W = 520, H = 230, L = 46, B = 30; const xs = c.points.map(p => p[0]), ys = c.points.map(p => p[1]); const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = v => L + (v - x0) / ((x1 - x0) || 1) * (W - L - 12), Y = v => H - B - (v - y0) / ((y1 - y0) || 1) * (H - B - 12);
  let svg = `<svg viewBox="0 0 ${W} ${H}"><line x1="${L}" y1="${H - B}" x2="${W - 12}" y2="${H - B}" stroke="${css("--line2")}"/><line x1="${L}" y1="12" x2="${L}" y2="${H - B}" stroke="${css("--line2")}"/>`;
  if (c.slope !== undefined) svg += `<line x1="${X(x0)}" y1="${Y(c.slope * x0 + c.intercept)}" x2="${X(x1)}" y2="${Y(c.slope * x1 + c.intercept)}" stroke="${css("--acc")}" stroke-width="2" stroke-dasharray="5 4"/>`;
  c.points.forEach(p => svg += `<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="5" fill="${css("--dab")}" stroke="${css("--card")}"><title>${p[2]}: ${p[0]}, ${p[1]}</title></circle>`);
  svg += `<text x="${(L + W) / 2}" y="${H - 6}" text-anchor="middle" font-size="10" fill="${css("--mut")}">${$("#cor-x option:checked").textContent}</text><text x="12" y="${H / 2}" text-anchor="middle" font-size="10" fill="${css("--mut")}" transform="rotate(-90 12 ${H / 2})">${$("#cor-y option:checked").textContent}</text></svg>`;
  sc.innerHTML = svg;
  ct.innerHTML = c.pearson_r !== undefined ? `Pearson r = <b>${c.pearson_r}</b> (p = ${c.pearson_p.toPrecision(2)}) · Spearman ρ = <b>${c.spearman_rho}</b> (p = ${c.spearman_p.toPrecision(2)}) · n = ${c.points.length} · fit y = ${c.slope.toFixed(3)}·x + ${c.intercept.toFixed(2)}` : `n = ${c.points.length} — need three or more images`;
}
$("#stat-metric").onchange = renderStats; $("#cor-x").onchange = renderCor; $("#cor-y").onchange = renderCor;
$$("#stbl th[data-k]").forEach(th => th.onclick = () => { const k = th.dataset.k; state.sort = { k, dir: state.sort.k === k ? -state.sort.dir : 1 }; renderSession(); });
$("#copy-tsv").onclick = async () => { const cols = ["image", "n_cells", "pct_positive", "pct_1plus", "pct_2plus", "pct_3plus", "h_score", "allred_total", "dab_area_fraction_pct", "mean_dab_od_tissue", "second_stain", "thr_weak", "thr_moderate", "thr_strong", "qc_flags"]; const lines = [cols.join("\t"), ...state.order.map(id => cols.map(c => state.results[id].summary[c] ?? "").join("\t"))]; try { await navigator.clipboard.writeText(lines.join("\n")); toast("Copied " + state.order.length + " rows — paste into Excel or Prism"); } catch (e) { toast("Clipboard blocked by the browser; use Download CSV", true); } };

/* ---------- calibrate ---------- */
const roles = {};
function renderCalib() {
  const tb = $("#ctbl tbody"); tb.innerHTML = "";
  if (!state.order.length) { tb.innerHTML = '<tr><td colspan="4" class="mut">Score some images first.</td></tr>'; return; }
  for (const id of state.order) { const j = state.results[id], s = j.summary; const med = j.cells.length ? [...j.cells.map(c => c[3])].sort((a, b) => a - b)[Math.floor(j.cells.length / 2)] : null; const tr = document.createElement("tr");
    tr.innerHTML = `<td>${s.image}</td><td><input class="grp" value="${s.group || ""}" placeholder="group"></td><td class="n">${fmt(s.n_cells, 0)}</td><td class="n">${fmt(med, 3)}</td><td><select data-id="${id}"><option value="">—</option><option value="negative">negative control</option><option value="weak">1+ control</option><option value="moderate">2+ control</option><option value="strong">3+ control</option></select></td>`;
    const sel = $("select", tr); sel.value = roles[id] || ""; sel.onchange = () => roles[id] = sel.value; tb.appendChild(tr); }
}
$("#fit-btn").onclick = async () => {
  const groups = {}; for (const [id, r] of Object.entries(roles)) if (r) (groups[r] = groups[r] || []).push(id);
  if (!Object.keys(groups).length) return toast("Mark at least one control first", true);
  $("#cal-out").innerHTML = '<span class="mut">Fitting…</span>';
  try { const r = await fetch("/api/calibrate", { method: "POST", body: JSON.stringify({ groups }) }); const j = await r.json(); if (!r.ok) throw new Error(j.error); const t = j.thresholds;
    $("#cal-out").innerHTML = `<div class="cuts" style="margin-bottom:12px"><div class="cut b1"><label>0 → 1+</label><b>${t.weak}</b></div><div class="cut b2"><label>1+ → 2+</label><b>${t.moderate}</b></div><div class="cut b3"><label>2+ → 3+</label><b>${t.strong}</b></div></div>
      <div class="tw"><table><thead><tr><th>control</th><th class="n">cells used</th><th>note</th><th class="n">p10</th><th class="n">median</th><th class="n">p90</th></tr></thead><tbody>${j.table.map(r => `<tr><td>${r.category}</td><td class="n">${r.cells_used}</td><td class="mut">${r.note}</td><td class="n">${fmt(r.p10, 3)}</td><td class="n">${fmt(r.median, 3)}</td><td class="n">${fmt(r.p90, 3)}</td></tr>`).join("")}</tbody></table></div>
      <div class="row gap"><button class="btn primary sm" id="use-cal">Use these cut points for new images</button><button class="btn sm" id="apply-all">Re-bin every scored image</button></div>
      <p class="mut" style="margin-top:8px">The negative control anchors the 0/1+ cut (its 99.5th percentile × 1.15); upper cuts sit between adjacent positive-cell populations. Save the profile from the Score tab once you are happy with it.</p>`;
    $("#use-cal").onclick = () => { $("#weak").value = t.weak; $("#moderate").value = t.moderate; $("#strong").value = t.strong; syncTh(); showView("score"); toast("Cut points set for new images"); };
    $("#apply-all").onclick = async () => { let n = 0; for (const id of [...state.order]) { const r2 = await fetch(`/api/rebin?id=${id}&weak=${t.weak}&moderate=${t.moderate}&strong=${t.strong}`, { method: "POST" }); if (r2.ok) { const nj = await r2.json(); nj.truth = state.results[id].truth; add(nj); n++; } } $("#weak").value = t.weak; $("#moderate").value = t.moderate; $("#strong").value = t.strong; syncTh(); toast(`Re-binned ${n} image${n === 1 ? "" : "s"}`); if (state.cur) show(state.cur); };
  } catch (err) { $("#cal-out").innerHTML = `<span style="color:var(--bad)">${err.message}</span>`; }
};

/* ---------- keyboard ---------- */
document.addEventListener("keydown", e => { if (/input|select|textarea/i.test(e.target.tagName)) return; if (e.key === "1") setLayer("original"); if (e.key === "2") setLayer("cells"); if (e.key === "3") setLayer("positivity"); if (e.key.toLowerCase() === "f") { fitView(); drawViewer(); } if (e.key === "Enter" && !$("#apply").disabled) applyTh(); if (e.key === "ArrowLeft" || e.key === "ArrowRight") { const i = state.order.indexOf(state.cur); if (i < 0) return; const nx = state.order[i + (e.key === "ArrowRight" ? 1 : -1)]; if (nx) show(nx); } });
function drawAll() { if (state.cur) { drawViewer(); drawHist(); } }
matchMedia("(prefers-color-scheme: light)").addEventListener("change", drawAll);
})();
