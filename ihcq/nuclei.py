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


def segmentation_channel(conc: np.ndarray, rgb: np.ndarray, how: str) -> np.ndarray:
    """Which signal nuclei are found in.

    Strong DAB in a nucleus quenches the hematoxylin counterstain, so for
    nuclear markers segmenting on hematoxylin alone loses precisely the
    positive cells.  `hema+dab` (default) avoids that; `hema` is right for
    membrane/cytoplasmic markers where DAB is not nuclear.
    """
    if how == "hema":
        return conc[..., 0]
    if how == "hema+dab":
        return conc[..., 0] + conc[..., 1]
    od_gray = -np.log10(np.clip(rgb.mean(-1) + 1, 1, None) / 256.0)
    return od_gray


def segment_watershed(chan: np.ndarray, tissue: np.ndarray, cfg: Config) -> np.ndarray:
    sm = filters.gaussian(chan, sigma=cfg.nucleus_smooth_sigma, preserve_range=True)
    inside = sm[tissue] if tissue.any() else sm.ravel()
    if cfg.nucleus_od_threshold is not None:
        t = cfg.nucleus_od_threshold
    else:
        try:
            t = filters.threshold_otsu(inside)
        except ValueError:
            return np.zeros(chan.shape, dtype=np.int32)
        # Otsu on a mostly-negative field can drift very low; keep a floor so
        # faint cytoplasm is not called nuclei.
        t = max(t, 0.12)
    fg = (sm > t) & tissue
    fg = morphology.remove_small_objects(fg, cfg.nucleus_min_area_px // 2)
    fg = ndi.binary_fill_holes(fg)
    fg = morphology.binary_opening(fg, morphology.disk(1))
    if not fg.any():
        return np.zeros(chan.shape, dtype=np.int32)

    dist = ndi.distance_transform_edt(fg)
    # Seeds: local maxima of the distance map, weighted by intensity so a
    # single elongated nucleus is not split at every wobble.
    seedmap = dist * (1.0 + sm / (sm.max() + 1e-9))
    coords = feature.peak_local_max(seedmap, min_distance=cfg.nucleus_min_distance_px,
                                    labels=measure.label(fg), exclude_border=False)
    markers = np.zeros(chan.shape, dtype=np.int32)
    markers[tuple(coords.T)] = np.arange(1, len(coords) + 1)
    labels = segmentation.watershed(-seedmap, markers, mask=fg)
    return filter_by_area(labels, cfg.nucleus_min_area_px, cfg.nucleus_max_area_px)


def segment_stardist(rgb: np.ndarray, cfg: Config) -> np.ndarray:
    try:
        from stardist.models import StarDist2D
        from csbdeep.utils import normalize
    except ImportError as e:
        raise RuntimeError("StarDist backend requested but not installed: pip install 'ihcq[dl]'") from e
    model = StarDist2D.from_pretrained("2D_versatile_he")
    labels, _ = model.predict_instances(normalize(rgb, 1, 99.8, axis=(0, 1)))
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


def segment_nuclei(rgb: np.ndarray, conc: np.ndarray, tissue: np.ndarray, cfg: Config) -> np.ndarray:
    if cfg.backend == "stardist":
        return segment_stardist(rgb, cfg)
    chan = segmentation_channel(conc, rgb, cfg.segment_on)
    return segment_watershed(chan, tissue, cfg)


def compartment_masks(labels: np.ndarray, compartment: str, ring_px: int) -> np.ndarray:
    """Return a label image for the region each cell is scored in.

    nuclear   → the nucleus itself
    membrane  → a ring `ring_px` wide immediately outside the nucleus
    cytoplasm → a wider band outside the nucleus (2× ring), stopping at neighbours
    Rings are assigned to the nearest nucleus so adjacent cells don't share
    pixels.
    """
    if compartment == "nuclear" or labels.max() == 0:
        return labels
    width = ring_px if compartment == "membrane" else 2 * ring_px
    dist, (iy, ix) = ndi.distance_transform_edt(labels == 0, return_indices=True)
    nearest = labels[iy, ix]
    ring = (labels == 0) & (dist <= width)
    return np.where(ring, nearest, 0).astype(np.int32)
