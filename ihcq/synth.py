"""Synthetic IHC fields with known ground truth.

Forward-modelled through the same Beer–Lambert optics the analysis inverts,
then degraded with noise, blur, uneven illumination and hematoxylin quenching
by DAB — so recovering the truth is a genuine test of segmentation and
scoring, not just of the matrix inverse.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stains import stain_matrix, od_to_rgb

# per-bin DAB OD ranges used to draw cells (deliberately not aligned with the
# default thresholds' midpoints, so calibration has something to do)
BIN_OD = {0: (0.0, 0.08), 1: (0.20, 0.34), 2: (0.48, 0.72), 3: (0.95, 1.45)}


def make_field(n_cells=400, fractions=(0.4, 0.2, 0.25, 0.15), size=(768, 1024), seed=0,
               matrix=None, noise=2.5, blur=0.7, radius=(6, 10), dab_cyto=0.0) -> tuple[np.ndarray, pd.DataFrame, dict]:
    """Return (rgb, truth_cells, truth_summary).

    fractions: proportion of cells in bins 0, 1+, 2+, 3+.
    dab_cyto: extra DAB OD painted as diffuse cytoplasm around positive cells
              (raises pixel area fraction without changing the cell H-score).
    """
    rng = np.random.default_rng(seed)
    H, W = size
    matrix = matrix if matrix is not None else stain_matrix()
    fr = np.asarray(fractions, dtype=float); fr = fr / fr.sum()

    yy, xx = np.mgrid[0:H, 0:W]
    # tissue footprint: a big soft blob, leaving glass at the edges
    cy, cx = H * 0.5 + rng.normal(0, 30), W * 0.5 + rng.normal(0, 40)
    ry, rx = H * 0.42, W * 0.44
    tissue = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1.0 + 0.08 * np.sin(xx / 37.0) + 0.06 * np.cos(yy / 29.0)

    hema = np.where(tissue, rng.uniform(0.05, 0.11), 0.0) * (1 + 0.15 * np.sin(xx / 53.0) * np.cos(yy / 41.0))
    dab = np.zeros((H, W), dtype=np.float64)
    truth_dab = np.zeros((H, W), dtype=np.float64)

    # place nuclei with a minimum spacing inside tissue
    pts, tries = [], 0
    min_d = radius[1] * 2.2
    while len(pts) < n_cells and tries < n_cells * 60:
        tries += 1
        y, x = rng.uniform(radius[1] + 2, H - radius[1] - 2), rng.uniform(radius[1] + 2, W - radius[1] - 2)
        if not tissue[int(y), int(x)]:
            continue
        if pts and np.min(np.hypot(np.array(pts)[:, 0] - y, np.array(pts)[:, 1] - x)) < min_d:
            continue
        pts.append((y, x))
    pts = np.array(pts)
    bins = rng.choice(4, size=len(pts), p=fr)
    rows = []
    for (y, x), b in zip(pts, bins):
        a, c = rng.uniform(*radius), rng.uniform(*radius)
        th = rng.uniform(0, np.pi)
        dy, dx = yy - y, xx - x
        u = dy * np.cos(th) + dx * np.sin(th); v = -dy * np.sin(th) + dx * np.cos(th)
        m = (u / a) ** 2 + (v / c) ** 2 <= 1.0
        d_od = rng.uniform(*BIN_OD[int(b)])
        h_od = rng.uniform(0.55, 0.85)
        # strong DAB quenches the counterstain: the classic reason hematoxylin-only
        # segmentation loses positive nuclei
        h_od *= 1.0 - 0.6 * min(d_od / 1.2, 1.0)
        hema[m] = h_od
        dab[m] = d_od
        truth_dab[m] = d_od
        if dab_cyto > 0 and b > 0:
            ring = ((u / (a + 4)) ** 2 + (v / (c + 4)) ** 2 <= 1.0) & ~m & tissue
            dab[ring] = np.maximum(dab[ring], dab_cyto * d_od)
        rows.append({"y": round(y, 1), "x": round(x, 1), "true_bin": int(b), "true_dab_od": round(d_od, 3)})
    truth = pd.DataFrame(rows)

    conc = np.stack([hema, dab, np.zeros_like(dab)], axis=-1)
    od = conc.reshape(-1, 3) @ matrix
    # uneven illumination: white point varies 238–252 across the field
    i0 = 245 + 7 * np.cos(xx / W * np.pi) * np.cos(yy / H * np.pi)
    i0 = np.stack([i0, i0 - 1.5, i0 - 3.0], axis=-1)
    rgb = (i0 + 1) * np.power(10.0, -od.reshape(H, W, 3)) - 1
    if blur:
        from scipy.ndimage import gaussian_filter
        rgb = np.stack([gaussian_filter(rgb[..., k], blur) for k in range(3)], axis=-1)
    rgb = rgb + rng.normal(0, noise, rgb.shape)
    rgb = np.clip(np.round(rgb), 0, 255).astype(np.uint8)

    from .metrics import h_score, allred
    tb = truth["true_bin"].to_numpy()
    summary = {
        "true_n_cells": int(len(truth)), "true_h_score": h_score(tb),
        "true_pct_positive": round(float((tb > 0).mean() * 100), 2),
        **{f"true_{k}": v for k, v in allred(tb).items()},
        "true_tissue_px": int(tissue.sum()),
    }
    return rgb, truth, summary, {"tissue": tissue, "dab": dab}
