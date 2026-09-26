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


def _predict(cells_od: list, th: Thresholds, target: str) -> np.ndarray:
    if target == "h_score":
        return np.array([h_score(bin_intensity(c, th)) if c.size else np.nan for c in cells_od])
    return np.array([(bin_intensity(c, th) > 0).mean() * 100 if c.size else np.nan for c in cells_od])


def fit_to_scores(scored: pd.DataFrame, base: Config | None = None, name: str = "fitted",
                  grid_step: float = 0.05, image_root=None, target: str | None = None,
                  cells_od: list | None = None) -> tuple[Config, pd.DataFrame]:
    """Fit thresholds so computed scores agree with reference scores.

    `scored` needs `image` (path) plus either `h_score` (0–300) — all three
    cuts are fitted — or `pct_positive` (0–100, e.g. a Ki-67 index) — only
    the 0/1+ cut is fitted, the upper cuts keep the base config's values.
    Per-cell OD is computed once per image (or passed in via `cells_od`),
    then the grid is searched for the lowest mean absolute error.
    """
    cfg = Config.from_dict((base or Config()).to_dict())
    target = target or ("h_score" if "h_score" in scored.columns else "pct_positive")
    root = Path(image_root) if image_root else Path(".")
    if cells_od is None:
        cells_od = []
        for _, r in scored.iterrows():
            p = Path(r["image"]); p = p if p.is_absolute() else root / p
            res = analyze(load_image(p), cfg)
            cells_od.append(res.cells["dab_od"].to_numpy() if len(res.cells) else np.array([]))
    ref = scored[target].to_numpy(dtype=float)
    grid = np.round(np.arange(0.05, 1.6, grid_step), 3)
    if target == "h_score":
        triples = [(w, m, s) for w, m, s in product(grid, grid, grid) if w < m < s]
    else:
        m0, s0 = cfg.thresholds.moderate, cfg.thresholds.strong
        triples = [(w, max(m0, w + 0.05), max(s0, w + 0.10)) for w in grid]
    best, best_err = None, np.inf
    for w, m, s in triples:
        th = Thresholds(w, m, s)
        err = np.nanmean(np.abs(_predict(cells_od, th, target) - ref))
        if err < best_err:
            best, best_err = th, err
    cfg.thresholds = best
    cfg.profile_name = name
    pred = _predict(cells_od, best, target)
    table = pd.DataFrame({"image": scored["image"], f"reference_{target}": ref, f"fitted_{target}": np.round(pred, 1),
                          "abs_error": np.round(np.abs(pred - ref), 1), "n_cells": [c.size for c in cells_od]})
    return cfg.validate(), table
