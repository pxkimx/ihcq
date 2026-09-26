"""Calibrate and validate HER2 membrane scoring on BCI (977 test patches, slide-level 0/1+/2+/3+).

Stage 1 caches per-cell membrane sector peaks and tumour probability for every patch (parallel).
Stage 2 fits (weak, moderate, strong, complete_frac, population) on even patches by balanced
accuracy, and reports the held-out odd patches — alongside the previous p90-ring method.
"""
import glob, re, sys, time
from itertools import product
from multiprocessing import Pool
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = "data/public/BCI/BCI_dataset/IHC/test"
CACHE = Path("results/bci/her2_cache.npz")
ORD = {"0": 0, "1+": 1, "2+": 2, "3+": 3}


def one(f):
    import warnings; warnings.filterwarnings("ignore")
    from ihcq import Config, analyze
    from ihcq.io import load_image
    r = analyze(load_image(f), Config(compartment="membrane", cell_statistic="p90"))
    e = r.extra
    if "peaks" not in e: return f, None
    return f, (e["peaks"].astype(np.float16), e["has"], e["tumour_p"].astype(np.float16), bool(e["tumour_info"].get("separated")))


def build():
    files = sorted(glob.glob(f"{ROOT}/*.png")); t = time.time()
    with Pool(8) as p:
        out = []
        for i, res in enumerate(p.imap(one, files, chunksize=4), 1):
            out.append(res)
            if i % 100 == 0: print(f"  {i}/{len(files)} {time.time()-t:.0f}s", flush=True)
    names = [Path(f).name for f, _ in out]; data = [d for _, d in out]
    np.savez_compressed(CACHE, names=np.array(names), data=np.array(data, dtype=object), allow_pickle=True)


def main():
    if not CACHE.exists(): build()
    z = np.load(CACHE, allow_pickle=True); names, data = list(z["names"]), list(z["data"])
    y = np.array([ORD[re.search(r"_(0|1\+|2\+|3\+)\.png$", n).group(1)] for n in names])
    ok = np.array([d is not None and len(d[0]) > 0 for d in data]); print(f"{ok.sum()} / {len(ok)} patches with cells")
    sorted_ = []  # per patch: per-cell sorted sector peaks descending among usable sectors → completeness at any cut is cheap
    for d in data:
        if d is None or not len(d[0]): sorted_.append(None); continue
        pk = d[0].astype(np.float32); has = d[1]; pk = np.where(has, pk, -1)
        sorted_.append((np.sort(pk, 1)[:, ::-1], has.sum(1), d[2].astype(np.float32), d[3]))

    def score(i, w, m, s, cf, pop):
        d = sorted_[i]
        if d is None: return 0
        srt, usable, tp, sep = d
        if pop == "tumour" and sep: keep = tp > 0.5
        else: keep = np.ones(len(tp), bool)
        if keep.sum() < 20: keep = np.ones(len(tp), bool)
        srt, usable = srt[keep], usable[keep]
        ns = (srt >= w).sum(1); comp = ns / np.maximum(usable, 1)
        # membrane OD = median over stained sectors ≈ value at index ns//2 of the descending sort
        mod = np.where(ns > 0, srt[np.arange(len(srt)), np.maximum(ns // 2, 0)], 0)
        cls = np.where(ns == 0, 0, np.where((comp >= cf) & (usable >= 8), 2, 1))
        cs = ((cls == 2) & (mod >= s)).mean() * 100; ca = (cls == 2).mean() * 100; im = ((cls == 1) & (mod >= m)).mean() * 100; an = (cls > 0).mean() * 100
        return 3 if cs > 10 else 2 if (ca > 10 or im > 10) else 1 if an > 10 else 0

    def bal(p, t): return float(np.mean([(p[t == k] == k).mean() for k in range(4) if (t == k).any()]))
    fit, val = np.arange(0, len(y), 2), np.arange(1, len(y), 2)
    grid_w = [0.08, 0.12, 0.16, 0.20, 0.25]; grid_s = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]; grid_cf = [0.5, 0.6, 0.7, 0.8, 0.9]
    best, bb = None, -1; t = time.time()
    for w, s, cf, pop in product(grid_w, grid_s, grid_cf, ("all", "tumour")):
        for m in sorted({round(w + (s - w) * 0.4, 3), round(w + (s - w) * 0.6, 3)}):
            if not (w < m < s): continue
            p = np.array([score(i, w, m, s, cf, pop) for i in fit]); b = bal(p, y[fit])
            if b > bb: best, bb = (w, m, s, cf, pop), b
    print(f"grid search {time.time()-t:.0f}s; best on fit half: weak={best[0]} moderate={best[1]} strong={best[2]} complete_frac={best[3]} population={best[4]}  balanced={bb:.3f}")
    from scipy.stats import spearmanr
    for name, par in (("default 0.15/0.40/0.80 cf0.8 all", (0.15, 0.40, 0.80, 0.8, "all")), ("default, tumour only", (0.15, 0.40, 0.80, 0.8, "tumour")), ("fitted", best)):
        p = np.array([score(i, *par) for i in val]); t_ = y[val]
        cm = pd.crosstab(pd.Series(t_, name="truth"), pd.Series(p, name="pred")).reindex(index=range(4), columns=range(4), fill_value=0)
        print(f"\n== held-out odd patches · {name} ==\n{cm.to_string()}")
        print(f"balanced {bal(p, t_):.3f}  exact {np.mean(p == t_):.3f}  within-one {np.mean(np.abs(p - t_) <= 1):.3f}  neg(0/1+) vs pos(2+/3+) {np.mean((p >= 2) == (t_ >= 2)):.3f}  Spearman {spearmanr(t_, p).correlation:.3f}")
    print("\n(previous method, p90 ring % cells, fitted cut points: held-out balanced 0.476, exact 0.430, neg-vs-pos 0.600)")


if __name__ == "__main__":
    main()
