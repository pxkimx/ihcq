"""DAB-free tumour-vs-stroma likelihood for each nucleus.

Uses only what hematoxylin shows — nuclear size, shape, hematoxylin
density and crowding — never the brown, so the classification cannot bias
the DAB scores it is used to gate.  Two-cluster k-means on robustly
standardised features; the cluster with larger, rounder, more crowded
nuclei is called tumour/epithelial.  It is a helper, not a diagnosis: when
the two populations don't separate, it says so and everything counts.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.measure import regionprops


def nucleus_features(labels: np.ndarray, hema: np.ndarray) -> np.ndarray:
    n = int(labels.max())
    if n == 0:
        return np.zeros((0, 5))
    props = regionprops(labels, intensity_image=hema)
    f = np.zeros((n, 5))
    cent = np.zeros((n, 2))
    for r in props:
        i = r.label - 1
        f[i, 0] = np.log(max(r.area, 1))
        f[i, 1] = r.eccentricity
        f[i, 2] = r.solidity
        f[i, 3] = r.intensity_mean if hasattr(r, "intensity_mean") else r.mean_intensity
        cent[i] = r.centroid
    med_r = np.sqrt(np.median(np.exp(f[:, 0])) / np.pi)
    tree = cKDTree(cent)
    f[:, 4] = np.log1p(np.array([len(x) - 1 for x in tree.query_ball_point(cent, r=6 * med_r)]))
    return f


def tumour_probability(labels: np.ndarray, hema: np.ndarray, seed: int = 0) -> tuple[np.ndarray, dict]:
    """Return (p_tumour per nucleus, diagnostics)."""
    f = nucleus_features(labels, hema)
    n = len(f)
    if n < 40:
        return np.full(n, 0.5), {"separated": False, "reason": "too few nuclei"}
    med = np.median(f, 0); mad = np.median(np.abs(f - med), 0) * 1.4826 + 1e-6
    z = np.clip((f - med) / mad, -4, 4)
    w = np.array([1.2, 1.0, 0.5, 0.7, 1.0])          # size and crowding matter most
    zw = z * w
    # init: most "tumour-like" (big, round, crowded) vs least
    t_score = z[:, 0] - z[:, 1] + z[:, 4]
    c = np.stack([zw[t_score >= np.percentile(t_score, 70)].mean(0), zw[t_score <= np.percentile(t_score, 30)].mean(0)])
    for _ in range(30):
        d = ((zw[:, None, :] - c[None]) ** 2).sum(-1)
        a = d.argmin(1)
        new = np.stack([zw[a == k].mean(0) if (a == k).any() else c[k] for k in (0, 1)])
        if np.allclose(new, c): break
        c = new
    d = np.sqrt(((zw[:, None, :] - c[None]) ** 2).sum(-1))
    p = d[:, 1] / (d[:, 0] + d[:, 1] + 1e-9)       # near centre 0 (tumour) → p → 1
    # tumour cluster = larger & rounder & more crowded on average
    tsc = [(z[a == k, 0].mean() - z[a == k, 1].mean() + z[a == k, 4].mean()) if (a == k).any() else -9 for k in (0, 1)]
    if tsc[1] > tsc[0]:
        p = 1 - p
    frac = float((p > 0.5).mean())
    sep = float(np.linalg.norm(c[0] - c[1]))
    ok = 0.05 <= frac <= 0.95 and sep > 1.0
    if not ok:
        p = np.full(n, 0.5)
    return p, {"separated": ok, "tumour_fraction": round(frac, 3), "separation": round(sep, 2)}
