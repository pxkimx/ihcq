"""Derive intensity thresholds (and optionally stain vectors) from control
material, so that 1+/2+/3+ mean something about *your* stain, not a textbook's.

Two routes:

* `calibrate(groups)` — control images grouped by the intensity a pathologist
  assigned to their positive cells.  The negative control fixes the 0/1+ cut
  (nothing in it may score positive); the 1+/2+ and 2+/3+ cuts are placed
  between the positive-cell populations of adjacent groups.
* `fit_to_scores(scored)` — images with a pathologist H-score each.  Searches
  threshold triples for the one whose computed H-scores agree best with the
  pathologist's.  This is the route for concordance validation.
"""
from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, Thresholds
from .pipeline import analyze
from .io import load_image
from .stains import estimate_stain_vectors
from .metrics import h_score, bin_intensity

CATS = ("negative", "weak", "moderate", "strong")


def collect_cell_od(paths, cfg: Config) -> np.ndarray:
    vals = []
    for p in paths:
        res = analyze(load_image(p), cfg)
        if len(res.cells):
            vals.append(res.cells["dab_od"].to_numpy())
    return np.concatenate(vals) if vals else np.array([])


def _between(lo: np.ndarray, hi: np.ndarray, default: float) -> float:
    """Cut between two adjacent positive populations: halfway between the
    upper quartile of the lower one and the lower quartile of the upper one
    when they separate, else halfway between their medians."""
    if lo.size and hi.size:
        a, b = np.percentile(lo, 75), np.percentile(hi, 25)
        mid = (a + b) / 2 if b > a else (np.median(lo) + np.median(hi)) / 2
        return float(round(mid, 3))
    if lo.size:
        return float(round(max(np.percentile(lo, 95), default), 3))
    if hi.size:
        return float(round(min(np.percentile(hi, 5), default), 3))
    return default


def calibrate(groups: dict, base: Config | None = None, estimate_stains: bool = False,
              name: str = "calibrated", negative_margin: float = 1.15) -> tuple[Config, pd.DataFrame]:
    """`groups`: {"negative": [paths], "weak": [...], "moderate": [...], "strong": [...]} (any subset)."""
    cfg = Config.from_dict((base or Config()).to_dict())
    if estimate_stains:
        pool = [p for c in ("strong", "moderate", "negative") for p in groups.get(c, [])]
        if pool:
            m = estimate_stain_vectors(load_image(pool[0]))
            cfg.stain_vectors = [list(map(float, m[0])), list(map(float, m[1]))]
    od = {c: collect_cell_od(groups.get(c, []), cfg) for c in CATS}
    d = Thresholds()

    # 0 / 1+: nothing in the negative control may be called positive
    neg = od["negative"]
    weak = float(round(max(np.percentile(neg, 99.5) * negative_margin, 0.06), 3)) if neg.size else d.weak

    # upper cuts from the positive cells of each control
    pos = {c: od[c][od[c] >= weak] for c in ("weak", "moderate", "strong")}
    moderate = _between(pos["weak"], pos["moderate"] if pos["moderate"].size else pos["strong"], d.moderate)
    strong = _between(pos["moderate"], pos["strong"], d.strong)
    moderate = max(moderate, weak + 0.05)
    strong = max(strong, moderate + 0.05)
    cfg.thresholds = Thresholds(weak=weak, moderate=moderate, strong=strong)
    cfg.profile_name = name

    rows = []
    for c in CATS:
        v = od[c] if c == "negative" else pos.get(c, np.array([]))
        rows.append({"category": c, "cells_used": int(v.size),
                     "note": "all cells" if c == "negative" else f"positive cells (≥{weak})",
                     **({"p10": round(float(np.percentile(v, 10)), 3), "median": round(float(np.median(v)), 3),
                         "p90": round(float(np.percentile(v, 90)), 3)} if v.size else {"p10": None, "median": None, "p90": None})})
    return cfg.validate(), pd.DataFrame(rows)


def fit_to_scores(scored: pd.DataFrame, base: Config | None = None, name: str = "fitted",
                  grid_step: float = 0.05, image_root=None) -> tuple[Config, pd.DataFrame]:
    """Fit thresholds so computed H-scores agree with pathologist H-scores.

    `scored` needs columns `image` (path) and `h_score` (0–300).  Per-cell OD
    is computed once per image; then every (weak, moderate, strong) triple on
    a grid is evaluated and the one with the lowest mean absolute error wins.
    Returns the config and a per-image table of pathologist vs fitted scores.
    """
    cfg = Config.from_dict((base or Config()).to_dict())
    root = Path(image_root) if image_root else Path(".")
    cells, target = [], []
    for _, r in scored.iterrows():
        p = Path(r["image"]); p = p if p.is_absolute() else root / p
        res = analyze(load_image(p), cfg)
        cells.append(res.cells["dab_od"].to_numpy() if len(res.cells) else np.array([]))
        target.append(float(r["h_score"]))
    target = np.asarray(target)
    grid = np.round(np.arange(0.05, 1.6, grid_step), 3)
    best, best_err = None, np.inf
    for w, m, s in product(grid, grid, grid):
        if not (w < m < s):
            continue
        th = Thresholds(w, m, s)
        pred = np.array([h_score(bin_intensity(c, th)) if c.size else np.nan for c in cells])
        err = np.nanmean(np.abs(pred - target))
        if err < best_err:
            best, best_err = th, err
    cfg.thresholds = best
    cfg.profile_name = name
    pred = np.array([h_score(bin_intensity(c, best)) if c.size else np.nan for c in cells])
    table = pd.DataFrame({"image": scored["image"], "pathologist_h": target, "fitted_h": np.round(pred, 1),
                          "abs_error": np.round(np.abs(pred - target), 1), "n_cells": [c.size for c in cells]})
    return cfg.validate(), table
