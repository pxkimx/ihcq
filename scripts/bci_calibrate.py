"""Fit DAB cut points to BCI HER2 labels and validate on held-out patches.

Per-cell membrane OD is collected once per patch (classical backend), then
the three OD cut points are searched to maximise agreement of an
ASCO/CAP-style rule (3+: ≥10 % of cells strong; 2+: ≥10 % moderate-or-more;
1+: ≥10 % any; else 0) with the patch label, on even-indexed patches; odd-
indexed patches are the validation set.  Patches carry their slide's score,
so a tumour-free patch is 'wrong' by construction — treat the numbers as a
lower bound.
"""
import glob, re, sys, time
from itertools import product
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ihcq import Config, analyze
from ihcq.io import load_image
from ihcq.metrics import bin_intensity
from ihcq.config import Thresholds

ROOT = "data/public/BCI/BCI_dataset/IHC/test"
files = sorted(glob.glob(f"{ROOT}/*.png"))
lab = [re.search(r"_(0|1\+|2\+|3\+)\.png$", f).group(1) for f in files]
order = {"0": 0, "1+": 1, "2+": 2, "3+": 3}
y = np.array([order[l] for l in lab])
cfg = Config(compartment="membrane", cell_statistic="p90")
cells, t0 = [], time.time()
for i, f in enumerate(files):
    res = analyze(load_image(f), cfg)
    cells.append(res.cells["dab_od"].to_numpy() if len(res.cells) else np.zeros(0))
    if (i + 1) % 100 == 0: print(f"  {i+1}/{len(files)} {time.time()-t0:.0f}s", flush=True)
np.savez_compressed("results/bci/percell_test_membrane_p90.npz", y=y, names=np.array([Path(f).name for f in files]),
                    cells=np.array(cells, dtype=object), allow_pickle=True)

def score(th, idx, pct=10.0):
    pred = np.zeros(len(idx), int)
    for k, i in enumerate(idx):
        c = cells[i]
        if c.size == 0: continue
        b = bin_intensity(c, th)
        p1, p2, p3 = (b >= 1).mean() * 100, (b >= 2).mean() * 100, (b >= 3).mean() * 100
        pred[k] = 3 if p3 >= pct else 2 if p2 >= pct else 1 if p1 >= pct else 0
    return pred

fit_idx, val_idx = np.arange(0, len(files), 2), np.arange(1, len(files), 2)
grid = np.round(np.arange(0.04, 1.2, 0.04), 3)
best, best_s = None, -1
for w, m, s in product(grid, grid, grid):
    if not (w < m < s): continue
    pred = score(Thresholds(w, m, s), fit_idx)
    acc1 = (np.abs(pred - y[fit_idx]) <= 1).mean(); exact = (pred == y[fit_idx]).mean()
    sc = exact + 0.5 * acc1
    if sc > best_s: best, best_s = (w, m, s), sc
w, m, s = best
print(f"\nfitted cut points (even patches): weak={w} moderate={m} strong={s}   (defaults 0.15 / 0.40 / 0.80)")
for name, th in (("default", Thresholds()), ("fitted", Thresholds(w, m, s))):
    pred = score(th, val_idx); yv = y[val_idx]
    cm = pd.crosstab(pd.Series(yv, name="truth"), pd.Series(pred, name="pred"))
    rho = spearmanr(yv, pred).correlation
    print(f"\n== held-out odd patches, {name} thresholds ==")
    print(cm.to_string())
    print(f"exact {np.mean(pred==yv):.3f}   within-one {np.mean(np.abs(pred-yv)<=1):.3f}   neg(0/1+) vs pos(2+/3+) {np.mean((pred>=2)==(yv>=2)):.3f}   Spearman {rho:.3f}")
