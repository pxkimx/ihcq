/* IHCq · shared helpers, state, theme, toasts, presets and settings
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const BIN = ["--b0", "--b1", "--b2", "--b3"], BINNAME = ["0", "1+", "2+", "3+"];
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : (typeof v === "number" ? v.toFixed(d) : String(v));
const state = { teach: null, clicks: {}, pick: null, custom: { white: null, hema: null, dab: null }, csort: { c: "dab", dir: -1 }, cfilter: "all", rois: {}, tool: null, drawing: null, heat: null, results: {}, order: [], cur: null, th: { weak: .15, moderate: .40, strong: .80 }, layer: "cells", zoom: 1, pan: { x: 0, y: 0 }, imgs: {}, hover: null, sort: { k: "image", dir: 1 } };

/* ---------- theme ---------- */
/* Light | Dark: the choice is stored as localStorage "theme"; until one is picked IHCq follows the system, as it always has */
const sysTheme = () => matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
const curTheme = () => document.documentElement.dataset.theme || sysTheme();
function syncTheme() { const t = curTheme(); $$("#theme button").forEach(b => { const on = b.dataset.t === t; b.setAttribute("aria-checked", on); b.setAttribute("aria-pressed", on); b.tabIndex = on ? 0 : -1; }); }
function setTheme(t) { document.documentElement.dataset.theme = t; try { localStorage.setItem("theme", t); localStorage.removeItem("ihcq-theme"); } catch (e) {} syncTheme(); if (typeof drawAll === "function") drawAll(); }
$$("#theme button").forEach(b => b.onclick = () => setTheme(b.dataset.t));
$("#theme").addEventListener("keydown", e => { if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); setTheme(curTheme() === "light" ? "dark" : "light"); $(`#theme button[data-t="${curTheme()}"]`).focus(); } });
matchMedia("(prefers-color-scheme: light)").addEventListener("change", syncTheme);
syncTheme();


/* ---------- toast ---------- */
let toastT; function toast(msg, bad = false) { const t = $("#toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, bad ? 6000 : 2600); }

/* ---------- tabs ---------- */
function showView(v) { const el = document.getElementById("sec-" + v); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }
let refreshT; function refreshAll() { clearTimeout(refreshT); refreshT = setTimeout(() => { renderSession(); renderCalib(); }, 80); }

/* ---------- presets & settings ---------- */
const PRESETS = {
  nuclear: { compartment: "nuclear", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: true, ring: 3 },
  membrane: { compartment: "membrane", statistic: "p90", weak: .15, moderate: .40, strong: .80, segment: true, ring: 3 },
  cyto: { compartment: "cell", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: true, ring: 4 },
  her2: { compartment: "membrane", statistic: "p90", weak: .16, moderate: .216, strong: .30, segment: true, ring: 3 },
  pixels: { compartment: "nuclear", statistic: "mean", weak: .15, moderate: .40, strong: .80, segment: false, ring: 3 },
};
$("#preset").onchange = e => { const p = PRESETS[e.target.value]; for (const k of ["compartment", "statistic"]) $("#" + k).value = p[k]; for (const k of ["weak", "moderate", "strong", "ring"]) $("#" + k).value = p[k]; $("#segment").checked = p.segment; syncTh(); };
function settingsQuery(name) { const p = new URLSearchParams(); for (const k of ["compartment", "backend", "statistic", "mpp", "radius", "ring", "weak", "moderate", "strong"]) { const v = $("#" + k).value; if (v !== "") p.set(k, v); } if (!$("#segment").checked) p.set("segment", "0"); if ($("#fit_stains").checked) p.set("fit_stains", "1"); if ($("#tumour_only").checked) p.set("tumour_only", "1"); const C = state.custom; if (C.white) p.set("white", C.white.join(",")); if (C.hema) p.set("hvec", C.hema.join(",")); if (C.dab) p.set("dvec", C.dab.join(",")); if (name) p.set("name", name); return p.toString(); }
function syncTh() { state.th = { weak: +$("#weak").value, moderate: +$("#moderate").value, strong: +$("#strong").value }; if (state.cur) { drawHist(); live(); } }
["weak", "moderate", "strong"].forEach(k => $("#" + k).oninput = syncTh);
$("#save-profile").onclick = () => { const cfg = { compartment: $("#compartment").value, cell_statistic: $("#statistic").value, backend: $("#backend").value, ring_px: +$("#ring").value || 3, mpp: $("#mpp").value ? +$("#mpp").value : null, nucleus_radius_px: $("#radius").value ? +$("#radius").value : null, segment: $("#segment").checked, thresholds: { weak: +$("#weak").value, moderate: +$("#moderate").value, strong: +$("#strong").value }, profile_name: "app-profile",
    white_point: state.custom.white || null, stain_vectors: state.custom.dab || state.custom.hema ? [state.custom.hema || [0.65, 0.704, 0.286], state.custom.dab || [0.268, 0.57, 0.776]] : null }; const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" })); a.download = "ihcq_profile.json"; a.click(); toast("Profile saved — usable with  ihcq score --profile"); };
$("#load-profile").onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const c = JSON.parse(await f.text()); if (c.compartment) $("#compartment").value = c.compartment; if (c.cell_statistic) $("#statistic").value = c.cell_statistic; if (c.backend) $("#backend").value = c.backend; if (c.ring_px) $("#ring").value = c.ring_px; $("#mpp").value = c.mpp ?? ""; $("#radius").value = c.nucleus_radius_px ?? ""; if (c.segment !== undefined) $("#segment").checked = !!c.segment; state.custom = { white: c.white_point || null, hema: c.stain_vectors ? c.stain_vectors[0] : null, dab: c.stain_vectors ? c.stain_vectors[1] : null, hemaRGB: [110, 120, 190], dabRGB: [130, 80, 40] }; renderVecs(); if (c.thresholds) { $("#weak").value = c.thresholds.weak; $("#moderate").value = c.thresholds.moderate; $("#strong").value = c.thresholds.strong; } syncTh(); toast("Profile loaded: " + (c.profile_name || f.name)); } catch (err) { toast("Not a profile: " + err.message, true); } e.target.value = ""; };
