"""Tissue-versus-glass masking."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from skimage import morphology


def remove_small(mask: np.ndarray, n: int) -> np.ndarray:
    """Drop connected components smaller than `n` px, on any scikit-image version."""
    try:
        return morphology.remove_small_objects(mask, max_size=n - 1)
    except TypeError:
        return morphology.remove_small_objects(mask, min_size=n)


def tissue_mask(od_total: np.ndarray, threshold: float = 0.08, min_size: int = 400, close_radius: int = 3,
                fill_holes: bool = True, smooth_sigma: float = 4.0) -> np.ndarray:
    """Pixels that belong to the tissue footprint.

    `od_total` is the summed OD across channels.  Bare glass sits near zero.
    The OD is smoothed (σ≈4 px) before thresholding so that a region dense in
    nuclei counts as tissue even where the stroma between them is barely
    counterstained — otherwise pale stroma punches holes that drop the very
    cells sitting in it.  Small specks (dust, debris) are removed and holes
    (lumens, fat vacuoles) filled, so area fractions are relative to the
    tissue footprint rather than to stained pixels alone.
    """
    field = ndi.gaussian_filter(od_total.astype(np.float32), smooth_sigma) if smooth_sigma else od_total
    mask = field > threshold
    if close_radius > 0:
        mask = morphology.closing(mask, morphology.disk(close_radius)).astype(bool)
    if fill_holes:
        mask = ndi.binary_fill_holes(mask)
    if min_size > 0:
        mask = remove_small(mask, min_size)
    return mask


def saturation_fraction(rgb: np.ndarray, mask: np.ndarray | None = None, lo: int = 3, hi: int = 252) -> float:
    """Fraction of (tissue) pixels that are clipped in any channel.

    Clipped pixels have unknown true OD; a slide with many of them was
    over-exposed on the scanner and its intensities can't be trusted.
    """
    clipped = np.any((rgb <= lo) | (rgb >= hi), axis=-1)
    if mask is not None:
        clipped = clipped & mask
        denom = mask.sum()
    else:
        denom = clipped.size
    return float(clipped.sum() / max(denom, 1))
