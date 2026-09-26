"""Membrane completeness and HER2 scoring (ASCO/CAP 2018, with the 2023
HER2-low / ultralow categories).

A pathologist scores HER2 on two things per tumour cell: whether the
membrane stain goes *all the way round* (complete, circumferential) and how
*strong* it is.  Here each nucleus gets a cell territory (nearest-nucleus
region out to a fixed expansion, like QuPath's cell expansion).  The
territory outside the nucleus is split into angular sectors around the
nucleus centre; each sector's membrane signal is the peak smoothed DAB OD
along it.  Completeness is the fraction of sectors whose peak reaches the
weak cut point; membrane intensity is the median peak over stained sectors.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

N_SECTORS = 24


def sector_profile(labels: np.ndarray, dab: np.ndarray, tissue: np.ndarray, expand_px: int, n_sectors: int = N_SECTORS, smooth: float = 1.0):
    """Per-nucleus, per-sector peak DAB OD in the cell territory outside the nucleus.

    Returns (peaks, has): float32 (n, S) and bool (n, S), row i = label i+1.
    `has` marks sectors that contain any territory pixel (a cell squeezed
    against a neighbour or the tissue edge has fewer usable sectors).
    """
    n = int(labels.max())
    if n == 0:
        return np.zeros((0, n_sectors), np.float32), np.zeros((0, n_sectors), bool)
    dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
    terr = np.where((dist <= expand_px) & tissue, labels[iy, ix], 0)
    ys, xs = np.nonzero((terr > 0) & (labels == 0))
    lab = terr[ys, xs]
    cy, cx = np.array(ndi.center_of_mass(labels > 0, labels, np.arange(1, n + 1))).T
    ang = np.arctan2(ys - cy[lab - 1], xs - cx[lab - 1])
    sec = (((ang + np.pi) / (2 * np.pi)) * n_sectors).astype(np.int64) % n_sectors
    d = ndi.gaussian_filter(dab.astype(np.float32), smooth) if smooth else dab
    idx = (lab.astype(np.int64) - 1) * n_sectors + sec
    peaks = np.zeros(n * n_sectors, np.float32)
    np.maximum.at(peaks, idx, d[ys, xs])
    has = np.zeros(n * n_sectors, bool); has[idx] = True
    return peaks.reshape(n, n_sectors), has.reshape(n, n_sectors)


def membrane_calls(peaks: np.ndarray, has: np.ndarray, th, complete_frac: float = 0.8, min_sectors: int = 8):
    """Completeness (0–1), membrane OD and class per cell.

    class: 0 no membrane staining · 1 incomplete · 2 complete (≥ complete_frac of sectors).
    Cells with fewer than `min_sectors` usable sectors can't be judged for
    completeness and are classed on intensity alone (incomplete at most).
    """
    usable = has.sum(1)
    stained = (peaks >= th.weak) & has
    ns = stained.sum(1)
    completeness = np.where(usable > 0, ns / np.maximum(usable, 1), 0.0)
    mem_od = np.array([np.median(p[s]) if s.any() else (p[h].max() if h.any() else 0.0) for p, s, h in zip(peaks, stained, has)], dtype=np.float32)
    cls = np.where(ns == 0, 0, np.where((completeness >= complete_frac) & (usable >= min_sectors), 2, 1)).astype(np.int8)
    return completeness.astype(np.float32), mem_od, cls


def her2_summary(completeness, mem_od, cls, th, pct_cut: float = 10.0) -> dict:
    """Field-level HER2 score from per-cell membrane calls (tumour cells only, ideally).

    ASCO/CAP 2018 (with 2023 low/ultralow wording):
      3+  complete, intense membrane staining in >10 % of tumour cells
      2+  weak–moderate complete staining in >10 %  (or intense but incomplete in >10 %)
      1+  incomplete, faint staining in >10 %
      0   none, or incomplete faint staining in ≤10 %  (ultralow if any, null if none)
    """
    n = len(cls)
    if n == 0:
        return {"her2_score": None, "her2_category": None}
    strong = mem_od >= th.strong
    moderate = mem_od >= th.moderate
    c_strong = ((cls == 2) & strong).mean() * 100
    c_any = (cls == 2).mean() * 100
    inc_mod = ((cls == 1) & moderate).mean() * 100
    any_stain = (cls > 0).mean() * 100
    if c_strong > pct_cut:
        score, cat = "3+", "HER2-positive"
    elif c_any > pct_cut or inc_mod > pct_cut:
        score, cat = "2+", "HER2-equivocal (reflex ISH) · HER2-low if ISH negative"
    elif any_stain > pct_cut:
        score, cat = "1+", "HER2-low"
    elif any_stain > 0:
        score, cat = "0", "HER2-ultralow"
    else:
        score, cat = "0", "HER2-null"
    return {"her2_score": score, "her2_category": cat, "her2_cells": int(n),
            "pct_complete_strong": round(float(c_strong), 2), "pct_complete_any": round(float(c_any), 2),
            "pct_incomplete": round(float((cls == 1).mean() * 100), 2), "pct_membrane_any": round(float(any_stain), 2),
            "mean_completeness_stained": round(float(completeness[cls > 0].mean()), 3) if (cls > 0).any() else None}
