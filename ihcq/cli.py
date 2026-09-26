"""Command line.

  ihcq score IMG [IMG ...] -o results.csv --overlays qc/ [--profile p.json]
  ihcq calibrate --negative a.png --weak b.png --moderate c.png --strong d.png -o profile.json
  ihcq inspect IMG                 # OD histogram and white point, to sanity-check thresholds
  ihcq demo -o demo/               # synthetic slides with known truth, scored end to end
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config


def _cfg_from_args(a) -> Config:
    cfg = Config.from_json(a.profile) if getattr(a, "profile", None) else Config()
    for k in ("compartment", "cell_statistic", "backend", "segment_on"):
        v = getattr(a, k, None)
        if v:
            setattr(cfg, k, v)
    if getattr(a, "mpp", None):
        cfg.mpp = a.mpp
    if getattr(a, "no_segment", False):
        cfg.segment = False
    if getattr(a, "thresholds", None):
        w, m, s = a.thresholds
        cfg.thresholds.weak, cfg.thresholds.moderate, cfg.thresholds.strong = w, m, s
        cfg.profile_name = "cli-thresholds"
    return cfg.validate()


def cmd_score(a):
    from .pipeline import analyze_file
    cfg = _cfg_from_args(a)
    rows = []
    for p in a.images:
        try:
            res = analyze_file(p, cfg, overlay_dir=a.overlays, cells_dir=a.cells_dir, max_side=a.max_side)
        except Exception as e:  # keep going through a folder; report the failure in the table
            print(f"  ! {p}: {e}", file=sys.stderr)
            rows.append({"image": Path(p).name, "error": str(e)})
            continue
        s = res.summary
        rows.append(s)
        hs = s.get("h_score")
        print(f"  {s['image']:40s} cells={s.get('n_cells','-'):>5}  H={hs if hs is not None else '-':>6}  "
              f"+cells={s.get('pct_positive','-')}%  DAB area={s['dab_area_fraction_pct']}%  "
              + ("  ⚠ " + "; ".join(res.qc) if res.qc else ""))
    df = pd.DataFrame(rows)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    cfg.to_json(out.with_suffix(".config.json"))
    print(f"\nwrote {out}  ({len(df)} rows) and {out.with_suffix('.config.json')}")


def cmd_calibrate(a):
    from .calibrate import calibrate, fit_to_scores
    base = Config.from_json(a.profile) if a.profile else Config()
    for k in ("compartment", "segment_on"):
        if getattr(a, k, None):
            setattr(base, k, getattr(a, k))
    if a.scored:
        scored = pd.read_csv(a.scored)
        if not {"image", "h_score"} <= set(scored.columns):
            sys.exit("--scored CSV needs columns: image, h_score")
        cfg, table = fit_to_scores(scored, base, name=Path(a.output).stem, image_root=Path(a.scored).parent)
        print(table.to_string(index=False))
        print(f"\nmean |error| = {table['abs_error'].mean():.1f} H-score units over {len(table)} images")
    else:
        groups = {c: getattr(a, c) or [] for c in ("negative", "weak", "moderate", "strong")}
        if not any(groups.values()):
            sys.exit("give control images with --negative/--weak/--moderate/--strong, or --scored scores.csv")
        cfg, table = calibrate(groups, base, estimate_stains=a.estimate_stains, name=Path(a.output).stem)
        print(table.to_string(index=False))
    print(f"\nthresholds  weak={cfg.thresholds.weak}  moderate={cfg.thresholds.moderate}  strong={cfg.thresholds.strong}")
    if cfg.stain_vectors:
        print(f"stain vectors  hema={np.round(cfg.stain_vectors[0],3).tolist()}  dab={np.round(cfg.stain_vectors[1],3).tolist()}")
    cfg.to_json(a.output)
    print(f"wrote {a.output}")


def cmd_inspect(a):
    from .io import load_image
    from .stains import estimate_white, stain_matrix, deconvolve
    from .tissue import tissue_mask
    rgb = load_image(a.image, max_side=a.max_side)
    white = estimate_white(rgb)
    conc = deconvolve(rgb, stain_matrix(), white)
    tissue = tissue_mask(conc.sum(-1))
    dab = conc[..., 1][tissue]
    print(f"{a.image}: {rgb.shape[1]}×{rgb.shape[0]}  white point RGB={np.round(white,1).tolist()}  tissue={tissue.mean()*100:.1f}%")
    print("DAB OD over tissue percentiles:")
    for q in (50, 75, 90, 95, 99, 99.9):
        print(f"  p{q:<5} {np.percentile(dab, q):.3f}")
    hist, edges = np.histogram(dab, bins=np.arange(0, 1.6, 0.1))
    top = hist.max() or 1
    for h, e in zip(hist, edges):
        print(f"  {e:4.1f}–{e+0.1:3.1f} {'█' * int(40 * h / top):40s} {h}")
    print("\nIf almost everything sits below 0.15 the field is negative; bins 1+/2+/3+ should each hold a visible shoulder on a positive control.")


def cmd_demo(a):
    from .synth import make_field
    from .pipeline import analyze, write_overlays
    from PIL import Image
    out = Path(a.output); out.mkdir(parents=True, exist_ok=True)
    designs = [("neg_control", (1.0, 0, 0, 0)), ("low", (0.75, 0.15, 0.08, 0.02)),
               ("mixed", (0.4, 0.2, 0.25, 0.15)), ("high", (0.1, 0.1, 0.3, 0.5))]
    cfg = Config(profile_name="demo")
    rows = []
    for i, (name, fr) in enumerate(designs):
        rgb, truth, ts, _ = make_field(n_cells=a.cells, fractions=fr, seed=i)
        Image.fromarray(rgb).save(out / f"{name}.png")
        truth.to_csv(out / f"{name}_truth_cells.csv", index=False)
        res = analyze(rgb, cfg)
        write_overlays(rgb, res, out / "qc", name)
        s = res.summary
        rows.append({"image": name, "true_cells": ts["true_n_cells"], "found_cells": s["n_cells"],
                     "true_H": ts["true_h_score"], "H": s["h_score"], "true_pos%": ts["true_pct_positive"],
                     "pos%": s["pct_positive"], "true_allred": ts["true_allred_total"], "allred": s["allred_total"],
                     "DAB_area%": s["dab_area_fraction_pct"]})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    df.to_csv(out / "demo_results.csv", index=False)
    print(f"\nimages, truth tables and QC overlays in {out}/")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ihcq", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="score one or more images")
    s.add_argument("images", nargs="+")
    s.add_argument("-o", "--output", default="ihcq_results.csv")
    s.add_argument("--overlays", help="directory for QC overlay PNGs")
    s.add_argument("--cells-dir", help="directory for per-cell CSVs")
    s.add_argument("--profile", help="calibration profile JSON from `ihcq calibrate`")
    s.add_argument("--thresholds", nargs=3, type=float, metavar=("WEAK", "MOD", "STRONG"))
    s.add_argument("--compartment", choices=["nuclear", "membrane", "cytoplasm"])
    s.add_argument("--cell-statistic", dest="cell_statistic", choices=["mean", "median", "p90"])
    s.add_argument("--segment-on", dest="segment_on", choices=["hema", "hema+dab", "gray"])
    s.add_argument("--backend", choices=["watershed", "stardist"])
    s.add_argument("--mpp", type=float, help="microns per pixel (enables µm² and per-mm² outputs)")
    s.add_argument("--no-segment", action="store_true", help="pixel metrics only")
    s.add_argument("--max-side", type=int, help="for pyramidal TIFFs: read the level near this size")
    s.set_defaults(func=cmd_score)

    c = sub.add_parser("calibrate", help="fit intensity thresholds from control images")
    for cat in ("negative", "weak", "moderate", "strong"):
        c.add_argument(f"--{cat}", nargs="+")
    c.add_argument("--scored", help="CSV with columns image,h_score — fit thresholds to pathologist scores")
    c.add_argument("-o", "--output", default="profile.json")
    c.add_argument("--profile", help="start from an existing profile")
    c.add_argument("--compartment", choices=["nuclear", "membrane", "cytoplasm"])
    c.add_argument("--segment-on", dest="segment_on", choices=["hema", "hema+dab", "gray"])
    c.add_argument("--estimate-stains", action="store_true", help="also fit stain vectors (Macenko) from the controls")
    c.set_defaults(func=cmd_calibrate)

    i = sub.add_parser("inspect", help="OD histogram and white point for one image")
    i.add_argument("image")
    i.add_argument("--max-side", type=int)
    i.set_defaults(func=cmd_inspect)

    d = sub.add_parser("demo", help="generate and score synthetic slides with known truth")
    d.add_argument("-o", "--output", default="ihcq_demo")
    d.add_argument("--cells", type=int, default=400)
    d.set_defaults(func=cmd_demo)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
