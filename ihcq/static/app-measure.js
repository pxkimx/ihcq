/* IHCq · region morphometry: named traced regions with cut-outs → area, nuclei, ratios
   Classic script, loaded after app-viewer.js. */
"use strict";
const MCOL = ["#0a84ff", "#bf5af2", "#30d158", "#ff9f0a", "#64d2ff", "#ff375f", "#ffd60a", "#ac8e68"];
state.measure = {}; state.mtool = null; state.mmode = "free"; state.mdraw = null; state.space = false; state.mres = {};

function M() { if (!state.cur) return null; return state.measure[state.cur] = state.measure[state.cur] || { regions: [], sel: -1 }; }
function newRegion(name) { const m = M(); if (!m) return toast("Open an image first", true); const i = m.regions.length;
  m.regions.push({ name: name || ["Media", "Adventitia", "Intima", "Lumen"][i] || `Region ${i + 1}`, color: MCOL[i % MCOL.length], include: [], exclude: [] }); m.sel = i; setMTool("add"); renderMRegions(); }
function setMTool(t) { state.mtool = t; state.tool = null; state.pick = null; state.teach = null;
  $$("#m-tool button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.t === t))); viewer.style.cursor = t ? "crosshair" : "grab";
  const m = M(), r = m && m.regions[m.sel]; $("#m-hint").textContent = t && r ? `${t === "add" ? "Tracing" : "Cutting out of"} “${r.name}” — ${state.mmode === "free" ? "drag to trace, release to close" : "click points, double-click to close"} · hold Space to pan · Esc to stop` : "Hold Space to pan while tracing."; }
$("#m-new").onclick = () => newRegion();
$$("#m-mode button").forEach(b => b.onclick = () => { state.mmode = b.dataset.m; $$("#m-mode button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); setMTool(state.mtool); });
$$("#m-tool button").forEach(b => b.onclick = () => { const m = M(); if (!m) return; if (m.sel < 0) newRegion(); setMTool(state.mtool === b.dataset.t ? null : b.dataset.t); });
$("#m-undo").onclick = () => { const m = M(); if (!m || m.sel < 0) return; const r = m.regions[m.sel]; const last = r._hist && r._hist.pop(); if (last) { r[last].pop(); renderMRegions(); measureNow(); drawViewer(); } };
$("#m-del").onclick = () => { const m = M(); if (!m || m.sel < 0) return; m.regions.splice(m.sel, 1); m.regions.forEach((r, i) => r.color = MCOL[i % MCOL.length]); m.sel = m.regions.length - 1; renderMRegions(); measureNow(); drawViewer(); };

function renderMRegions() { const m = M(); const box = $("#m-regions"); box.innerHTML = ""; if (!m) return;
  m.regions.forEach((r, i) => { const res = (state.mres[state.cur] || {}).byName || {}; const g = res[r.name];
    const chip = document.createElement("div"); chip.className = "m-chip"; chip.style.setProperty("--rc", r.color); chip.setAttribute("aria-current", String(i === m.sel));
    chip.innerHTML = `<i></i><input list="m-names" value="${r.name.replace(/"/g, "&quot;")}" aria-label="region name"><small>${g ? fmtArea(g) : r.include.length ? "…" : "not traced"}</small>`;
    chip.onclick = () => { m.sel = i; renderMRegions(); setMTool(state.mtool); drawViewer(); };
    const inp = chip.querySelector("input"); inp.onchange = () => { r.name = inp.value.trim() || `Region ${i + 1}`; measureNow(); }; inp.onclick = e => e.stopPropagation();
    box.appendChild(chip); });
  if (!m.regions.length) box.innerHTML = '<span class="mut">No regions yet — press <b>＋ New region</b>, then trace on the image. Cut out an inner boundary to make a ring (e.g. media = external minus internal elastic lamina).</span>'; }
function fmtArea(g) { if (g.area_mm2 != null) return g.area_mm2 >= 0.01 ? `${g.area_mm2.toFixed(3)} mm²` : `${Math.round(g.area_um2).toLocaleString()} µm²`; return `${Math.round(g.area_px).toLocaleString()} px²`; }

/* drawing */
function drawMeasure(sc) { const m = M(); if (!m) return;
  const path = pts => { ctx.beginPath(); pts.forEach((p, k) => k ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); };
  m.regions.forEach((r, i) => { if (!r.include.length) return;
    ctx.save(); ctx.beginPath(); r.include.forEach(p => { p.forEach((q, k) => k ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.closePath(); });
    r.exclude.forEach(p => { p.slice().reverse().forEach((q, k) => k ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1])); ctx.closePath(); });
    ctx.fillStyle = r.color; ctx.globalAlpha = i === m.sel ? 0.22 : 0.13; ctx.fill("evenodd"); ctx.globalAlpha = 1;
    ctx.lineWidth = (i === m.sel ? 2.5 : 1.6) / sc; ctx.strokeStyle = r.color; r.include.forEach(p => { path(p); ctx.stroke(); });
    ctx.setLineDash([6 / sc, 4 / sc]); r.exclude.forEach(p => { path(p); ctx.stroke(); }); ctx.setLineDash([]); ctx.restore();
    const p0 = r.include[0]; const cx = p0.reduce((a, q) => a + q[0], 0) / p0.length, cy = p0.reduce((a, q) => a + q[1], 0) / p0.length;
    ctx.font = `600 ${12 / sc}px -apple-system, system-ui`; const tw = ctx.measureText(r.name).width; ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(cx - tw / 2 - 5 / sc, cy - 10 / sc, tw + 10 / sc, 18 / sc); ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(r.name, cx, cy + 3 / sc); ctx.textAlign = "left"; });
  if (state.mdraw && state.mdraw.pts.length) { const r = m.regions[m.sel]; ctx.beginPath(); state.mdraw.pts.forEach((p, k) => k ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.lineWidth = 2 / sc; ctx.strokeStyle = r ? r.color : "#fff"; ctx.setLineDash(state.mtool === "cut" ? [6 / sc, 4 / sc] : []); ctx.stroke(); ctx.setLineDash([]); } }
function commitStroke() { const m = M(), d = state.mdraw; state.mdraw = null; if (!m || !d || m.sel < 0) return drawViewer();
  if (d.pts.length < 3) return drawViewer(); const r = m.regions[m.sel]; const key = state.mtool === "cut" ? "exclude" : "include";
  if (key === "exclude" && !r.include.length) { toast("Trace the region before cutting out of it", true); return drawViewer(); }
  r[key].push(d.pts.map(p => [Math.round(p[0] * 10) / 10, Math.round(p[1] * 10) / 10])); (r._hist = r._hist || []).push(key); renderMRegions(); drawViewer(); measureNow(); }
viewer.addEventListener("pointerdown", e => { if (!state.mtool || state.space || state.mmode !== "free" || e.button !== 0 || e.target.closest(".vfloat")) return;
  try { viewer.setPointerCapture(e.pointerId); } catch (_) { /* synthetic or lost pointer — tracing still works */ }
  state.mdraw = { pts: [imgPoint(e)] }; drawViewer(); });
viewer.addEventListener("pointermove", e => { if (!state.mdraw || state.mmode !== "free") return; const p = imgPoint(e), q = state.mdraw.pts[state.mdraw.pts.length - 1];
  if (Math.hypot(p[0] - q[0], p[1] - q[1]) * state.base * state.zoom >= 3) { state.mdraw.pts.push(p); drawViewer(); } });
viewer.addEventListener("pointerup", () => { if (state.mdraw && state.mmode === "free") commitStroke(); });
viewer.addEventListener("click", e => { if (!state.mtool || state.space || state.mmode !== "points" || e.target.closest(".vfloat")) return; const p = imgPoint(e);
  state.mdraw = state.mdraw || { pts: [] }; const q = state.mdraw.pts[state.mdraw.pts.length - 1]; if (!q || Math.hypot(p[0] - q[0], p[1] - q[1]) > 1) state.mdraw.pts.push(p); drawViewer(); });
viewer.addEventListener("dblclick", e => { if (!state.mtool || state.mmode !== "points") return; e.preventDefault(); commitStroke(); });
document.addEventListener("keydown", e => { if (/input|select|textarea/i.test(e.target.tagName)) return; if (e.code === "Space" && state.mtool) { state.space = true; viewer.style.cursor = "grab"; e.preventDefault(); } if (e.key === "Escape" && state.mtool) { state.mdraw = null; setMTool(null); drawViewer(); } });
document.addEventListener("keyup", e => { if (e.code === "Space") { state.space = false; viewer.style.cursor = state.mtool ? "crosshair" : "grab"; } });

/* results */
let mT; function measureNow() { clearTimeout(mT); mT = setTimeout(runMeasure, 120); }
async function runMeasure() { const m = M(); const j = state.results[state.cur]; if (!m || !j) return;
  const regions = m.regions.filter(r => r.include.length).map(r => ({ name: r.name, include: r.include, exclude: r.exclude }));
  if (!regions.length) { $("#m-out").innerHTML = ""; $("#m-csv").hidden = true; renderMRegions(); return; }
  const mpp = +$("#mpp").value || null;
  try { const r = await fetch(`/api/measure?id=${j.id}`, { method: "POST", body: JSON.stringify({ regions, mpp }) }); const d = await r.json(); if (!r.ok) throw new Error(d.error);
    d.byName = Object.fromEntries(d.regions.map(g => [g.name, g])); state.mres[state.cur] = d; renderMRegions(); renderMOut(d); } catch (err) { toast(err.message, true); } }
function renderMOut(d) { const m = M(); const col = n => (m.regions.find(r => r.name === n) || {}).color || "#888"; const unit = d.mpp ? "mm²" : "px²";
  const A = g => d.mpp ? (g.area_mm2 >= 0.01 ? g.area_mm2.toFixed(4) : g.area_mm2.toFixed(5)) : Math.round(g.area_px).toLocaleString();
  const names = d.regions.map(g => g.name); const prev = state.mpair && names.includes(state.mpair[0]) && names.includes(state.mpair[1]) ? state.mpair : [names[1] || names[0], names[0]];
  let h = "";
  if (names.length >= 2) { const [a, b] = prev; const ra = d.ratios.find(x => x.a === a && x.b === b) || {}; const ga = d.byName[a], gb = d.byName[b];
    h += `<div class="m-ratio"><select id="m-a">${names.map(n => `<option ${n === a ? "selected" : ""}>${n}</option>`).join("")}</select><span class="mut">÷</span><select id="m-b">${names.map(n => `<option ${n === b ? "selected" : ""}>${n}</option>`).join("")}</select>
      <span class="big">${ra.area_ratio != null ? ra.area_ratio.toFixed(3) : "—"}</span><span class="mut">area ratio</span>
      <span class="big" style="margin-left:14px">${ra.nuclei_ratio != null ? ra.nuclei_ratio.toFixed(3) : "—"}</span><span class="mut">nuclei ratio</span>
      <div style="flex-basis:100%"><div class="m-bar"><span style="width:${ra.a_pct_of_pair_area || 0}%;background:${col(a)}"></span><span style="width:${100 - (ra.a_pct_of_pair_area || 0)}%;background:${col(b)}"></span></div>
      <span class="mut">${a} ${fmt(ra.a_pct_of_pair_area)}% · ${b} ${fmt(100 - (ra.a_pct_of_pair_area || 0))}% of their combined area · nuclei ${ga.nuclei} vs ${gb.nuclei}</span></div></div>`; }
  h += `<div class="tw"><table><thead><tr><th>region</th><th class="n">area (${unit})</th><th class="n">% of total</th><th class="n">perimeter (${d.mpp ? "µm" : "px"})</th><th class="n">nuclei</th><th class="n">% of nuclei</th><th class="n">nuclei /${d.mpp ? "mm²" : "10⁴px"}</th><th class="n">positive</th><th class="n">% positive</th><th class="n">DAB area %</th><th class="n">tissue %</th></tr></thead><tbody>` +
    d.regions.map(g => `<tr><td class="nm"><span class="bdot" style="background:${col(g.name)}"></span>${g.name}</td><td class="n"><b>${A(g)}</b></td><td class="n">${fmt(g.pct_of_total_area)}</td><td class="n">${fmt(d.mpp ? g.perimeter_um : g.perimeter_px, 0)}</td><td class="n"><b>${g.nuclei}</b></td><td class="n">${fmt(g.pct_of_total_nuclei)}</td><td class="n">${fmt(d.mpp ? g.nuclei_per_mm2 : g.nuclei_per_1e4px, d.mpp ? 0 : 2)}</td><td class="n">${g.nuclei_positive}</td><td class="n">${fmt(g.pct_positive)}${g.pct_positive_ci95 ? ` <span class="mut">(${g.pct_positive_ci95[0]}–${g.pct_positive_ci95[1]})</span>` : ""}</td><td class="n">${fmt(g.dab_area_pct)}</td><td class="n">${fmt(g.tissue_pct, 0)}</td></tr>`).join("") + `</tbody></table></div>`;
  if (names.length >= 3) { h += `<details style="margin-top:8px"><summary class="mut" style="cursor:pointer">All area ratios (row ÷ column)</summary><div class="tw"><table><thead><tr><th></th>${names.map(n => `<th class="n">${n}</th>`).join("")}</tr></thead><tbody>` +
    names.map(a => `<tr><td class="nm">${a}</td>${names.map(b => `<td class="n">${a === b ? "—" : fmt((d.ratios.find(x => x.a === a && x.b === b) || {}).area_ratio, 3)}</td>`).join("")}</tr>`).join("") + `</tbody></table></div></details>`; }
  if (d.overlaps.length) h += `<div class="qc" style="margin-top:8px">${d.overlaps.map(o => `<div>${o.a} and ${o.b} overlap by ${fmt(o.pct_of_smaller)}% of the smaller region — their areas and nuclei are counted in both. Cut one out of the other if they should be separate layers.</div>`).join("")}</div>`;
  if (d.unit_note) h += `<p class="mut" style="margin-top:6px">Areas are in pixels — set the pixel size in Analysis settings to get µm² and mm².</p>`;
  $("#m-out").innerHTML = h; $("#m-csv").href = d.csv; $("#m-csv").download = `${state.results[state.cur].summary.image}_measurements.csv`; $("#m-csv").hidden = false;
  const sa = $("#m-a"), sb = $("#m-b"); if (sa) { const upd = () => { state.mpair = [sa.value, sb.value]; renderMOut(d); }; sa.onchange = upd; sb.onchange = upd; } }
$("#mpp").addEventListener("change", () => { if (M() && M().regions.some(r => r.include.length)) measureNow(); });
/* when an image is shown, restore its regions and results */
const _showM = show; show = async function (id) { await _showM(id); state.mdraw = null; renderMRegions(); const d = state.mres[id]; if (d) renderMOut(d); else { $("#m-out").innerHTML = ""; $("#m-csv").hidden = true; if (M() && M().regions.some(r => r.include.length)) measureNow(); } };
