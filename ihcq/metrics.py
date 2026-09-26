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
    df = pd.DataFrame({
        "cell": idx, "y": np.round(cy, 1), "x": np.round(cx, 1), "area_px": area.astype(int),
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
    if mpp:
        out["tissue_area_mm2"] = round(n_tissue * (mpp / 1000.0) ** 2, 4)
        out["dab_area_mm2"] = round(int(pos.sum()) * (mpp / 1000.0) ** 2, 4)
    return out
