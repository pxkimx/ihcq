/* IHCq · session table and charts, statistics, correlation, calibration, keyboard
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
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
  } catch (err) { $("#cal-out").innerHTML = `<span style="color:var(--badt)">${err.message}</span>`; }
};

/* ---------- keyboard ---------- */
document.addEventListener("keydown", e => { if (/input|select|textarea/i.test(e.target.tagName)) return; if (e.key === "1") setLayer("original"); if (e.key === "2") setLayer("cells"); if (e.key === "3") setLayer("positivity"); if (e.key.toLowerCase() === "f") { fitView(); drawViewer(); } if (e.key === "Enter" && !$("#apply").disabled) applyTh(); if (e.key === "ArrowLeft" || e.key === "ArrowRight") { const i = state.order.indexOf(state.cur); if (i < 0) return; const nx = state.order[i + (e.key === "ArrowRight" ? 1 : -1)]; if (nx) show(nx); } });
/* on a theme change: canvases and the SVG charts bake their colours in when drawn, so redraw them all */
function drawAll() { if (state.cur) { drawViewer(); drawHist(); } if (state.order.length) refreshAll(); }
matchMedia("(prefers-color-scheme: light)").addEventListener("change", drawAll);
