"""Scores.  Each function is small and documented so that adding a new
scheme (e.g. a lab-specific modified H-score) is one more function here."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import ndimage as ndi

from .config import Thresholds

BIN_NAMES = {0: "0", 1: "1+", 2: "2+", 3: "3+"}


def bin_intensity(od: np.ndarray, th: Thresholds) -> np.ndarray:
    """Map DAB OD → {0,1,2,3}."""
    od = np.asarray(od)
    return (od >= th.weak).astype(np.int8) + (od >= th.moderate) + (od >= th.strong)


# --------------------------------------------------------------------------
# cell-level
# --------------------------------------------------------------------------
def per_cell_table(labels: np.ndarray, score_labels: np.ndarray, dab: np.ndarray, hema: np.ndarray,
                   th: Thresholds, statistic: str = "mean", mpp: float | None = None) -> pd.DataFrame:
    """One row per cell: position, size, DAB summary in the scoring compartment, bin."""
    n = int(labels.max())
    if n == 0:
        return pd.DataFrame(columns=["cell", "y", "x", "area_px", "dab_od", "hema_od", "bin", "bin_name"])
    idx = np.arange(1, n + 1)
    cy, cx = zip(*ndi.center_of_mass(labels > 0, labels, idx)) if n else ([], [])
    area = ndi.sum(np.ones_like(labels, dtype=np.float32), labels, idx)
    hema_mean = ndi.mean(hema, labels, idx)

    if statistic == "mean":
        dab_stat = ndi.mean(dab, score_labels, idx)
    elif statistic == "median":
        dab_stat = ndi.median(dab, score_labels, idx)
    else:  # p90
        dab_stat = np.array([np.percentile(dab[score_labels == i], 90) if (score_labels == i).any() else 0.0 for i in idx])
    dab_stat = np.nan_to_num(np.asarray(dab_stat, dtype=np.float64))
    bins = bin_intensity(dab_stat, th)
    from skimage.measure import regionprops
    props = {r.label: r for r in regionprops(labels)}
    ecc = np.array([props[i].eccentricity if i in props else 0.0 for i in idx])
    sol = np.array([props[i].solidity if i in props else 0.0 for i in idx])
    df = pd.DataFrame({
        "cell": idx, "y": np.round(cy, 1), "x": np.round(cx, 1), "area_px": area.astype(int),
        "eccentricity": np.round(ecc, 3), "solidity": np.round(sol, 3),
        "dab_od": np.round(dab_stat, 4), "hema_od": np.round(hema_mean, 4),
        "bin": bins, "bin_name": [BIN_NAMES[int(b)] for b in bins],
    })
    if mpp:
        df["area_um2"] = np.round(df["area_px"] * mpp * mpp, 2)
    return df


def h_score(bins: np.ndarray) -> float:
    """H-score = Σ (intensity × % of cells at that intensity), 0–300."""
    bins = np.asarray(bins)
    if bins.size == 0:
        return float("nan")
    pct = np.array([(bins == k).mean() * 100 for k in (1, 2, 3)])
    return float(np.round(1 * pct[0] + 2 * pct[1] + 3 * pct[2], 1))


def allred(bins: np.ndarray) -> dict:
    """Allred score: proportion score (0–5) + intensity score (0–3) = 0–8."""
    bins = np.asarray(bins)
    if bins.size == 0:
        return {"allred_ps": None, "allred_is": None, "allred_total": None}
    pos = bins > 0
    frac = pos.mean()
    if frac == 0:
        ps = 0
    elif frac <= 0.01:
        ps = 1
    elif frac <= 0.10:
        ps = 2
    elif frac <= 1 / 3:
        ps = 3
    elif frac <= 2 / 3:
        ps = 4
    else:
        ps = 5
    is_ = int(np.round(bins[pos].mean())) if pos.any() else 0
    return {"allred_ps": ps, "allred_is": is_, "allred_total": ps + is_}


def irs(bins: np.ndarray) -> dict:
    """Immunoreactive score (Remmele & Stegner): proportion score (0: ≤5 %,
    1: 6–25 %, 2: 26–50 %, 3: >50 % positive) × intensity score (0–3, the
    rounded mean bin of positive cells) = 0–12."""
    bins = np.asarray(bins)
    if bins.size == 0:
        return {"irs_ps": None, "irs_is": None, "irs": None}
    pos = bins > 0
    f = pos.mean() * 100
    ps = 0 if f <= 5 else 1 if f <= 25 else 2 if f <= 50 else 3
    is_ = int(np.round(bins[pos].mean())) if pos.any() else 0
    return {"irs_ps": ps, "irs_is": is_, "irs": ps * is_}


def profiler_score(px_bins: np.ndarray) -> dict:
    """Four-tier pixel score in the spirit of IHC Profiler (Varghese 2014):
    the percentage of tissue pixels in each intensity zone and the zone that
    dominates the stained pixels.  Zones follow this tool's OD cut points
    rather than IHC Profiler's fixed 8-bit intensity bands."""
    px_bins = np.asarray(px_bins)
    if px_bins.size == 0:
        return {"profiler_zone": None, "profiler_pct": None}
    pct = [(px_bins == k).mean() * 100 for k in range(4)]
    names = ["negative", "low positive", "positive", "high positive"]
    # IHC Profiler's rule: score = zone holding the largest share of stained pixels,
    # unless the field is essentially unstained
    stained = pct[1] + pct[2] + pct[3]
    zone = "negative" if stained < 5 else names[1 + int(np.argmax(pct[1:]))]
    return {"profiler_zone": zone, "profiler_pct": [round(v, 2) for v in pct]}


def hotspot(df: pd.DataFrame, window_cells: int = 500) -> dict:
    """Ki-67-style hotspot: among all neighbourhoods of `window_cells` nearest
    cells, the one with the highest positive fraction (IKWG counts ≥500
    tumour cells in the hottest field).  Also returns the coldest, so the
    heterogeneity across the field is visible next to the global index."""
    n = len(df)
    if n < 50:
        return {"hotspot_pct_positive": None, "hotspot_xy": None, "coldspot_pct_positive": None, "hotspot_window": None}
    from scipy.spatial import cKDTree
    # A window that holds every cell is not a hotspot, it is the global index.
    # Use at most a quarter of the field so hot and cold regions can differ.
    k = int(min(window_cells, max(30, n // 4)))
    pts = df[["x", "y"]].to_numpy()
    pos = (df["bin"].to_numpy() > 0).astype(float)
    tree = cKDTree(pts)
    # evaluate windows centred on a subsample of cells (all if small)
    idx = np.arange(n) if n <= 2000 else np.random.default_rng(0).choice(n, 2000, replace=False)
    _, nb = tree.query(pts[idx], k=k)
    frac = pos[nb].mean(axis=1)
    hi, lo = int(np.argmax(frac)), int(np.argmin(frac))
    return {"hotspot_pct_positive": round(float(frac[hi] * 100), 2), "hotspot_xy": [round(float(pts[idx[hi]][0]), 1), round(float(pts[idx[hi]][1]), 1)],
            "coldspot_pct_positive": round(float(frac[lo] * 100), 2), "hotspot_window": int(k)}


def cell_summary(df: pd.DataFrame, tissue_area_px: int, mpp: float | None = None) -> dict:
    """Aggregate the per-cell table into report-level numbers."""
    n = len(df)
    out = {"n_cells": n}
    if n == 0:
        out.update({"pct_positive": None, "pct_1plus": None, "pct_2plus": None, "pct_3plus": None,
                    "h_score": None, "allred_ps": None, "allred_is": None, "allred_total": None,
                    "mean_cell_dab_od": None})
        return out
    b = df["bin"].to_numpy()
    out["pct_positive"] = round(float((b > 0).mean() * 100), 2)
    for k in (1, 2, 3):
        out[f"pct_{k}plus"] = round(float((b == k).mean() * 100), 2)
    out["h_score"] = h_score(b)
    out.update(allred(b))
    out.update(irs(b))
    out.update(hotspot(df))
    out["mean_cell_dab_od"] = round(float(df["dab_od"].mean()), 4)
    out["cells_per_tissue_px1e4"] = round(n / max(tissue_area_px, 1) * 1e4, 3)
    if mpp:
        mm2 = tissue_area_px * (mpp / 1000.0) ** 2
        out["cells_per_mm2"] = round(n / max(mm2, 1e-9), 1)
        out["positive_cells_per_mm2"] = round(int((b > 0).sum()) / max(mm2, 1e-9), 1)
    return out


# --------------------------------------------------------------------------
# pixel-level
# --------------------------------------------------------------------------
def pixel_summary(dab: np.ndarray, hema: np.ndarray, tissue: np.ndarray, th: Thresholds,
                  positive_od: float | None = None, mpp: float | None = None) -> dict:
    """Area fraction, optical density and integrated OD over the tissue footprint."""
    t = positive_od if positive_od is not None else th.weak
    n_tissue = int(tissue.sum())
    out = {"tissue_px": n_tissue, "tissue_fraction": round(float(tissue.mean()), 4)}
    if n_tissue == 0:
        out.update({"dab_area_fraction_pct": None, "hema_area_fraction_pct": None,
                    "mean_dab_od_tissue": None, "mean_dab_od_positive": None, "integrated_dab_od": None,
                    "pct_px_1plus": None, "pct_px_2plus": None, "pct_px_3plus": None})
        return out
    d = dab[tissue]
    h = hema[tissue]
    pos = d >= t
    bins = bin_intensity(d, th)
    out["dab_area_fraction_pct"] = round(float(pos.mean() * 100), 3)
    out["hema_area_fraction_pct"] = round(float((h >= t).mean() * 100), 3)
    out["mean_dab_od_tissue"] = round(float(d.mean()), 4)
    out["mean_dab_od_positive"] = round(float(d[pos].mean()), 4) if pos.any() else 0.0
    out["p95_dab_od_tissue"] = round(float(np.percentile(d, 95)), 4)
    out["integrated_dab_od"] = round(float(d.sum()), 1)
    for k in (1, 2, 3):
        out[f"pct_px_{k}plus"] = round(float((bins == k).mean() * 100), 3)
    # a pixel-level H-score analogue: same arithmetic, over tissue pixels
    out["pixel_h_score"] = h_score(bins)
    out.update(profiler_score(bins))
    if mpp:
        out["tissue_area_mm2"] = round(n_tissue * (mpp / 1000.0) ** 2, 4)
        out["dab_area_mm2"] = round(int(pos.sum()) * (mpp / 1000.0) ** 2, 4)
    return out
