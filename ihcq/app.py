"""Local desktop UI: `ihcq app` (or double-click IHCQ.app).

A small HTTP server on 127.0.0.1 serving one page.  Nothing leaves the
machine and nothing is installed beyond ihcq itself.

API (all JSON, all local):
  POST /api/score?name=&<options>   image bytes in body → result
  GET  /api/demo?<options>          synthetic field with known truth → result
  POST /api/rebin?id=&weak=&moderate=&strong=   re-bin a cached result
  POST /api/calibrate               {"groups": {"negative": [ids], ...}} → cut points
  GET  /api/session                 every result of this session
  GET  /out/<file>                  overlays, originals, CSVs
  POST /api/quit
"""
from __future__ import annotations

import io as _io
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from .config import Config, Thresholds

HOST, PORT = "127.0.0.1", 8765
OUT = Path(tempfile.mkdtemp(prefix="ihcq_"))
STATIC = Path(__file__).parent / "static"
SESSION = {"rows": [], "cache": OrderedDict(), "assets": {}, "groups": {}, "lock": threading.Lock(), "server": None, "seq": 0}
CACHE_MAX = 12


def _cfg_from_query(q: dict) -> Config:
    cfg = Config()
    g = lambda k, d=None: (q.get(k, [d]) or [d])[0]
    if g("compartment"): cfg.compartment = g("compartment")
    if g("backend"): cfg.backend = g("backend")
    if g("statistic"): cfg.cell_statistic = g("statistic")
    if g("segment_on"): cfg.segment_on = g("segment_on")
    if g("mpp"): cfg.mpp = float(g("mpp"))
    if g("radius"): cfg.nucleus_radius_px = int(float(g("radius")))
    if g("ring"): cfg.ring_px = int(float(g("ring")))
    for k in ("weak", "moderate", "strong"):
        if g(k): setattr(cfg.thresholds, k, float(g(k)))
    if any(g(k) for k in ("weak", "moderate", "strong")):
        cfg.profile_name = g("profile_name") or "app"
    if g("white"):
        cfg.white_point = [float(v) for v in g("white").split(",")]
    if g("segment") == "0": cfg.segment = False
    if g("fit_stains") == "1": cfg.fit_stains = True
    if g("tumour_only") == "1": cfg.tumour_only = True
    if g("dvec"):
        from .stains import STAIN_VECTORS
        dv = [float(v) for v in g("dvec").split(",")]
        hv = [float(v) for v in g("hvec").split(",")] if g("hvec") else list(STAIN_VECTORS["hematoxylin"])
        cfg.stain_vectors = [hv, dv]
    elif g("hvec"):
        from .stains import STAIN_VECTORS
        cfg.stain_vectors = [[float(v) for v in g("hvec").split(",")], list(STAIN_VECTORS["dab"])]
    return cfg.validate()


def _safe(stem: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)[:60] or "image"


def _payload(rid: str, entry: dict, paths: dict) -> dict:
    res = entry["res"]
    cells = res.cells
    cols = ["x", "y", "area_px", "dab_od", "hema_od", "bin"]
    cell_list = cells[cols].round(3).values.tolist() if len(cells) else []
    if len(cells):
        tl = cells["tumour_like"].astype(int).tolist() if "tumour_like" in cells else [-1] * len(cells)
        mc = cells["membrane_class"].astype(int).tolist() if "membrane_class" in cells else [-1] * len(cells)
        cp = cells["completeness"].round(2).tolist() if "completeness" in cells else [None] * len(cells)
        cell_list = [row + [a, b, c] for row, a, b, c in zip(cell_list, tl, mc, cp)]
    return {"id": rid, "summary": {"image": entry["name"], "group": SESSION["groups"].get(rid, ""), **res.summary}, "qc": res.qc,
            "overlays": {k: f"/out/{v.name}" for k, v in paths.items()}, "original": f"/out/{entry['orig'].name}",
            "cells": cell_list, "thresholds": {"weak": res.config.thresholds.weak, "moderate": res.config.thresholds.moderate, "strong": res.config.thresholds.strong},
            "cells_csv": f"/out/{entry['cells_csv'].name}" if entry.get("cells_csv") else None,
            "results_csv": "/out/session_results.csv", "n_session": len(SESSION["rows"])}


def _record(rid: str, entry: dict, paths: dict | None = None):
    row = {"id": rid, "image": entry["name"], "group": SESSION["groups"].get(rid, ""), **entry["res"].summary}
    if paths is not None:
        SESSION["assets"][rid] = {"images": {"original": str(entry["orig"]), **{k: str(v) for k, v in paths.items()}},
                                  "cells_csv": str(entry["cells_csv"]) if entry.get("cells_csv") else None}
    SESSION["assets"].setdefault(rid, {})["summary"] = row; SESSION["assets"][rid]["qc"] = entry["res"].qc
    # replaying a result exactly needs the settings it was SEGMENTED with (base) and
    # the cut points it is currently BINNED with — segmentation uses the weak cut
    SESSION["assets"][rid]["config"] = (entry["base"]["config"] if "base" in entry else entry["res"].config).to_dict()
    SESSION["assets"][rid]["thresholds"] = vars(entry["res"].config.thresholds).copy()
    SESSION["assets"][rid]["roi"] = entry.get("roi", {"include": [], "exclude": []})
    SESSION["assets"][rid]["clicks"] = entry.get("clicks"); SESSION["assets"][rid]["tumour_only"] = entry.get("tumour_only")
    with SESSION["lock"]:
        SESSION["rows"] = [r for r in SESSION["rows"] if r["id"] != rid] + [row]
        pd.DataFrame(SESSION["rows"]).drop(columns=["id"]).to_csv(OUT / "session_results.csv", index=False)


def _score(rgb: np.ndarray, cfg: Config, stem: str) -> dict:
    from .pipeline import analyze, write_overlays
    res = analyze(rgb, cfg)
    SESSION["seq"] += 1
    rid = f"r{SESSION['seq']}"
    stamp = f"{_safe(stem)}_{rid}"
    paths = write_overlays(rgb, res, OUT, stamp)
    orig = OUT / f"{stamp}_original.png"; Image.fromarray(rgb).save(orig)
    entry = {"id": rid, "name": _safe(stem), "rgb": rgb, "res": res, "orig": orig, "stamp": stamp}
    _snapshot(entry)
    if len(res.cells):
        entry["cells_csv"] = OUT / f"{stamp}_cells.csv"; res.cells.to_csv(entry["cells_csv"], index=False)
    with SESSION["lock"]:
        SESSION["cache"][rid] = entry
        while len(SESSION["cache"]) > CACHE_MAX:
            SESSION["cache"].popitem(last=False)
    _record(rid, entry, paths)
    return _payload(rid, entry, paths)


def _snapshot(entry: dict):
    """Freeze the full-field result.  Every ROI and every re-bin is derived
    from this, never from a previously derived state."""
    r = entry["res"]
    entry["base"] = {"labels": r.labels.copy(), "score_labels": r.score_labels.copy(), "tissue": r.tissue.copy(),
                     "summary": dict(r.summary), "config": Config.from_dict(r.config.to_dict())}
    entry.setdefault("roi", {"include": [], "exclude": []})


def _derive(entry: dict, th: Thresholds | None = None, roi: dict | None = None) -> dict:
    from scipy import ndimage as ndi
    from .metrics import per_cell_table, cell_summary, pixel_summary
    from .pipeline import write_overlays, _qc_flags
    res, base = entry["res"], entry["base"]
    cfg = Config.from_dict(base["config"].to_dict())
    if th is not None:
        cfg.thresholds = th; cfg.profile_name = "app-adjusted"
    elif res.config.profile_name == "app-adjusted":
        cfg.thresholds = res.config.thresholds; cfg.profile_name = "app-adjusted"
    if roi is not None:
        entry["roi"] = {"include": roi.get("include") or [], "exclude": roi.get("exclude") or []}
    roi = entry["roi"]
    active = bool(roi["include"] or roi["exclude"])
    shape = base["tissue"].shape
    mask = _polys_mask(shape, roi["include"]) if roi["include"] else np.ones(shape, bool)
    if roi["exclude"]:
        mask &= ~_polys_mask(shape, roi["exclude"])
    tissue = base["tissue"] & mask
    labels, score_labels = base["labels"], base["score_labels"]
    n = int(labels.max())
    ids = np.arange(1, n + 1)
    if active and n:
        cy, cx = np.array(ndi.center_of_mass(labels > 0, labels, np.arange(1, n + 1))).T
        keep = mask[np.clip(np.round(cy).astype(int), 0, shape[0] - 1), np.clip(np.round(cx).astype(int), 0, shape[1] - 1)]
        lut = np.zeros(n + 1, np.int32)
        lut[1:][keep] = np.arange(1, int(keep.sum()) + 1)      # one map for nuclei AND their rings
        labels, score_labels = lut[labels], lut[score_labels]
        ids = np.nonzero(keep)[0] + 1
    dab, hema = res.conc[..., 1], res.conc[..., 0]
    s = dict(base["summary"])
    s.update(pixel_summary(dab, hema, tissue, cfg.thresholds, cfg.pixel_positive_od, cfg.mpp))
    cells = pd.DataFrame()
    if "tumour_only" in entry:
        cfg.tumour_only = entry["tumour_only"]
    if cfg.segment:
        from .pipeline import enrich_cells, score_cells
        cells = per_cell_table(labels, score_labels, dab, hema, cfg.thresholds, cfg.cell_statistic, cfg.mpp)
        cells = enrich_cells(cells, res.extra, ids, cfg)
        s.update(score_cells(cells, int(tissue.sum()), cfg, res.extra))
        ti = res.extra.get("tumour_info", {})
        s["tumour_classifier"] = ti.get("source", "automatic")
        if ti.get("loo_accuracy") is not None: s["tumour_classifier_accuracy"] = ti["loo_accuracy"]
    s.update({"thr_weak": cfg.thresholds.weak, "thr_moderate": cfg.thresholds.moderate, "thr_strong": cfg.thresholds.strong, "profile": cfg.profile_name,
              "roi_fraction": round(float(tissue.sum() / max(base["tissue"].sum(), 1)), 4) if active else None,
              "roi_polygons": roi if active else None})
    res.summary, res.cells, res.labels, res.score_labels, res.tissue, res.config = s, cells, labels, score_labels, tissue, cfg
    res.qc = _qc_flags(s, cfg)
    if active: res.qc.insert(0, f"scored inside a drawn region — {s['roi_fraction'] * 100:.0f}% of the tissue, {len(cells)} nuclei")
    s["qc_flags"] = " | ".join(res.qc)
    paths = write_overlays(entry["rgb"], res, OUT, entry["stamp"] + f"_d{int(time.time() * 1000) % 1000000}")
    if len(cells):
        entry["cells_csv"] = OUT / f"{entry['stamp']}_cells.csv"; cells.to_csv(entry["cells_csv"], index=False)
    else:
        entry.pop("cells_csv", None)
    _record(entry["id"], entry, paths)
    return _payload(entry["id"], entry, paths)


def _regions(rid: str, polys: list) -> dict:
    """Score every include polygon on its own (no merging), from the full-field snapshot."""
    from scipy import ndimage as ndi
    from .metrics import per_cell_table, cell_summary, pixel_summary
    entry = _cached(rid); res, base = entry["res"], entry["base"]
    cfg = res.config
    shape = base["tissue"].shape
    labels, score_labels = base["labels"], base["score_labels"]
    dab, hema = res.conc[..., 1], res.conc[..., 0]
    n = int(labels.max())
    from .pipeline import enrich_cells, score_cells
    cells_all = per_cell_table(labels, score_labels, dab, hema, cfg.thresholds, cfg.cell_statistic, cfg.mpp) if cfg.segment and n else pd.DataFrame()
    if len(cells_all): cells_all = enrich_cells(cells_all, res.extra, np.arange(1, n + 1), cfg)
    cfg = Config.from_dict(cfg.to_dict()); cfg.tumour_only = entry.get("tumour_only", cfg.tumour_only)
    out = []
    for i, poly in enumerate(polys or [], 1):
        m = _polys_mask(shape, [poly]); t = base["tissue"] & m
        row = {"region": i, "tissue_px": int(t.sum())}
        px = pixel_summary(dab, hema, t, cfg.thresholds, cfg.pixel_positive_od, cfg.mpp)
        row.update({k: px.get(k) for k in ("dab_area_fraction_pct", "mean_dab_od_tissue", "tissue_area_mm2")})
        if len(cells_all):
            yi = cells_all["y"].round().astype(int).clip(0, shape[0] - 1).to_numpy(); xi = cells_all["x"].round().astype(int).clip(0, shape[1] - 1).to_numpy()
            c = cells_all[m[yi, xi]]
            cs = score_cells(c.reset_index(drop=True), int(t.sum()), cfg, res.extra)
            row.update({k: cs.get(k) for k in ("n_cells", "pct_positive", "pct_positive_ci95", "h_score", "allred_total", "irs", "pct_3plus", "cells_per_mm2", "positive_cells_per_mm2", "cells_per_tissue_px1e4", "her2_score", "pct_complete_any", "scored_population")})
        out.append(row)
    # two-region comparison of positivity: Fisher exact on positive/negative counts
    test = None
    if len(out) == 2 and all(r.get("n_cells") for r in out):
        from scipy.stats import fisher_exact
        a = [round(out[k]["pct_positive"] / 100 * out[k]["n_cells"]) for k in (0, 1)]
        tab = [[a[0], out[0]["n_cells"] - a[0]], [a[1], out[1]["n_cells"] - a[1]]]
        test = {"test": "Fisher exact, positive vs negative cells", "p": float(fisher_exact(tab)[1])}
    return {"regions": out, "test": test}


def _classify(rid: str, tumour_pts: list, stroma_pts: list, tumour_only: bool = True) -> dict:
    """Per-image tumour/stroma classifier trained on clicked nuclei (QuPath-style object classifier)."""
    from scipy import ndimage as ndi
    from .tumour import rich_features, fit_clicks
    entry = _cached(rid); res, base = entry["res"], entry["base"]
    labels = base["labels"]; n = int(labels.max())
    if n < 10:
        raise ValueError("too few nuclei in this image to classify")
    if "features" not in base:
        base["features"] = rich_features(labels, res.conc[..., 0], base["tissue"])
    cy, cx = np.array(ndi.center_of_mass(labels > 0, labels, np.arange(1, n + 1))).T
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([cx, cy]))
    rad = max(8.0, 3 * float(np.sqrt(np.median(np.bincount(labels.ravel())[1:]) / np.pi)))
    def nearest(pts):
        idx = []
        for x, y in pts:
            d, i = tree.query([float(x), float(y)])
            if d <= rad and i not in idx: idx.append(int(i))
        return idx
    ti, si = nearest(tumour_pts), nearest(stroma_pts)
    p, info = fit_clicks(base["features"], ti, si)
    res.extra["tumour_p"], res.extra["tumour_info"] = p, info
    entry["tumour_only"] = bool(tumour_only)
    entry["clicks"] = {"tumour": tumour_pts, "stroma": stroma_pts}
    out = _derive(entry)
    out["classifier"] = {**info, "clicks_matched": [len(ti), len(si)], "clicks_given": [len(tumour_pts), len(stroma_pts)]}
    return out


def _cached(rid: str) -> dict:
    entry = SESSION["cache"].get(rid)
    if entry is None:
        raise KeyError("that image is no longer in memory (only the last 12 are kept) — drop it again")
    return entry


def _rebin(rid: str, th: Thresholds) -> dict:
    return _derive(_cached(rid), th=th)


def _roi(rid: str, include: list, exclude: list) -> dict:
    return _derive(_cached(rid), roi={"include": include, "exclude": exclude})


def _reanalyze(rid: str, cfg: Config) -> dict:
    from .pipeline import analyze
    entry = _cached(rid)
    entry["res"] = analyze(entry["rgb"], cfg)
    _snapshot(entry)
    return _derive(entry)          # re-applies any ROI the user drew


def _stats(metric: str) -> dict:
    from scipy import stats as st
    rows = [r for r in SESSION["rows"] if r.get("group")]
    groups = {}
    for r in rows:
        v = r.get(metric)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            groups.setdefault(r["group"], []).append(float(v))
    out = {"metric": metric, "groups": {}, "tests": {}, "note": ""}
    for g, v in groups.items():
        a = np.asarray(v)
        out["groups"][g] = {"n": int(a.size), "mean": round(float(a.mean()), 3), "sd": round(float(a.std(ddof=1)), 3) if a.size > 1 else None,
                            "median": round(float(np.median(a)), 3), "q1": round(float(np.percentile(a, 25)), 3), "q3": round(float(np.percentile(a, 75)), 3),
                            "min": round(float(a.min()), 3), "max": round(float(a.max()), 3), "values": [round(x, 3) for x in a.tolist()]}
    arrs = [np.asarray(v) for v in groups.values() if len(v) >= 2]
    if len(groups) == 2 and len(arrs) == 2:
        t = st.ttest_ind(*arrs, equal_var=False); u = st.mannwhitneyu(*arrs, alternative="two-sided")
        d = (arrs[0].mean() - arrs[1].mean()) / np.sqrt((arrs[0].var(ddof=1) + arrs[1].var(ddof=1)) / 2) if all(a.size > 1 for a in arrs) else float("nan")
        out["tests"] = {"welch_t": {"stat": round(float(t.statistic), 3), "p": float(t.pvalue)}, "mann_whitney": {"stat": float(u.statistic), "p": float(u.pvalue)}, "cohens_d": round(float(d), 3) if d == d else None}
        out["note"] = "Two groups: Welch t-test (unequal variances) and Mann–Whitney U (rank-based, no normality assumption). Cohen's d is the standardised mean difference."
    elif len(groups) > 2 and len(arrs) >= 2:
        f = st.f_oneway(*arrs); k = st.kruskal(*arrs)
        out["tests"] = {"anova": {"stat": round(float(f.statistic), 3), "p": float(f.pvalue)}, "kruskal": {"stat": round(float(k.statistic), 3), "p": float(k.pvalue)}}
        pair = {}
        names = [g for g, v in groups.items() if len(v) >= 2]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pair[f"{names[i]} vs {names[j]}"] = float(st.mannwhitneyu(groups[names[i]], groups[names[j]], alternative="two-sided").pvalue)
        m = len(pair) or 1
        out["tests"]["pairwise_mann_whitney_bonferroni"] = {k_: min(1.0, v * m) for k_, v in pair.items()}
        out["note"] = "More than two groups: one-way ANOVA and Kruskal–Wallis, then pairwise Mann–Whitney with Bonferroni correction."
    else:
        out["note"] = "Assign at least two images to each of two groups to test."
    return out


def _correlate(x: str, y: str) -> dict:
    from scipy import stats as st
    pts = [(r.get(x), r.get(y), r["image"]) for r in SESSION["rows"]]
    pts = [(float(a), float(b), n) for a, b, n in pts if a is not None and b is not None and a == a and b == b]
    out = {"x": x, "y": y, "points": pts}
    if len(pts) >= 3:
        a = np.array([p[0] for p in pts]); b = np.array([p[1] for p in pts])
        pr = st.pearsonr(a, b); sp = st.spearmanr(a, b); slope, inter = np.polyfit(a, b, 1)
        out.update({"pearson_r": round(float(pr[0]), 3), "pearson_p": float(pr[1]), "spearman_rho": round(float(sp[0]), 3), "spearman_p": float(sp[1]), "slope": float(slope), "intercept": float(inter)})
    return out


def _report() -> Path:
    from .report import build_report
    assets = []
    for rid in [r["id"] for r in SESSION["rows"]]:
        a = SESSION["assets"].get(rid)
        if not a: continue
        cells = pd.read_csv(a["cells_csv"]) if a.get("cells_csv") and Path(a["cells_csv"]).exists() else None
        assets.append({"summary": a["summary"], "qc": a.get("qc", []), "images": a.get("images", {}), "cells": cells})
    stats = None
    if any(r.get("group") for r in SESSION["rows"]):
        stats = {"groups": {}, "tests": {}, "note": ""}
        for m, _ in [("h_score", ""), ("pct_positive", ""), ("allred_total", ""), ("dab_area_fraction_pct", ""), ("mean_dab_od_tissue", "")]:
            s = _stats(m); stats["groups"] = s["groups"] or stats["groups"]; stats["note"] = s["note"]
            t = s["tests"]
            if "welch_t" in t: stats["tests"][m] = {"test": "Welch t", "p": t["welch_t"]["p"]}
            elif "anova" in t: stats["tests"][m] = {"test": "ANOVA", "p": t["anova"]["p"]}
    out = OUT / f"ihcq_report_{time.strftime('%Y%m%d_%H%M')}.pdf"
    rows = [{k: v for k, v in r.items() if k != "id"} for r in SESSION["rows"]]
    build_report(assets, rows, stats, out)
    return out


def _polys_mask(shape, polys) -> np.ndarray:
    from PIL import ImageDraw
    m = Image.new("L", (shape[1], shape[0]), 0); d = ImageDraw.Draw(m)
    for poly in polys or []:
        pts = [(float(x), float(y)) for x, y in poly]
        if len(pts) >= 3: d.polygon(pts, fill=1)
    return np.array(m, dtype=bool)


PROJECT_VERSION = 1


def _project_save() -> Path:
    """Zip every image's original plus the exact settings, cut points, regions and group."""
    import zipfile
    out = OUT / f"IHCq_project_{time.strftime('%Y%m%d_%H%M')}.ihcq"
    items = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for k, r in enumerate(SESSION["rows"]):
            a = SESSION["assets"].get(r["id"], {})
            orig = a.get("images", {}).get("original")
            if not orig or not Path(orig).exists():
                continue
            arc = f"images/{k:03d}_{_safe(r['image'])}.png"
            z.write(orig, arc)
            items.append({"name": r["image"], "file": arc, "config": a.get("config"), "roi": a.get("roi", {"include": [], "exclude": []}),
                          "clicks": a.get("clicks"), "tumour_only": a.get("tumour_only"),
                          "thresholds": a.get("thresholds"), "group": r.get("group", ""), "summary_at_save": {x: r.get(x) for x in ("n_cells", "pct_positive", "h_score", "her2_score")}})
        z.writestr("manifest.json", json.dumps({"format": "IHCq project", "version": PROJECT_VERSION, "saved": time.strftime("%Y-%m-%d %H:%M"), "images": items}, indent=2))
    return out


def _project_open(raw: bytes) -> dict:
    import zipfile
    from .io import _to_rgb8
    z = zipfile.ZipFile(_io.BytesIO(raw))
    try:
        man = json.loads(z.read("manifest.json"))
    except KeyError:
        raise ValueError("not an IHCq project (no manifest.json)")
    if man.get("format") != "IHCq project":
        raise ValueError("not an IHCq project")
    results, mismatches = [], []
    for it in man.get("images", []):
        with Image.open(_io.BytesIO(z.read(it["file"]))) as im:
            rgb = _to_rgb8(np.array(im.convert("RGB")))
        cfg = Config.from_dict(it["config"]) if it.get("config") else Config()
        out = _score(rgb, cfg, it["name"])
        rid = out["id"]
        if it.get("group"):
            SESSION["groups"][rid] = it["group"]
        roi = it.get("roi") or {}
        th = it.get("thresholds")
        th = Thresholds(**th) if th and (th != vars(cfg.thresholds)) else None
        if roi.get("include") or roi.get("exclude") or it.get("group") or th is not None:
            out = _derive(_cached(rid), th=th, roi=roi)
        if it.get("clicks"):
            out = _classify(rid, it["clicks"]["tumour"], it["clicks"]["stroma"], bool(it.get("tumour_only", True)))
        elif it.get("tumour_only") is not None:
            e = _cached(rid); e["tumour_only"] = bool(it["tumour_only"]); out = _derive(e)
        was, now = it.get("summary_at_save", {}), out["summary"]
        if was.get("h_score") is not None and now.get("h_score") is not None and abs(was["h_score"] - now["h_score"]) > 0.05:
            mismatches.append(it["name"])
        results.append(out)
    return {"results": results, "saved": man.get("saved"), "mismatches": mismatches}


def _calibrate(groups: dict) -> dict:
    from .calibrate import fit_from_cells
    od = {}
    for cat, ids in groups.items():
        arrs = [SESSION["cache"][i]["res"].cells["dab_od"].to_numpy() for i in ids if i in SESSION["cache"] and len(SESSION["cache"][i]["res"].cells)]
        od[cat] = np.concatenate(arrs) if arrs else np.array([])
    th, table = fit_from_cells(od)
    return {"thresholds": {"weak": th.weak, "moderate": th.moderate, "strong": th.strong}, "table": table.to_dict(orient="records")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=lambda o: None).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def _file(self, p: Path, ctype: str, download=False):
        if not p.exists():
            return self._send(404, {"error": "not found"})
        data = p.read_bytes()
        self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        if download: self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._file(STATIC / "index.html", "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            name = Path(u.path).name
            ctype = {"css": "text/css", "js": "application/javascript", "svg": "image/svg+xml"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
            return self._file(STATIC / name, ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))
        if u.path == "/api/demo" and (q.get("kind") or ["real"])[0] == "real":
            from .io import _to_rgb8
            rgb = _to_rgb8(np.array(Image.open(STATIC / "demo_ihc.png").convert("RGB")))
            cfg = _cfg_from_query(q)
            if not q.get("compartment"):
                cfg.compartment, cfg.cell_statistic = "membrane", "p90"
            out = _score(rgb, cfg, "demo_colon_membrane")
            out["note"] = "Real IHC: colon epithelium, membranous DAB, hematoxylin counterstain (scikit-image reference image). Epithelial nests should read positive, the stroma between them negative."
            return self._send(200, out)
        if u.path == "/api/demo":
            from .synth import make_field
            fr = {"negative": (1, 0, 0, 0), "low": (0.75, 0.15, 0.08, 0.02), "mixed": (0.4, 0.2, 0.25, 0.15), "high": (0.1, 0.1, 0.3, 0.5)}.get((q.get("kind") or ["mixed"])[0], (0.4, 0.2, 0.25, 0.15))
            rgb, truth, ts, _ = make_field(n_cells=350, fractions=fr, seed=int(time.time()) % 1000)
            out = _score(rgb, _cfg_from_query(q), "demo_" + (q.get("kind") or ["mixed"])[0])
            out["truth"] = {"h_score": ts["true_h_score"], "pct_positive": ts["true_pct_positive"], "n_cells": ts["true_n_cells"]}
            return self._send(200, out)
        if u.path == "/api/stats":
            return self._send(200, _stats((q.get("metric") or ["h_score"])[0]))
        if u.path == "/api/correlate":
            return self._send(200, _correlate((q.get("x") or ["pct_positive"])[0], (q.get("y") or ["h_score"])[0]))
        if u.path == "/api/report":
            try:
                p = _report()
            except Exception as e:
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return self._file(p, "application/pdf", download=True)
        if u.path == "/api/project/save":
            if not SESSION["rows"]:
                return self._send(400, {"error": "nothing scored yet"})
            return self._file(_project_save(), "application/zip", download=True)
        if u.path == "/api/session":
            with SESSION["lock"]:
                return self._send(200, {"rows": SESSION["rows"], "cached": list(SESSION["cache"].keys())})
        if u.path.startswith("/out/"):
            p = OUT / Path(u.path[5:]).name
            return self._file(p, "image/png" if p.suffix == ".png" else "text/csv", download=p.suffix == ".csv")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        n = int(self.headers.get("Content-Length", 0)); raw = self.rfile.read(n) if n else b""
        try:
            if u.path == "/api/quit":
                self._send(200, {"ok": True}); threading.Thread(target=SESSION["server"].shutdown, daemon=True).start(); return
            if u.path == "/api/score":
                from .io import _to_rgb8
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(_io.BytesIO(raw)) as im:
                    rgb = _to_rgb8(np.array(im.convert("RGB")))
                name = (q.get("name") or ["image"])[0]
                return self._send(200, _score(rgb, _cfg_from_query(q), Path(name).stem))
            if u.path == "/api/rebin":
                th = Thresholds(float(q["weak"][0]), float(q["moderate"][0]), float(q["strong"][0])); th.validate()
                return self._send(200, _rebin(q["id"][0], th))
            if u.path == "/api/project/open":
                return self._send(200, _project_open(raw))
            if u.path == "/api/classify":
                body = json.loads(raw or b"{}")
                return self._send(200, _classify(q["id"][0], body.get("tumour") or [], body.get("stroma") or [], bool(body.get("tumour_only", True))))
            if u.path == "/api/tumour_only":
                e = _cached(q["id"][0]); e["tumour_only"] = (q.get("on") or ["1"])[0] == "1"
                return self._send(200, _derive(e))
            if u.path == "/api/regions":
                body = json.loads(raw or b"{}")
                return self._send(200, _regions(q["id"][0], body.get("include") or []))
            if u.path == "/api/roi":
                body = json.loads(raw or b"{}")
                return self._send(200, _roi(q["id"][0], body.get("include") or [], body.get("exclude") or []))
            if u.path == "/api/reanalyze":
                return self._send(200, _reanalyze(q["id"][0], _cfg_from_query(q)))
            if u.path == "/api/group":
                body = json.loads(raw or b"{}"); rid, grp = body.get("id"), (body.get("group") or "").strip()
                SESSION["groups"][rid] = grp
                with SESSION["lock"]:
                    for r in SESSION["rows"]:
                        if r["id"] == rid: r["group"] = grp
                    if rid in SESSION["assets"] and "summary" in SESSION["assets"][rid]: SESSION["assets"][rid]["summary"]["group"] = grp
                    pd.DataFrame(SESSION["rows"]).drop(columns=["id"]).to_csv(OUT / "session_results.csv", index=False)
                return self._send(200, {"ok": True})
            if u.path == "/api/calibrate":
                body = json.loads(raw or b"{}")
                return self._send(200, _calibrate(body.get("groups", {})))
        except Exception as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "not found"})


def _port_open(host, port) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) == 0


def main(open_browser: bool = True, port: int = PORT):
    url = f"http://{HOST}:{port}/"
    if _port_open(HOST, port):
        print(f"IHCq is already running at {url}")
        if open_browser: webbrowser.open(url)
        return
    server = ThreadingHTTPServer((HOST, port), Handler)
    SESSION["server"] = server
    print(f"IHCq app at {url}   (outputs in {OUT})")
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
