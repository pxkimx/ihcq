"""Evaluate membrane (HER2) scoring against the BCI dataset.

BCI (Liu et al., CVPR-W 2022; non-commercial licence) has 4,873 HER2 IHC
patches at 1024×1024 whose filenames carry the slide's HER2 score:
`00012_test_2+.png`.  The score is a slide-level pathologist call inherited
by every patch cut from that slide, so individual patches vary; what a
correct membrane score must show is a monotonic, well-separated trend across
0 / 1+ / 2+ / 3+ and a usable patch-level classifier.

Usage: python scripts/eval_bci.py [--split test] [--n 300] [--backend hybrid] [--mpp 0.5]
"""
import argparse, glob, re, sys, time
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ihcq import Config, analyze
from ihcq.io import load_image

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="data/public/BCI/IHC")
ap.add_argument("--split", default="test")
ap.add_argument("--n", type=int, default=0, help="per-class cap (0 = all)")
ap.add_argument("--backend", default="watershed")
ap.add_argument("--mpp", type=float, default=None)
ap.add_argument("--radius", type=int, default=None)
ap.add_argument("--stat", default="p90", choices=["mean", "median", "p90"])
args = ap.parse_args()

files = sorted(glob.glob(f"{args.root}/{args.split}/*.png"))
lab = {f: re.search(r"_(0|1\+|2\+|3\+)\.png$", f).group(1) for f in files if re.search(r"_(0|1\+|2\+|3\+)\.png$", f)}
if args.n:
    keep = []
    for c in ("0", "1+", "2+", "3+"):
        keep += [f for f in files if lab.get(f) == c][: args.n]
    files = keep
print(f"{len(files)} {args.split} patches; per class:", pd.Series([lab[f] for f in files]).value_counts().sort_index().to_dict())

cfg = Config(backend=args.backend, compartment="membrane", cell_statistic=args.stat, mpp=args.mpp, nucleus_radius_px=args.radius)
rows, t0 = [], time.time()
for i, f in enumerate(files):
    try:
        s = analyze(load_image(f), cfg).summary
    except Exception as e:
        print("  !", f, e); continue
    rows.append({"image": Path(f).name, "her2": lab[f], **{k: s.get(k) for k in (
        "n_cells", "pct_positive", "pct_1plus", "pct_2plus", "pct_3plus", "h_score", "mean_cell_dab_od",
        "dab_area_fraction_pct", "mean_dab_od_tissue", "p95_dab_od_tissue", "integrated_dab_od", "second_stain", "scores_valid", "dab_in_nuclei_fraction")}})
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(files)}  {time.time()-t0:.0f}s", flush=True)
df = pd.DataFrame(rows)
out = Path("results/bci"); out.mkdir(parents=True, exist_ok=True)
df.to_csv(out / f"per_patch_{args.split}_{args.backend}_{args.stat}.csv", index=False)

order = {"0": 0, "1+": 1, "2+": 2, "3+": 3}
df["her2_ord"] = df.her2.map(order)
df["pct_2plus_or_more"] = df.pct_2plus + df.pct_3plus
metrics = ["pct_positive", "pct_2plus_or_more", "pct_3plus", "h_score", "mean_cell_dab_od", "dab_area_fraction_pct", "mean_dab_od_tissue"]
print("\n== per HER2 class: median (IQR) ==")
g = df.groupby("her2")[metrics]
med = g.median().round(2); q1 = g.quantile(.25).round(2); q3 = g.quantile(.75).round(2)
print(med.to_string())
print("\n== Spearman rho vs HER2 class ==")
from scipy.stats import spearmanr
for m in metrics:
    rho = spearmanr(df["her2_ord"], df[m], nan_policy="omit").correlation
    print(f"  {m:24s} rho = {rho:.3f}")
print("\n== stain check ==", df.second_stain.value_counts().to_dict(), "| scores_valid:", df.scores_valid.mean().round(3))

# a transparent ASCO/CAP-flavoured patch classifier on the two most informative numbers,
# thresholds chosen on this split (report as such): 3+ if strong-complete-ish (pct_3plus high),
# 0 if almost nothing stains; in between by pct_2plus_or_more.
best, best_acc = None, 0
for t3 in np.arange(5, 60, 5):
    for t2 in np.arange(5, 60, 5):
        for t1 in np.arange(1, 20, 2):
            pred = np.where(df.pct_3plus >= t3, 3, np.where(df.pct_2plus_or_more >= t2, 2, np.where(df.pct_positive >= t1, 1, 0)))
            acc = (pred == df.her2_ord).mean()
            if acc > best_acc: best, best_acc = (t1, t2, t3), acc
t1, t2, t3 = best
pred = np.where(df.pct_3plus >= t3, 3, np.where(df.pct_2plus_or_more >= t2, 2, np.where(df.pct_positive >= t1, 1, 0)))
cm = pd.crosstab(df.her2, pd.Series(pred).map({v: k for k, v in order.items()}).values, rownames=["truth"], colnames=["pred"])
print(f"\n== patch classifier (thresholds fitted on this split: 1+ if %pos≥{t1}, 2+ if %≥2+ ≥{t2}, 3+ if %3+ ≥{t3}) ==")
print(cm.to_string()); print(f"exact accuracy {best_acc:.3f}   within-one-grade {(np.abs(pred - df.her2_ord) <= 1).mean():.3f}   HER2-negative(0/1+) vs 2+/3+: {((pred>=2)==(df.her2_ord>=2)).mean():.3f}")
