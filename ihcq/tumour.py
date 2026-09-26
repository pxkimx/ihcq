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


def rich_features(labels: np.ndarray, hema: np.ndarray, tissue: np.ndarray, reach: int = 30) -> np.ndarray:
    """Nucleus features + cell-territory size + hematoxylin texture (still no DAB)."""
    base = nucleus_features(labels, hema)
    n = int(labels.max())
    if n == 0:
        return np.zeros((0, 7))
    dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
    terr = np.where((dist <= reach) & tissue, labels[iy, ix], 0)
    tarea = np.bincount(terr.ravel(), minlength=n + 1)[1:]
    m = labels > 0
    s1 = np.bincount(labels[m], weights=hema[m], minlength=n + 1)[1:]
    s2 = np.bincount(labels[m], weights=hema[m] ** 2, minlength=n + 1)[1:]
    cnt = np.maximum(np.bincount(labels[m], minlength=n + 1)[1:], 1)
    hstd = np.sqrt(np.maximum(s2 / cnt - (s1 / cnt) ** 2, 0))
    return np.column_stack([base, np.log1p(tarea), hstd])


def fit_clicks(X: np.ndarray, tumour_idx, stroma_idx) -> tuple[np.ndarray, dict]:
    """Fisher LDA trained on clicked nuclei; returns p_tumour for every nucleus.

    Features are standardised on the whole field; the covariance is shrunk so
    a dozen clicks are enough.  Cross-validated accuracy on the clicks is
    reported so the user can see whether the two classes really separate."""
    t, s_ = np.asarray(tumour_idx, int), np.asarray(stroma_idx, int)
    if len(t) < 3 or len(s_) < 3:
        raise ValueError("click at least 3 tumour and 3 stromal nuclei")
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd

    def train(ti, si):
        m1, m0 = Z[ti].mean(0), Z[si].mean(0)
        S = (np.cov(Z[ti].T) if len(ti) > 1 else 0) + (np.cov(Z[si].T) if len(si) > 1 else 0)
        S = 0.5 * np.asarray(S) + 0.5 * np.eye(Z.shape[1])            # shrinkage toward identity
        w = np.linalg.solve(S, m1 - m0); c = w @ (m1 + m0) / 2
        return w, c

    # leave-one-out on the clicks
    correct = []
    for k in range(len(t)):
        w, c = train(np.delete(t, k), s_); correct.append(Z[t[k]] @ w > c)
    for k in range(len(s_)):
        w, c = train(t, np.delete(s_, k)); correct.append(Z[s_[k]] @ w <= c)
    w, c = train(t, s_)
    score = Z @ w - c
    scale = np.std(score) + 1e-9
    p = 1 / (1 + np.exp(-score / scale * 2.5))
    return p, {"separated": True, "source": "clicks", "clicks_tumour": int(len(t)), "clicks_stroma": int(len(s_)),
               "loo_accuracy": round(float(np.mean(correct)), 3), "tumour_fraction": round(float((p > 0.5).mean()), 3)}
