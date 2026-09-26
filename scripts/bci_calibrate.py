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

cells_sorted = [np.sort(c) for c in cells]
grid = np.round(np.arange(0.04, 1.2, 0.04), 3)
F = {t: np.array([(c.size - np.searchsorted(c, t)) / c.size * 100 if c.size else 0.0 for c in cells_sorted]) for t in grid}

def predict(w, m, s, pct=10.0):
    """ASCO/CAP-style rule over ALL cells: 3+ if ≥pct% of cells strong, 2+ if ≥pct% moderate-or-more, 1+ if ≥pct% any."""
    return np.where(F[s] >= pct, 3, np.where(F[m] >= pct, 2, np.where(F[w] >= pct, 1, 0)))

def balanced_acc(p, t):
    return float(np.mean([(p[t == k] == k).mean() for k in range(4) if (t == k).any()]))

# Objective: balanced accuracy, NOT exact accuracy.  Exact accuracy on these
# labels is maximised by calling almost everything "2+" (46 % of patches),
# which a first version of this script duly did with cut points of 0.04/0.08.
fit_idx, val_idx = np.arange(0, len(files), 2), np.arange(1, len(files), 2)
best, best_b = None, -1
for w, m, s in product(grid, grid, grid):
    if w < m < s:
        b = balanced_acc(predict(w, m, s)[fit_idx], y[fit_idx])
        if b > best_b: best, best_b = (w, m, s), b
w, m, s = best
print(f"\nfitted cut points (even patches, balanced accuracy {best_b:.3f}): weak={w} moderate={m} strong={s}   (defaults 0.15 / 0.40 / 0.80)")
for name, (a, b_, c) in (("default", (0.16, 0.40, 0.80)), ("fitted", (w, m, s))):
    pred, yv = predict(a, b_, c)[val_idx], y[val_idx]
    cm = pd.crosstab(pd.Series(yv, name="truth"), pd.Series(pred, name="pred")).reindex(index=range(4), columns=range(4), fill_value=0)
    print(f"\n== held-out odd patches, {name} thresholds ==\n{cm.to_string()}")
    print(f"balanced {balanced_acc(pred, yv):.3f}   exact {np.mean(pred==yv):.3f}   within-one {np.mean(np.abs(pred-yv)<=1):.3f}   "
          f"neg(0/1+) vs pos(2+/3+) {np.mean((pred>=2)==(yv>=2)):.3f}   Spearman {spearmanr(yv, pred).correlation:.3f}")
