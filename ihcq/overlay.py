"""QC renderings.  A score without a picture of what was measured is not a
result anyone should trust, so every image gets an overlay by default."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.segmentation import find_boundaries

from .stains import reconstruct

BIN_RGB = {0: (60, 120, 255), 1: (255, 214, 0), 2: (255, 130, 0), 3: (220, 30, 30)}


def cell_overlay(rgb: np.ndarray, labels: np.ndarray, bins_by_label: dict, tissue: np.ndarray | None = None,
                 score_labels: np.ndarray | None = None) -> np.ndarray:
    """Outline each scored nucleus in its bin colour; grey out non-tissue."""
    out = rgb.copy()
    if tissue is not None:
        out[~tissue] = (out[~tissue] * 0.55 + 255 * 0.45).astype(np.uint8)
    if labels.max() > 0:
        bnd = find_boundaries(labels, mode="inner")
        lut = np.zeros((labels.max() + 1, 3), dtype=np.uint8)
        for lab, b in bins_by_label.items():
            lut[lab] = BIN_RGB[int(b)]
        out[bnd] = lut[labels[bnd]]
        if score_labels is not None and score_labels is not labels:
            rb = find_boundaries(score_labels, mode="outer") & (score_labels > 0)
            out[rb] = (out[rb] * 0.4 + lut[score_labels[rb]] * 0.6).astype(np.uint8)
    return out


def positivity_map(dab: np.ndarray, tissue: np.ndarray, th) -> np.ndarray:
    """Every tissue pixel painted by its DAB bin — the picture behind the area fraction."""
    from .metrics import bin_intensity
    bins = bin_intensity(dab, th)
    out = np.full(dab.shape + (3,), 255, dtype=np.uint8)
    out[tissue] = (235, 235, 235)
    for k, col in BIN_RGB.items():
        if k == 0:
            continue
        m = tissue & (bins == k)
        out[m] = col
    return out


def stain_panels(rgb: np.ndarray, conc: np.ndarray, matrix: np.ndarray, i0) -> np.ndarray:
    """Side-by-side: original | hematoxylin only | DAB only.  Shows whether the
    deconvolution actually separated the stains on this slide."""
    h = reconstruct(conc, matrix, 0, i0)
    d = reconstruct(conc, matrix, 1, i0)
    return np.concatenate([rgb, h, d], axis=1)


def with_caption(img: np.ndarray, text: str) -> np.ndarray:
    im = Image.fromarray(img)
    strip = Image.new("RGB", (im.width, 26), (20, 20, 20))
    draw = ImageDraw.Draw(strip)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 13)
    except Exception:
        font = ImageFont.load_default()
    draw.text((8, 6), text, fill=(240, 240, 240), font=font)
    canvas = Image.new("RGB", (im.width, im.height + 26))
    canvas.paste(strip, (0, 0))
    canvas.paste(im, (0, 26))
    return np.array(canvas)


def save(img: np.ndarray, path) -> None:
    Image.fromarray(img).save(path)
