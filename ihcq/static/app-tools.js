/* IHCq · eyedroppers, tumour classifier, projects, apply-to-all, re-analyze, groups, downloads
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
/* ---------- eyedroppers: white point & stain vectors ---------- */
const PICK_HINT = { white: "Click bare glass (no tissue)", hema: "Click the centre of a blue, DAB-negative nucleus", dab: "Click solid brown staining" };
$$("#pickers button").forEach(b => b.onclick = () => { if (!state.cur) return toast("Open an image first", true); state.pick = state.pick === b.dataset.pick ? null : b.dataset.pick; state.tool = null; $$("#roi-tools button").forEach(x => x.setAttribute("aria-pressed", "false")); $$("#pickers button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.pick === state.pick))); const h = $("#picker-hint"); h.hidden = !state.pick; h.textContent = PICK_HINT[state.pick] || ""; viewer.style.cursor = state.pick ? "crosshair" : "grab"; });
function sampleRGB(ix, iy) { const im = state.imgs.original; if (!state.sampler || state.sampler.src !== im.src) { const c = document.createElement("canvas"); c.width = im.width; c.height = im.height; const g = c.getContext("2d", { willReadFrequently: true }); g.drawImage(im, 0, 0); state.sampler = { src: im.src, g }; }
  const r = 4, x0 = Math.max(0, Math.round(ix) - r), y0 = Math.max(0, Math.round(iy) - r); const d = state.sampler.g.getImageData(x0, y0, 2 * r + 1, 2 * r + 1).data; const ch = [[], [], []];
  for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++) ch[k].push(d[i + k]); return ch.map(a => { a.sort((p, q) => p - q); return a[a.length >> 1]; }); }
function odVec(rgb) { const w = state.custom.white || (state.results[state.cur]?.summary.white_point) || [245, 245, 245]; const od = rgb.map((v, k) => Math.max(1e-4, -Math.log10((v + 1) / (w[k] + 1)))); const n = Math.hypot(...od); return od.map(v => +(v / n).toFixed(4)); }
function renderVecs() { const C = state.custom, rows = [];
  const sw = rgb => `<i style="background:rgb(${rgb.join(",")})"></i>`;
  if (C.white) rows.push(`${sw(C.white)}<span>glass ${C.white.join(" / ")}</span>`);
  if (C.hema) rows.push(`${sw(state.custom.hemaRGB)}<span>H ${C.hema.map(v => v.toFixed(3)).join(" ")}</span>`);
  if (C.dab) rows.push(`${sw(state.custom.dabRGB)}<span>DAB ${C.dab.map(v => v.toFixed(3)).join(" ")}</span>`);
  $("#vecs").innerHTML = rows.length ? rows.join("") : '<span class="mut" style="grid-column:1/-1">Using textbook vectors and automatic white point.</span>'; }
function finishPick(ix, iy) { const rgb = sampleRGB(ix, iy), k = state.pick;
  if (k === "white") { if (Math.min(...rgb) < 170) return toast("That looks like tissue, not glass — pick a brighter area", true); state.custom.white = rgb; }
  else { const v = odVec(rgb); if (Math.hypot(...rgb.map((c, i) => c - (state.custom.white || [245, 245, 245])[i])) < 25) return toast("Too pale to estimate a stain vector — pick a darker spot", true); state.custom[k] = v; state.custom[k + "RGB"] = rgb;
    const ref = k === "dab" ? [0.268, 0.57, 0.776] : [0.65, 0.704, 0.286]; const n = Math.hypot(...ref); const ang = Math.acos(Math.min(1, v.reduce((a, x, i) => a + x * ref[i] / n, 0))) * 180 / Math.PI;
    toast(`${k === "dab" ? "DAB" : "Hematoxylin"} vector set — ${ang.toFixed(0)}° from textbook${ang > 25 ? " (large: check you clicked a pure area)" : ""}`); }
  if (k === "white") toast(`White point set to ${rgb.join(" / ")}`);
  state.pick = null; $$("#pickers button").forEach(x => x.setAttribute("aria-pressed", "false")); $("#picker-hint").hidden = true; viewer.style.cursor = "grab"; renderVecs(); markDirty(); }
$("#vec-reset").onclick = () => { state.custom = { white: null, hema: null, dab: null }; renderVecs(); markDirty(); toast("Back to textbook vectors and automatic white point"); };
function markDirty() { if (state.cur) { const b = $("#reanalyze"); b.textContent = "Re-analyze current image with these settings ↻"; } }

/* ---------- teach the tumour/stroma classifier ---------- */
function updateClickCount() { const K = state.clicks[state.cur] || { tumour: [], stroma: [] }; $("#click-count").textContent = `${K.tumour.length} / ${K.stroma.length}`; $("#classify").disabled = K.tumour.length < 3 || K.stroma.length < 3; }
$$("#teach button").forEach(b => b.onclick = () => { if (!state.cur) return; state.teach = state.teach === b.dataset.teach ? null : b.dataset.teach; state.tool = null; state.pick = null;
  $$("#teach button").forEach(x => x.setAttribute("aria-pressed", String(x.dataset.teach === state.teach))); $$("#roi-tools button,#pickers button").forEach(x => x.setAttribute("aria-pressed", "false"));
  const h = $("#picker-hint"); h.hidden = !state.teach; h.textContent = state.teach ? `Click ${state.teach === "tumour" ? "tumour" : "stromal"} nuclei — at least 3 of each, 10+ is better` : ""; viewer.style.cursor = state.teach ? "crosshair" : "grab"; if (state.teach && state.layer !== "tumour") setLayer("tumour"); });
$("#classify").onclick = async () => { const j = state.results[state.cur]; const K = state.clicks[state.cur]; const b = $("#classify"); b.disabled = true;
  try { const r = await fetch(`/api/classify?id=${j.id}`, { method: "POST", body: JSON.stringify({ ...K, tumour_only: true }) }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error);
    nj.truth = j.truth; nj.note = j.note; state.clicks[nj.id] = K; add(nj); $("#tumour_only").checked = true; await show(nj.id); setLayer("tumour");
    const c = nj.classifier; toast(`Classifier trained on ${c.clicks_matched[0]} + ${c.clicks_matched[1]} clicks · leave-one-out accuracy ${Math.round(c.loo_accuracy * 100)}% · ${Math.round(c.tumour_fraction * 100)}% of nuclei tumour-like${c.loo_accuracy < 0.8 ? " — add more clicks" : ""}`, c.loo_accuracy < 0.7); }
  catch (err) { toast(err.message, true); } finally { updateClickCount(); } };
$("#tumour_only").addEventListener("change", async e => { const j = state.results[state.cur]; if (!j) return;
  try { const r = await fetch(`/api/tumour_only?id=${j.id}&on=${e.target.checked ? 1 : 0}`, { method: "POST" }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = j.truth; nj.note = j.note; add(nj); await show(nj.id);
    toast(e.target.checked ? (nj.summary.scored_population === "tumour-like cells" ? "Scoring tumour-like cells only" : "Tumour and stroma did not separate automatically — teach the classifier with a few clicks") : "Scoring all cells"); } catch (err) { toast(err.message, true); } });

/* ---------- projects ---------- */
$("#proj-save").addEventListener("click", e => { if (!state.order.length) { e.preventDefault(); toast("Score an image first — there is nothing to save", true); } else toast("Saving project — originals, settings, regions and groups"); });
$("#proj-open").onchange = async e => { const f = e.target.files[0]; e.target.value = ""; if (!f) return; toast(`Opening ${f.name} — re-analyzing every image…`);
  try { const r = await fetch("/api/project/open", { method: "POST", body: f }); const d = await r.json(); if (!r.ok) throw new Error(d.error);
    for (const j of d.results) { add(j); if (j.summary.roi_polygons) state.rois[j.id] = j.summary.roi_polygons;
      if (j.measure_regions) { state.measure[j.id] = { regions: j.measure_regions.map((r, i) => ({ ...r, color: MCOL[i % MCOL.length] })), sel: 0 }; if (j.measure) state.mres[j.id] = { ...j.measure, byName: Object.fromEntries(j.measure.regions.map(g => [g.name, g])) }; } }
    if (d.results.length) show(d.results[d.results.length - 1].id);
    toast(`Opened ${d.results.length} image${d.results.length === 1 ? "" : "s"} (saved ${d.saved})${d.mismatches.length ? ` · results differ for ${d.mismatches.length} — software changed since saving` : " · results reproduced exactly"}`, d.mismatches.length > 0); }
  catch (err) { toast("Could not open project: " + err.message, true); } };

/* ---------- apply to all ---------- */
$("#apply-all").onclick = async () => { const ids = [...state.order]; if (!ids.length) return; const b = $("#apply-all"); b.disabled = true; let ok = 0, gone = 0;
  for (let i = 0; i < ids.length; i++) { b.textContent = `Re-analyzing ${i + 1} of ${ids.length}…`; const old = state.results[ids[i]];
    try { const r = await fetch(`/api/reanalyze?id=${ids[i]}&` + settingsQuery(), { method: "POST" }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = old.truth; nj.note = old.note; add(nj); ok++; } catch (e) { gone++; } }
  b.textContent = "Apply settings to all images"; b.disabled = false; if (state.cur) show(state.cur);
  toast(`Re-analyzed ${ok} image${ok === 1 ? "" : "s"}${gone ? ` · ${gone} no longer in memory — drop them again` : ""}`, gone > 0); };

/* ---------- re-analyze / group / downloads ---------- */
$("#reanalyze").onclick = async () => { const j = state.results[state.cur]; if (!j) return; const b = $("#reanalyze"); b.disabled = true; b.textContent = "Re-analyzing…";
  try { const r = await fetch(`/api/reanalyze?id=${j.id}&` + settingsQuery(), { method: "POST" }); const nj = await r.json(); if (!r.ok) throw new Error(nj.error); nj.truth = j.truth; nj.note = j.note; add(nj); await show(nj.id); toast("Re-analyzed with the current settings"); }
  catch (err) { toast(err.message, true); } finally { b.textContent = "Re-analyze current image with these settings"; b.disabled = !state.cur; } };
["compartment", "backend", "statistic", "mpp", "radius", "ring", "segment", "fit_stains"].forEach(k => $("#" + k).addEventListener("change", () => { if (state.cur) { const b = $("#reanalyze"); b.classList.add("primary"); b.textContent = "Re-analyze current image with these settings ↻"; } }));
async function setGroup(id, g) { const j = state.results[id]; if (!j) return; j.summary.group = g; await fetch("/api/group", { method: "POST", body: JSON.stringify({ id, group: g }) }); }
$("#group").addEventListener("change", e => { if (state.cur) { setGroup(state.cur, e.target.value.trim()); toast(e.target.value.trim() ? `Grouped as “${e.target.value.trim()}”` : "Group cleared"); } });
const dlm = $("#dl-menu"); $("#dl-btn").onclick = e => { e.stopPropagation(); dlm.hidden = !dlm.hidden; }; document.addEventListener("click", () => dlm.hidden = true);
