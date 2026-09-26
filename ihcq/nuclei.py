"""Nucleus segmentation.

The default backend is a classical hematoxylin-driven watershed: no model
download, no GPU, and good enough for round nuclei at 20–40×.  The optional
StarDist backend (`pip install ihcq[dl]`) is markedly better on crowded or
irregular nuclei; the rest of the pipeline is identical either way.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from skimage import filters, morphology, segmentation, feature, measure

from .config import Config
from .tissue import remove_small


def segmentation_channel(conc: np.ndarray, rgb: np.ndarray, how: str) -> np.ndarray:
    """Which signal nuclei are found in.

    `hema` (and the default `auto`, which starts from it) uses the
    counterstain, which every nucleus carries.  `hema+dab` sums both stains;
    on real slides Otsu then locks onto the DAB level and pale negative
    nuclei vanish, inflating positivity — keep it for the rare stain where
    the counterstain is truly absent from positive nuclei.
    """
    if how in ("hema", "auto"):
        return conc[..., 0]
    if how == "hema+dab":
        return conc[..., 0] + conc[..., 1]
    od_gray = -np.log10(np.clip(rgb.mean(-1) + 1, 1, None) / 256.0)
    return od_gray


def segment_watershed(chan: np.ndarray, tissue: np.ndarray, cfg: Config, exclude: np.ndarray | None = None,
                      radius: int | None = None, max_area: int | None = None) -> np.ndarray:
    """Background-flattened threshold + distance-transform watershed.

    Nuclei are detected as *local* blobs: the channel is flattened by
    subtracting a wide Gaussian (about three nuclear radii), so a faintly
    counterstained nucleus on a tinted field is still a peak even when its
    absolute OD barely exceeds the background's.

    `exclude` marks pixels to leave OUT of the threshold estimate.  DAB
    leaks into the deconvolved hematoxylin channel whenever the textbook
    stain vectors don't quite match the slide; with those pixels in the
    sample Otsu splits "brown vs everything" and the pale negative nuclei
    fall below the cut, which inflates positivity.
    """
    r = max(3, int(radius if radius else (cfg.nucleus_radius_px or 8)))
    sm = filters.gaussian(chan, sigma=cfg.nucleus_smooth_sigma, preserve_range=True)
    background = filters.gaussian(sm, sigma=3 * r, preserve_range=True)
    flat = np.clip(sm - background, 0, None)
    sample_mask = tissue & ~exclude if exclude is not None else tissue
    inside = flat[sample_mask] if sample_mask.any() else flat.ravel()
    if cfg.nucleus_od_threshold is not None:
        fg = (sm > cfg.nucleus_od_threshold) & tissue
    else:
        try:
            t_otsu = filters.threshold_otsu(inside)
        except ValueError:
            return np.zeros(chan.shape, dtype=np.int32)
        # Otsu needs two populations; on a field of ghost-pale nuclei it lands
        # above them.  A noise-based cut (median + 4 robust σ of the flattened
        # field) catches faint blobs; take whichever is lower, with a floor so
        # pure noise is never called a nucleus.
        med = np.median(inside)
        mad = np.median(np.abs(inside - med)) * 1.4826
        t = max(0.015, min(t_otsu, med + 4 * mad))
        fg = (flat > t) & (sm > 0.03) & tissue
    fg = remove_small(fg, max(4, int(0.15 * np.pi * r * r)))
    fg = ndi.binary_fill_holes(fg)
    fg = morphology.opening(fg, morphology.disk(1)).astype(bool)
    if not fg.any():
        return np.zeros(chan.shape, dtype=np.int32)

    dist = ndi.distance_transform_edt(fg)
    # seeds: distance-map maxima weighted by intensity, so an elongated
    # nucleus is not split at every wobble of its outline
    seedmap = dist * (1.0 + sm / (sm.max() + 1e-9))
    coords = feature.peak_local_max(seedmap, min_distance=max(3, int(round(0.7 * r))),
                                    labels=measure.label(fg), exclude_border=False)
    markers = np.zeros(chan.shape, dtype=np.int32)
    markers[tuple(coords.T)] = np.arange(1, len(coords) + 1)
    labels = segmentation.watershed(-seedmap, markers, mask=fg)
    return filter_by_area(labels, cfg.nucleus_min_area_px, max_area or cfg.nucleus_max_area_px)


def _median_radius(labels: np.ndarray, min_solidity: float = 0.9) -> float | None:
    """Typical nuclear radius from the detected objects.

    Two failure modes must both be survived: a first pass that shattered
    large pale nuclei into fragments (the plain median is far too small) and
    one that merged neighbouring nuclei into clusters (an area-weighted
    median is far too large).  True nuclei are solid; fragments and merged
    clusters are not.  So: keep solid objects only, then take the
    area-weighted median so a few intact large nuclei outvote many specks."""
    if labels.max() < 20:
        return None
    props = measure.regionprops(labels)
    areas = np.array([p.area for p in props if p.solidity >= min_solidity])
    if len(areas) < 20:
        areas = np.array([p.area for p in props])
    areas = np.sort(areas)
    cum = np.cumsum(areas)
    med = areas[np.searchsorted(cum, cum[-1] / 2)]
    return float(np.sqrt(med / np.pi))


_STARDIST_MODEL = None


def segment_stardist(rgb: np.ndarray, cfg: Config) -> np.ndarray:
    """Pretrained StarDist `2D_versatile_he` (trained on H&E; transfers well to
    hematoxylin-counterstained IHC).  The model is loaded once per process and
    large images are tiled automatically."""
    global _STARDIST_MODEL
    try:
        from stardist.models import StarDist2D
        from csbdeep.utils import normalize
    except ImportError as e:
        raise RuntimeError("StarDist backend requested but not installed: pip install 'ihcq[dl]'") from e
    if _STARDIST_MODEL is None:
        _STARDIST_MODEL = StarDist2D.from_pretrained("2D_versatile_he")
    model = _STARDIST_MODEL
    img = normalize(rgb.astype(np.float32), 1, 99.8, axis=(0, 1))
    n_tiles = model._guess_n_tiles(img)
    labels, _ = model.predict_instances(img, n_tiles=n_tiles, prob_thresh=cfg.stardist_prob, nms_thresh=cfg.stardist_nms,
                                        verbose=False, show_tile_progress=False)
    return filter_by_area(labels.astype(np.int32), cfg.nucleus_min_area_px, cfg.nucleus_max_area_px)


def filter_by_area(labels: np.ndarray, min_area: int, max_area: int) -> np.ndarray:
    if labels.max() == 0:
        return labels
    areas = np.bincount(labels.ravel())
    keep = (areas >= min_area) & (areas <= max_area)
    keep[0] = False
    out = np.where(keep[labels], labels, 0)
    # relabel densely so downstream tables have contiguous ids
    _, inv = np.unique(out, return_inverse=True)
    return inv.reshape(out.shape).astype(np.int32)


def rescue_dab_nuclei(labels: np.ndarray, dab: np.ndarray, tissue: np.ndarray, cfg: Config,
                      od_floor: float = 0.5, min_solidity: float = 0.85, max_overlap: float = 0.1) -> np.ndarray:
    """Add strongly DAB-stained nuclei that the counterstain missed.

    A nuclear marker at 3+ can quench hematoxylin almost completely; such a
    nucleus is then a compact, nucleus-sized, solid brown blob.  Membranous or
    cytoplasmic DAB forms rings and networks, which fail the shape test and
    are left alone — so this rescue is safe to run on every stain.
    """
    fg = (dab >= od_floor) & tissue
    fg = ndi.binary_fill_holes(morphology.opening(fg, morphology.disk(1)).astype(bool))
    cand = measure.label(fg)
    if cand.max() == 0:
        return labels
    out = labels.copy()
    nxt = int(labels.max()) + 1
    # a rescued blob must be at least a plausible fraction of a typical nucleus
    min_area = cfg.nucleus_min_area_px
    if labels.max() >= 30:
        min_area = max(min_area, int(0.6 * np.median(np.bincount(labels.ravel())[1:])))
    for r in measure.regionprops(cand):
        if not (min_area <= r.area <= cfg.nucleus_max_area_px):
            continue
        if r.solidity < min_solidity or r.eccentricity > 0.92:
            continue
        sl = r.slice
        m = cand[sl] == r.label
        if (labels[sl][m] > 0).mean() > max_overlap:
            continue
        out[sl][m & (labels[sl] == 0)] = nxt
        nxt += 1
    return out


def assumed_radius(cfg: Config) -> int:
    if cfg.nucleus_radius_px:
        return int(cfg.nucleus_radius_px)
    if cfg.mpp:
        return int(round(min(25, max(4, 4.0 / cfg.mpp))))
    return 8


def _classical(rgb, conc, tissue, cfg):
    chan = segmentation_channel(conc, rgb, cfg.segment_on)
    exclude = (conc[..., 1] >= cfg.thresholds.weak) if cfg.segment_on in ("auto", "hema") else None
    r = assumed_radius(cfg)
    return segment_watershed(chan, tissue, cfg, exclude=exclude, radius=r,
                             max_area=max(cfg.nucleus_max_area_px, int(6 * np.pi * r * r)))


def merge_missing(base: np.ndarray, extra: np.ndarray, max_overlap: float = 0.2) -> np.ndarray:
    """Add objects from `extra` that `base` has no nucleus for (overlap < 20%)."""
    out = base.copy()
    nxt = int(base.max()) + 1
    for r in measure.regionprops(extra):
        sl = r.slice
        m = extra[sl] == r.label
        if (base[sl][m] > 0).mean() > max_overlap:
            continue
        out[sl][m & (base[sl] == 0)] = nxt
        nxt += 1
    return out


def segment_nuclei(rgb: np.ndarray, conc: np.ndarray, tissue: np.ndarray, cfg: Config) -> np.ndarray:
    if cfg.backend in ("stardist", "hybrid"):
        labels = segment_stardist(rgb, cfg)
        labels = np.where(tissue, labels, 0).astype(np.int32)
        if cfg.backend == "hybrid":
            # StarDist (trained on H&E) is precise but blind to faintly
            # counterstained nuclei; the classical detector sees those.  Keep
            # StarDist's outlines and add classical nuclei it has no match for.
            labels = merge_missing(labels, _classical(rgb, conc, tissue, cfg))
        # the H&E model can skip a nucleus that is solid brown; same rescue as the classical path
        labels = rescue_dab_nuclei(labels, conc[..., 1], tissue, cfg, od_floor=cfg.thresholds.strong)
        return drop_debris(labels)
    chan = segmentation_channel(conc, rgb, cfg.segment_on)
    exclude = (conc[..., 1] >= cfg.thresholds.weak) if cfg.segment_on in ("auto", "hema") else None
    # Nuclear radius: given, or from pixel size (a typical nucleus is ~4 µm
    # across the radius), else 8 px (≈20× at 0.5 µm/px).  It is not estimated
    # from the image: every cheap estimator we tried is fooled either by
    # fragmented large nuclei or by merged clusters, so the honest thing is
    # to take it from metadata and report what was found (see
    # `median_nucleus_radius_px` in the summary).
    if cfg.nucleus_radius_px:
        r = int(cfg.nucleus_radius_px)
    elif cfg.mpp:
        r = int(round(min(25, max(4, 4.0 / cfg.mpp))))
    else:
        r = 8
    labels = segment_watershed(chan, tissue, cfg, exclude=exclude, radius=r,
                               max_area=max(cfg.nucleus_max_area_px, int(6 * np.pi * r * r)))
    if cfg.segment_on == "auto":
        labels = rescue_dab_nuclei(labels, conc[..., 1], tissue, cfg, od_floor=cfg.thresholds.strong)
    return drop_debris(labels)


def drop_debris(labels: np.ndarray, frac: float = 0.25, min_count: int = 30) -> np.ndarray:
    """Remove objects far smaller than the typical nucleus in this image
    (apoptotic bodies, chromogen specks, split fragments).  Only applied once
    there are enough nuclei to know what typical means."""
    n = int(labels.max())
    if n < min_count:
        return labels
    areas = np.bincount(labels.ravel())
    med = np.median(areas[1:])
    keep = areas >= frac * med
    keep[0] = False
    out = np.where(keep[labels], labels, 0)
    _, inv = np.unique(out, return_inverse=True)
    return inv.reshape(out.shape).astype(np.int32)


def compartment_masks(labels: np.ndarray, compartment: str, ring_px: int) -> np.ndarray:
    """Return a label image for the region each cell is scored in.

    nuclear   → the nucleus itself
    membrane  → a ring `ring_px` wide immediately outside the nucleus
    cytoplasm → a wider band outside the nucleus (2× ring), stopping at neighbours
    Rings are assigned to the nearest nucleus so adjacent cells don't share
    pixels.
    """
    if labels.max() == 0:
        return labels
    if compartment == "nuclear":
        # Score the nuclear core: a segmentation mask reliably overshoots the
        # true edge by a pixel, and that rim of pale membrane dilutes the mean
        # OD enough to demote 3+ nuclei.  Tiny nuclei that erode to nothing
        # keep their full mask.
        core = np.where(ndi.binary_erosion(labels > 0), labels, 0)
        kept = np.bincount(core.ravel(), minlength=labels.max() + 1) > 0
        return np.where(kept[labels], core, labels).astype(np.int32)
    width = ring_px if compartment == "membrane" else 2 * ring_px
    dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
    nearest = labels[iy, ix]
    ring = (labels == 0) & (dist <= width)
    return np.where(ring, nearest, 0).astype(np.int32)
