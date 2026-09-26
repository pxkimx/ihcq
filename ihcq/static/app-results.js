/* IHCq · rendering one result: tiles, metrics strip, QC flags
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
/* ---------- results ---------- */
function add(j) { if (!state.results[j.id]) state.order.push(j.id); state.results[j.id] = j; $("#tab-count").textContent = state.order.length; $("#tab-count").hidden = false; refreshAll(); }
async function show(id) {
  const j = state.results[id]; if (!j) return; state.cur = id; const s = j.summary;
  $$("#queue li").forEach(li => li.setAttribute("aria-current", String(li.dataset.id === id)));
  $("#empty").hidden = true; $("#result").hidden = false;
  $("#r-name").textContent = `${s.image} · ${s.width}×${s.height} · ${s.compartment} · ${s.seconds}s`;
  const st = $("#r-stain"); const kind = s.second_stain; st.className = "stain " + (kind === "dab" ? "" : kind === "eosin" ? "bad" : "unk");
  st.innerHTML = `<i></i>${kind === "dab" ? "Second stain is <b>DAB</b> — chromogenic IHC" : kind === "eosin" ? "Second stain is <b>eosin</b> — this is H&amp;E; DAB scores are not valid" : "Second stain <b>unrecognised</b> — check the stain separation"} <span class="mut">${s.second_stain_angle_to_dab}° from DAB · ${s.second_stain_angle_to_eosin}° from eosin</span>`;
  if (s.roi_polygons) state.rois[id] = { include: s.roi_polygons.include || [], exclude: s.roi_polygons.exclude || [] };
  state.th = { ...j.thresholds }; $("#weak").value = state.th.weak; $("#moderate").value = state.th.moderate; $("#strong").value = state.th.strong;
  renderTiles(s); renderQC(j.qc);
  $("#st-orig").src = j.original; $("#st-hema").src = j.overlays.hematoxylin; $("#st-dab").src = j.overlays.dab;
  $("#dl-st-orig").href = j.original; $("#dl-st-orig").download = s.image + "_original.png";
  $("#dl-st-hema").href = j.overlays.hematoxylin; $("#dl-st-hema").download = s.image + "_hematoxylin.png";
  $("#dl-st-dab").href = j.overlays.dab; $("#dl-st-dab").download = s.image + "_dab.png";

  $("#dl-cells").href = j.cells_csv || "#"; $("#dl-cells").style.visibility = j.cells_csv ? "visible" : "hidden";
  $("#truth").textContent = j.truth ? `Synthetic field — truth: H = ${j.truth.h_score}, ${j.truth.pct_positive}% positive, ${j.truth.n_cells} nuclei.` : (j.note || "");
  $("#regions").hidden = true; updateClickCount();
  $("#group").value = s.group || ""; $("#reanalyze").disabled = false; $("#apply-all").disabled = false;
  $("#dl-orig").href = j.original; $("#dl-orig").download = s.image + "_original.png";
  $("#dl-cells-img").href = j.overlays.cells || "#"; $("#dl-cells-img").download = s.image + "_labelled_nuclei.png";
  $("#dl-pos").href = j.overlays.positivity; $("#dl-pos").download = s.image + "_positivity.png";
  $("#dl-stains").href = j.overlays.stains; $("#dl-stains").download = s.image + "_stain_separation.png";
  await loadImages(j); state.zoom = 1; state.pan = { x: 0, y: 0 }; fitView(); drawViewer(); drawHist(); live(); renderCells();
}
function tile(v, label, sub, color) { return `<div class="tile" style="--tc:${color}"><b>${v}</b><small>${label}</small>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`; }
function renderTiles(s) {
  const seg = s.n_cells !== undefined && s.n_cells !== null;
  const hcol = `var(${BIN[Math.min(3, Math.floor((s.h_score || 0) / 100) + 1)]})`;
  $("#tiles").innerHTML =
    (s.her2_score ? tile(s.her2_score, "HER2 (ASCO/CAP)", `${(s.her2_category || "").split(" (")[0].split(" ·")[0]} · complete ${fmt(s.pct_complete_any)}% · strong ${fmt(s.pct_complete_strong)}%`, `var(${BIN[{ "0": 0, "1+": 1, "2+": 2, "3+": 3 }[s.her2_score] || 0]})`) : "") +
    (seg ? tile(fmt(s.h_score, 0), "H-score", "0 – 300", hcol) : "") +
    (seg ? tile(fmt(s.pct_positive) + "%", "positive cells", s.pct_positive_ci95 ? `95% CI ${s.pct_positive_ci95[0]}–${s.pct_positive_ci95[1]} · n ${s.n_cells}` : `${s.n_cells} nuclei`, "var(--b2)") : "") +
    (seg ? tile(fmt(s.pct_3plus) + "%", "3+ cells", `2+ ${fmt(s.pct_2plus)}% · 1+ ${fmt(s.pct_1plus)}%`, "var(--b3)") : "") +
    (seg ? tile(fmt(s.allred_total, 0), "Allred", `PS ${fmt(s.allred_ps, 0)} + IS ${fmt(s.allred_is, 0)}`, "var(--b1)") : "") +
    (seg ? tile(fmt(s.irs, 0), "IRS", `PS ${fmt(s.irs_ps, 0)} × IS ${fmt(s.irs_is, 0)} · 0–12`, "var(--acc)") : "") +
    (seg && s.hotspot_pct_positive != null ? tile(fmt(s.hotspot_pct_positive) + "%", "hotspot", `${s.hotspot_window}-cell window · cold ${fmt(s.coldspot_pct_positive)}%`, "var(--b3)") : "") +
    tile(fmt(s.dab_area_fraction_pct) + "%", "DAB area", `profiler: ${s.profiler_zone || "—"}`, "var(--dab)") +
    tile(fmt(s.mean_dab_od_tissue, 3), "mean DAB OD", `p95 ${fmt(s.p95_dab_od_tissue, 2)}`, "var(--acc)") +
    (seg ? tile(fmt(s.cells_per_mm2 ?? s.cells_per_tissue_px1e4, s.cells_per_mm2 ? 0 : 2), s.cells_per_mm2 ? "nuclei / mm²" : "nuclei / 10⁴ px", `median r ${fmt(s.median_nucleus_radius_px)} px`, "var(--b0)") : "");
  const kv = [];
  kv.push(`tissue <b>${fmt(s.tissue_fraction * 100, 0)}%</b> of field`); kv.push(`white point <b>${s.white_point_source}</b> ${(s.white_point || []).map(v => Math.round(v)).join("/")}`);
  if (seg) { kv.push(`mean nucleus area <b>${fmt(s.mean_nucleus_area_px, 0)} px</b>`); kv.push(`nuclear area <b>${fmt(s.nuclear_area_fraction_pct)}%</b> of tissue`); kv.push(`nucleus radius <b>${fmt(s.median_nucleus_radius_px)} px</b> (assumed ${s.assumed_nucleus_radius_px})`); kv.push(`DAB inside nuclei <b>${fmt((s.dab_in_nuclei_fraction || 0) * 100, 0)}%</b>`); }
  kv.push(`pixel H <b>${fmt(s.pixel_h_score, 0)}</b>`); kv.push(`integrated DAB OD <b>${fmt(s.integrated_dab_od, 0)}</b>`);
  if (s.stain_vectors_used) kv.push(`DAB vector <b>${s.stain_vectors_used[1].map(v => v.toFixed(2)).join(" ")}</b>`);
  if (s.roi_fraction != null) kv.push(`ROI <b>${fmt(s.roi_fraction * 100, 0)}%</b> of tissue`);
  if (s.scored_population) kv.push(`scored <b>${s.scored_population}</b>${s.tumour_classifier === "clicks" ? ` (taught · click accuracy ${fmt((s.tumour_classifier_accuracy || 0) * 100, 0)}%)` : ""}`);
  if (s.tumour_like_fraction != null) kv.push(`tumour-like <b>${fmt(s.tumour_like_fraction * 100, 0)}%</b> of nuclei`);
  if (s.hema_crosstalk_k) kv.push(`DAB→hema leak corrected <b>${s.hema_crosstalk_k}</b>`);
  $("#kvs").innerHTML = kv.map(x => `<span>${x}</span>`).join("");
}
function renderQC(flags) { $("#qc").innerHTML = (flags || []).map(f => `<div class="${/NOT meaningful|not valid/i.test(f) ? "bad" : ""}">${f}</div>`).join(""); }
