"""Evaluate ihcq against the DeepLIIF validation set (CC-BY 4.0, Ghahremani et al. 2022).

Each field is six 512-px panels: IHC | hematoxylin | DAPI | Lap2 | Ki-67 | mask.
The mask marks positive nuclei red and negative nuclei blue, derived from the
multiplex-IF Ki-67 channel — an independent modality, not a re-reading of
the DAB image.  We score the IHC panel and compare:
  * nucleus detection (centroid match within `tol` px): precision / recall
  * positive-vs-negative agreement on matched nuclei
  * per-field Ki-67 index (% positive): error and correlation
Then fit the 0/1+ cut on even-numbered fields and re-evaluate on the odd ones.
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage import measure

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ihcq import Config, analyze
from ihcq.calibrate import fit_to_scores

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("root", nargs="?", default="data/public/deepliif_val/BC-DeepLIIF_Validation_Set")
ap.add_argument("--backend", default="watershed", choices=["watershed", "stardist", "hybrid"])
ap.add_argument("--radius", type=int)
ap.add_argument("--prob", type=float, help="StarDist detection probability threshold (model default ≈0.69)")
args = ap.parse_args()
ROOT = Path(args.root)
OUT = Path("results/deepliif_eval") / (args.backend + (f"_p{args.prob}" if args.prob else "")); OUT.mkdir(parents=True, exist_ok=True)
TOL = 10.0


def gt_nuclei(seg):
    red = (seg[..., 0] == 255) & (seg[..., 1] == 0)
    blue = (seg[..., 2] == 255) & (seg[..., 0] == 0)
    pts, cls = [], []
    for m, c in ((red, 1), (blue, 0)):
        lab = measure.label(m)
        if lab.max():
            for cy, cx in ndi.center_of_mass(m, lab, range(1, lab.max() + 1)):
                pts.append((cy, cx)); cls.append(c)
    return np.array(pts).reshape(-1, 2), np.array(cls)


def evaluate(cfg, files, cache):
    rows, matched_gt, matched_pred = [], [], []
    for f in files:
        im = np.array(Image.open(f).convert("RGB"))
        ihc, seg = im[:, :512], im[:, 5 * 512:6 * 512]
        gpts, gcls = gt_nuclei(seg)
        if f not in cache:
            cache[f] = analyze(ihc, cfg)
        res = cache[f]
        cells = res.cells
        ppts = cells[["y", "x"]].to_numpy() if len(cells) else np.zeros((0, 2))
        pbin = (cells["dab_od"].to_numpy() >= cfg.thresholds.weak).astype(int) if len(cells) else np.zeros(0, int)
        # detection
        tp = 0
        if len(gpts) and len(ppts):
            d, i = cKDTree(ppts).query(gpts)
            ok = d < TOL
            tp = int(ok.sum())
            matched_gt.append(gcls[ok]); matched_pred.append(pbin[i[ok]])
        rec = tp / max(len(gpts), 1); prec = tp / max(len(ppts), 1)
        gt_pos = float(gcls.mean() * 100) if len(gcls) else np.nan
        pr_pos = float(pbin.mean() * 100) if len(pbin) else np.nan
        rows.append({"image": Path(f).name, "gt_cells": len(gpts), "pred_cells": len(ppts), "recall": rec, "precision": prec,
                     "gt_pct_positive": gt_pos, "pred_pct_positive": pr_pos})
    df = pd.DataFrame(rows)
    g = np.concatenate(matched_gt) if matched_gt else np.zeros(0); p = np.concatenate(matched_pred) if matched_pred else np.zeros(0)
    tot_gt, tot_pred = df.gt_cells.sum(), df.pred_cells.sum()
    tp = sum(int((gg.size)) for gg in matched_gt)
    summ = {
        "fields": len(df), "gt_nuclei": int(tot_gt), "pred_nuclei": int(tot_pred),
        "detection_recall": round(tp / max(tot_gt, 1), 3), "detection_precision": round(tp / max(tot_pred, 1), 3),
        "cell_pos_neg_accuracy": round(float((g == p).mean()), 3) if g.size else None,
        "cell_pos_sensitivity": round(float((p[g == 1] == 1).mean()), 3) if (g == 1).any() else None,
        "cell_pos_specificity": round(float((p[g == 0] == 0).mean()), 3) if (g == 0).any() else None,
        "index_mean_abs_err_pp": round(float((df.pred_pct_positive - df.gt_pct_positive).abs().mean()), 2),
        "index_bias_pp": round(float((df.pred_pct_positive - df.gt_pct_positive).mean()), 2),
        "index_pearson_r": round(float(df[["gt_pct_positive", "pred_pct_positive"]].corr().iloc[0, 1]), 3),
    }
    return df, summ


files = sorted(glob.glob(str(ROOT / "*.png")))
cfg0 = Config(backend=args.backend, nucleus_radius_px=args.radius, stardist_prob=args.prob)
cache = {}
df0, s0 = evaluate(cfg0, files, cache)
print("== default thresholds, all fields ==")
for k, v in s0.items(): print(f"  {k:26s} {v}")
df0.to_csv(OUT / "per_field_default.csv", index=False)
import re as _re
df0["field"] = df0.image.str.replace(r"(_\d+)?\.png$", "", regex=True)
print("\n== per distinct field (mean over augmentations) ==")
print(df0.groupby("field")[["gt_cells", "pred_cells", "recall", "precision", "gt_pct_positive", "pred_pct_positive"]].mean().round(2).to_string())

# fit the 0/1+ cut on half the DISTINCT fields, validate on the rest.
# Files come as one original plus flipped/rotated copies (22.png, 22_0.png …);
# splitting by file would leak the same tissue into both halves.
import re
fam = sorted({re.sub(r"(_\d+)?\.png$", "", Path(f).name) for f in files})
fit_fam = set(fam[0::2])
fit_files = [f for f in files if re.sub(r"(_\d+)?\.png$", "", Path(f).name) in fit_fam]
val_files = [f for f in files if f not in fit_files]
print(f"\ndistinct fields: {fam}  → fit on {sorted(fit_fam)}, validate on {sorted(set(fam)-fit_fam)}")
scored = pd.DataFrame({"image": fit_files,
                       "pct_positive": [df0.set_index("image").loc[Path(f).name, "gt_pct_positive"] for f in fit_files]})
cells_od = [cache[f].cells["dab_od"].to_numpy() for f in fit_files]
cfg1, tab = fit_to_scores(scored, cfg0, name="deepliif_ki67", target="pct_positive", cells_od=cells_od, grid_step=0.02)
print(f"\n== fitted 0/1+ cut on {len(fit_files)} fields: weak={cfg1.thresholds.weak} (was {cfg0.thresholds.weak}) ==")
# evaluation on held-out odd fields uses the same segmentation (thresholds don't affect it)
for f in val_files: cache[f].config = cfg1
df1, s1 = evaluate(cfg1, val_files, cache)
_, s0v = evaluate(cfg0, val_files, cache)
print(f"== held-out {len(val_files)} fields: default vs fitted ==")
for k in s0v:
    print(f"  {k:26s} {s0v[k]!s:>10}  →  {s1[k]!s:>10}")
df1.to_csv(OUT / "per_field_heldout_fitted.csv", index=False)
cfg1.to_json(OUT / "deepliif_ki67_profile.json")
pd.DataFrame([{"split": "all/default", **s0}, {"split": "heldout/default", **s0v}, {"split": "heldout/fitted", **s1}]).to_csv(OUT / "summary.csv", index=False)
