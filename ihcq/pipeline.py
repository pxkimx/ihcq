"""One image in, one fully-specified result out."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time

import numpy as np
import pandas as pd

from .config import Config
from .stains import stain_matrix, find_white, deconvolve
from .tissue import tissue_mask, saturation_fraction
from .nuclei import segment_nuclei, compartment_masks, assumed_radius, _median_radius
from .metrics import per_cell_table, cell_summary, pixel_summary
from . import overlay as ov


@dataclass
class Result:
    summary: dict
    cells: pd.DataFrame
    conc: np.ndarray
    tissue: np.ndarray
    labels: np.ndarray
    score_labels: np.ndarray
    matrix: np.ndarray
    white: np.ndarray
    config: Config
    qc: list = field(default_factory=list)


def _qc_flags(summary: dict, cfg: Config) -> list:
    flags = []
    if summary["saturated_fraction"] > 0.02:
        flags.append(f"{summary['saturated_fraction']*100:.1f}% of tissue pixels clipped — over-exposed scan; OD unreliable")
    if summary["tissue_fraction"] < 0.05:
        flags.append("under 5% of the field is tissue — scores rest on very little material")
    if cfg.segment and summary.get("n_cells") is not None and summary["n_cells"] < 100:
        flags.append(f"only {summary['n_cells']} cells — H-score has wide confidence bounds below ~200 cells")
    if summary.get("mean_dab_od_tissue") and summary["mean_dab_od_tissue"] > 1.2:
        flags.append("mean DAB OD > 1.2 across tissue — chromogen may be saturated; bins compress at the top")
    f = summary.get("dab_in_nuclei_fraction")
    if f is not None and cfg.compartment == "nuclear" and f < 0.35 and summary.get("dab_area_fraction_pct", 0) > 2:
        flags.append(f"only {f*100:.0f}% of DAB+ pixels lie inside nuclei — a membranous/cytoplasmic stain? try --compartment membrane")
    if f is not None and cfg.compartment != "nuclear" and f > 0.75:
        flags.append(f"{f*100:.0f}% of DAB+ pixels lie inside nuclei — a nuclear stain scored in a {cfg.compartment} ring")
    r_est, r_used = summary.get("median_nucleus_radius_px"), summary.get("assumed_nucleus_radius_px")
    if r_est and r_used and (r_est < 0.55 * r_used or r_est > 1.8 * r_used):
        flags.append(f"detected nuclei have median radius {r_est} px against an assumed {r_used} px — set --mpp or --radius")
    if summary.get("white_point_source") == "default":
        flags.append("no bare glass in the field — white point assumed (245); pass --white from a blank area of this slide")
    if cfg.profile_name == "default":
        flags.append("default intensity thresholds in use — calibrate before reporting")
    return flags


def analyze(rgb: np.ndarray, cfg: Config | None = None) -> Result:
    cfg = (cfg or Config()).validate()
    t0 = time.time()
    matrix = stain_matrix(cfg.stains, cfg.stain_vectors)
    if cfg.white_point:
        white, white_src = np.asarray(cfg.white_point, dtype=np.float64), "config"
    else:
        white, found = find_white(rgb)
        white_src = "glass" if found else "default"
    conc = deconvolve(rgb, matrix, white).astype(np.float32)
    hema, dab = conc[..., 0], conc[..., 1]
    tissue = tissue_mask(conc.sum(-1), cfg.tissue_od_threshold, cfg.tissue_min_size_px, smooth_sigma=cfg.tissue_smooth_sigma)

    summary = {
        "height": rgb.shape[0], "width": rgb.shape[1],
        "white_point": [round(float(v), 1) for v in white], "white_point_source": white_src,
        "saturated_fraction": round(saturation_fraction(rgb, tissue), 4),
    }
    summary.update(pixel_summary(dab, hema, tissue, cfg.thresholds, cfg.pixel_positive_od, cfg.mpp))

    labels = np.zeros(rgb.shape[:2], dtype=np.int32)
    score_labels = labels
    cells = pd.DataFrame()
    if cfg.segment:
        labels = segment_nuclei(rgb, conc, tissue, cfg)
        score_labels = compartment_masks(labels, cfg.compartment, cfg.ring_px)
        cells = per_cell_table(labels, score_labels, dab, hema, cfg.thresholds, cfg.cell_statistic, cfg.mpp)
        summary.update(cell_summary(cells, int(tissue.sum()), cfg.mpp))
        # where does the chromogen actually sit?  Guides the compartment choice.
        pos_px = tissue & (dab >= (cfg.pixel_positive_od or cfg.thresholds.weak))
        summary["dab_in_nuclei_fraction"] = round(float((labels[pos_px] > 0).mean()), 3) if pos_px.any() else None
        est = _median_radius(labels)
        summary["assumed_nucleus_radius_px"] = assumed_radius(cfg)
        summary["median_nucleus_radius_px"] = round(est, 1) if est else None

    summary.update({
        "thr_weak": cfg.thresholds.weak, "thr_moderate": cfg.thresholds.moderate, "thr_strong": cfg.thresholds.strong,
        "compartment": cfg.compartment, "cell_statistic": cfg.cell_statistic, "profile": cfg.profile_name,
        "seconds": round(time.time() - t0, 2),
    })
    res = Result(summary, cells, conc, tissue, labels, score_labels, matrix, white, cfg)
    res.qc = _qc_flags(summary, cfg)
    summary["qc_flags"] = " | ".join(res.qc)
    return res


def write_overlays(rgb: np.ndarray, res: Result, out_dir, stem: str) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    s = res.summary
    paths = {}
    if res.config.segment and len(res.cells):
        bins = dict(zip(res.cells["cell"].astype(int), res.cells["bin"].astype(int)))
        img = ov.cell_overlay(rgb, res.labels, bins, res.tissue, res.score_labels)
        cap = (f"{stem}  cells={s['n_cells']}  H={s['h_score']}  +={s['pct_positive']}%  "
               f"[0 blue | 1+ yellow | 2+ orange | 3+ red]  thr={s['thr_weak']}/{s['thr_moderate']}/{s['thr_strong']}")
        p = out_dir / f"{stem}_cells.png"; ov.save(ov.with_caption(img, cap), p); paths["cells"] = p
    pm = ov.positivity_map(res.conc[..., 1], res.tissue, res.config.thresholds)
    cap = f"{stem}  DAB area fraction={s['dab_area_fraction_pct']}%  pixel-H={s['pixel_h_score']}  mean OD={s['mean_dab_od_tissue']}"
    p = out_dir / f"{stem}_positivity.png"; ov.save(ov.with_caption(pm, cap), p); paths["positivity"] = p
    sp = ov.stain_panels(rgb, res.conc, res.matrix, res.white)
    p = out_dir / f"{stem}_stains.png"; ov.save(ov.with_caption(sp, f"{stem}  original | hematoxylin | DAB"), p); paths["stains"] = p
    return paths


def analyze_file(path, cfg: Config | None = None, overlay_dir=None, cells_dir=None, max_side=None) -> Result:
    from .io import load_image
    path = Path(path)
    rgb = load_image(path, max_side=max_side)
    res = analyze(rgb, cfg)
    res.summary = {"image": path.name, **res.summary}
    if overlay_dir:
        write_overlays(rgb, res, overlay_dir, path.stem)
    if cells_dir and len(res.cells):
        Path(cells_dir).mkdir(parents=True, exist_ok=True)
        res.cells.to_csv(Path(cells_dir) / f"{path.stem}_cells.csv", index=False)
    return res
