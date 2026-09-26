"""One image in, one fully-specified result out."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time

import numpy as np
import pandas as pd

from .config import Config
from .stains import stain_matrix, find_white, deconvolve, identify_second_stain
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
    extra: dict = field(default_factory=dict)       # per-nucleus arrays indexed by original label - 1


def _qc_flags(summary: dict, cfg: Config) -> list:
    flags = []
    st = summary.get("second_stain")
    if st == "eosin":
        flags.append("second stain is eosin — this looks like H&E, not DAB IHC: positivity, H-score and DAB area are NOT meaningful here; nuclear counts, density and size still are")
    elif st == "unknown" and summary.get("dab_area_fraction_pct", 0) > 2:
        flags.append("second stain matches neither DAB nor eosin (melanin? a red chromogen?) — check the stain-separation overlay before trusting DAB scores")
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
    if f is not None and cfg.compartment in ("membrane", "cytoplasm") and f > 0.75:
        flags.append(f"{f*100:.0f}% of DAB+ pixels lie inside nuclei — a nuclear stain scored in a {cfg.compartment} ring")
    r_est, r_used = summary.get("median_nucleus_radius_px"), summary.get("assumed_nucleus_radius_px")
    if r_est and r_used and (r_est < 0.55 * r_used or r_est > 1.8 * r_used):
        flags.append(f"detected nuclei have median radius {r_est} px against an assumed {r_used} px — set --mpp or --radius")
    if summary.get("white_point_source") == "default":
        flags.append("no bare glass in the field — white point assumed (245); pass --white from a blank area of this slide")
    if cfg.tumour_only and summary.get("tumour_separated") is False:
        flags.append("tumour-only scoring requested but tumour and stroma nuclei did not separate — all cells were scored; draw a tumour ROI instead")
    if cfg.compartment == "membrane" and summary.get("her2_score") and summary.get("scored_population") == "all cells":
        flags.append("HER2 score is over all cells, stroma included — enable tumour-only scoring or draw a tumour ROI (ASCO/CAP scores tumour cells)")
    if cfg.profile_name == "default":
        flags.append("default intensity thresholds in use — calibrate before reporting")
    return flags


def cell_annotations(labels, hema, dab, tissue, cfg: Config) -> dict:
    """Per-nucleus arrays computed once on the full field: tumour likelihood
    (always) and membrane sector peaks (membrane compartment)."""
    from .tumour import tumour_probability
    from .her2 import sector_profile
    extra = {}
    if labels.max() == 0:
        return extra
    p, info = tumour_probability(labels, hema)
    extra["tumour_p"], extra["tumour_info"] = p, info
    if cfg.compartment == "membrane":
        expand = cfg.cell_expand_px or max(4, int(round(1.2 * assumed_radius(cfg))))
        extra["peaks"], extra["has"] = sector_profile(labels, dab, tissue, expand)
        extra["expand_px"] = expand
    return extra


def enrich_cells(cells: pd.DataFrame, extra: dict, ids: np.ndarray, cfg: Config) -> pd.DataFrame:
    """Add tumour and membrane columns to a cell table whose rows are original label ids `ids`."""
    if not len(cells) or not extra:
        return cells
    cells = cells.copy()
    ids = np.asarray(ids, dtype=np.int64) - 1
    if "tumour_p" in extra:
        cells["tumour_p"] = np.round(extra["tumour_p"][ids], 3)
        cells["tumour_like"] = cells["tumour_p"] > 0.5
    if "peaks" in extra:
        from .her2 import membrane_calls
        comp, mod, cls = membrane_calls(extra["peaks"][ids], extra["has"][ids], cfg.thresholds, cfg.membrane_complete_frac)
        cells["completeness"] = np.round(comp, 3); cells["membrane_od"] = np.round(mod, 3); cells["membrane_class"] = cls
    return cells


def score_cells(cells: pd.DataFrame, tissue_px: int, cfg: Config, extra: dict) -> dict:
    """Cell-level summary over the chosen population, plus HER2 when membrane calls exist."""
    info = extra.get("tumour_info", {})
    use_tumour = cfg.tumour_only and "tumour_like" in cells and info.get("separated")
    sub = cells[cells["tumour_like"]].reset_index(drop=True) if use_tumour else cells
    out = cell_summary(sub, tissue_px, cfg.mpp)
    out["scored_population"] = "tumour-like cells" if use_tumour else "all cells"
    if "tumour_like" in cells and len(cells):
        out["tumour_like_fraction"] = round(float(cells["tumour_like"].mean()), 3) if info.get("separated") else None
        out["tumour_separated"] = bool(info.get("separated"))
    if "membrane_class" in sub:
        from .her2 import her2_summary
        out.update(her2_summary(sub["completeness"].to_numpy(), sub["membrane_od"].to_numpy(), sub["membrane_class"].to_numpy(), cfg.thresholds))
    return out


def analyze(rgb: np.ndarray, cfg: Config | None = None) -> Result:
    cfg = (cfg or Config()).validate()
    t0 = time.time()
    matrix = stain_matrix(cfg.stains, cfg.stain_vectors)
    if cfg.fit_stains and not cfg.stain_vectors:
        from .stains import estimate_stain_vectors
        try:
            matrix = estimate_stain_vectors(rgb)
        except ValueError:
            pass  # not enough stained pixels — keep the textbook vectors
    if cfg.white_point:
        white, white_src = np.asarray(cfg.white_point, dtype=np.float64), "config"
    else:
        white, found = find_white(rgb)
        white_src = "glass" if found else "default"
    conc = deconvolve(rgb, matrix, white).astype(np.float32)
    hema, dab = conc[..., 0], conc[..., 1]
    tissue = tissue_mask(conc.sum(-1), cfg.tissue_od_threshold, cfg.tissue_min_size_px, smooth_sigma=cfg.tissue_smooth_sigma)

    ident = identify_second_stain(rgb, white)
    summary = {
        "height": rgb.shape[0], "width": rgb.shape[1],
        "second_stain": ident["stain"], "second_stain_angle_to_dab": ident["angle_to_dab"], "second_stain_angle_to_eosin": ident["angle_to_eosin"],
        "white_point": [round(float(v), 1) for v in white], "white_point_source": white_src,
        "saturated_fraction": round(saturation_fraction(rgb, tissue), 4),
    }
    summary.update(pixel_summary(dab, hema, tissue, cfg.thresholds, cfg.pixel_positive_od, cfg.mpp))

    labels = np.zeros(rgb.shape[:2], dtype=np.int32)
    score_labels = labels
    cells = pd.DataFrame()
    extra = {}
    if cfg.segment:
        labels = segment_nuclei(rgb, conc, tissue, cfg)
        score_labels = compartment_masks(labels, cfg.compartment, cfg.ring_px)
        cells = per_cell_table(labels, score_labels, dab, hema, cfg.thresholds, cfg.cell_statistic, cfg.mpp)
        extra = cell_annotations(labels, hema, dab, tissue, cfg)
        cells = enrich_cells(cells, extra, np.arange(1, int(labels.max()) + 1), cfg)
        summary.update(score_cells(cells, int(tissue.sum()), cfg, extra))
        # where does the chromogen actually sit?  Guides the compartment choice.
        pos_px = tissue & (dab >= (cfg.pixel_positive_od or cfg.thresholds.weak))
        summary["dab_in_nuclei_fraction"] = round(float((labels[pos_px] > 0).mean()), 3) if pos_px.any() else None
        est = _median_radius(labels)
        if cfg.compartment != "nuclear":
            from .nuclei import crosstalk_k
            summary["hema_crosstalk_k"] = round(crosstalk_k(conc), 3)
        summary["assumed_nucleus_radius_px"] = assumed_radius(cfg)
        summary["median_nucleus_radius_px"] = round(est, 1) if est else None
        # nuclear morphology — meaningful on any hematoxylin-stained section, H&E included
        if len(cells):
            summary["mean_nucleus_area_px"] = round(float(cells["area_px"].mean()), 1)
            summary["nuclear_area_fraction_pct"] = round(float((labels > 0)[tissue].mean() * 100), 2)
            summary["mean_nucleus_hema_od"] = round(float(cells["hema_od"].mean()), 4)
            if cfg.mpp:
                summary["mean_nucleus_area_um2"] = round(float(cells["area_px"].mean()) * cfg.mpp ** 2, 2)

    summary["stain_vectors_used"] = [[round(float(v), 3) for v in matrix[0]], [round(float(v), 3) for v in matrix[1]]]
    summary.update({
        "thr_weak": cfg.thresholds.weak, "thr_moderate": cfg.thresholds.moderate, "thr_strong": cfg.thresholds.strong,
        "compartment": cfg.compartment, "cell_statistic": cfg.cell_statistic, "profile": cfg.profile_name,
        "seconds": round(time.time() - t0, 2),
    })
    # DAB-derived scores are only meaningful when the chromogen really is DAB
    summary["scores_valid"] = not (summary["second_stain"] == "eosin" or
                                   (summary["second_stain"] == "unknown" and (summary.get("dab_area_fraction_pct") or 0) > 2))
    res = Result(summary, cells, conc, tissue, labels, score_labels, matrix, white, cfg, extra=extra)
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
        if res.config.mpp: img = ov.scale_bar(img, res.config.mpp)
        cap = (f"{stem}  cells={s['n_cells']}  H={s['h_score']}  +={s['pct_positive']}%  "
               f"[0 blue | 1+ yellow | 2+ orange | 3+ red]  thr={s['thr_weak']}/{s['thr_moderate']}/{s['thr_strong']}")
        p = out_dir / f"{stem}_cells.png"; ov.save(ov.with_caption(img, cap), p); paths["cells"] = p
    pm = ov.positivity_map(res.conc[..., 1], res.tissue, res.config.thresholds)
    if res.config.mpp: pm = ov.scale_bar(pm, res.config.mpp)
    cap = f"{stem}  DAB area fraction={s['dab_area_fraction_pct']}%  pixel-H={s['pixel_h_score']}  mean OD={s['mean_dab_od_tissue']}"
    p = out_dir / f"{stem}_positivity.png"; ov.save(ov.with_caption(pm, cap), p); paths["positivity"] = p
    sp = ov.stain_panels(rgb, res.conc, res.matrix, res.white)
    p = out_dir / f"{stem}_stains.png"; ov.save(ov.with_caption(sp, f"{stem}  original | hematoxylin | DAB"), p); paths["stains"] = p
    from .stains import reconstruct
    p = out_dir / f"{stem}_hematoxylin.png"; ov.save(reconstruct(res.conc, res.matrix, 0, res.white), p); paths["hematoxylin"] = p
    p = out_dir / f"{stem}_dab.png"; ov.save(reconstruct(res.conc, res.matrix, 1, res.white), p); paths["dab"] = p
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
