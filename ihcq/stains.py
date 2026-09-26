"""Stain optics: optical density, colour deconvolution, white-point estimation.

Everything downstream works in optical density (OD) space, because under the
Beer–Lambert law OD is linear in chromogen concentration while RGB intensity
is not.  Colour deconvolution follows Ruifrok & Johnston (2001).
"""
from __future__ import annotations

import numpy as np

# Published unit OD vectors (R, G, B) for common stains.  Values from Ruifrok &
# Johnston 2001 and the ImageJ colour-deconvolution plugin.  Real slides drift
# from these; use `estimate_stain_vectors` or a calibration profile for
# anything you intend to publish.
STAIN_VECTORS = {
    "hematoxylin": (0.650, 0.704, 0.286),
    "dab": (0.268, 0.570, 0.776),
    "eosin": (0.072, 0.990, 0.105),
    "aec": (0.274, 0.679, 0.680),
    "fast_red": (0.214, 0.851, 0.478),
    "methyl_green": (0.980, 0.144, 0.133),
}


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n == 0:
        raise ValueError("stain vector has zero length")
    return v / n


def stain_matrix(stains=("hematoxylin", "dab"), vectors=None) -> np.ndarray:
    """Return a 3×3 matrix whose rows are unit stain OD vectors.

    `stains` names entries in STAIN_VECTORS; `vectors` (list of 3-tuples)
    overrides them.  With two stains the third row is their cross product,
    which absorbs whatever colour neither stain explains.
    """
    rows = [_unit(v) for v in vectors] if vectors is not None else [_unit(STAIN_VECTORS[s]) for s in stains]
    if len(rows) == 2:
        third = np.cross(rows[0], rows[1])
        rows.append(_unit(third))
    if len(rows) != 3:
        raise ValueError("need two or three stains")
    m = np.vstack(rows)
    if abs(np.linalg.det(m)) < 1e-6:
        raise ValueError("stain vectors are (nearly) collinear; deconvolution is ill-posed")
    return m


def find_white(rgb: np.ndarray, percentile: float = 99.5, default: float = 245.0):
    """Per-channel illumination reference I0 from bare glass, if the field has any.

    Glass is bright AND neutral.  Bright tissue (cytoplasm, mucin) is usually
    tinted, and taking it as "white" would fold that tint into every OD.  A
    field with no glass returns the default and `found=False`; the right
    value then is one measured on a blank area of the same slide, passed in
    as `white_point`.
    """
    flat = rgb.reshape(-1, 3).astype(np.float64)
    cand = flat[(flat.min(1) >= 170) & ((flat.max(1) - flat.min(1)) <= 20)]
    if len(cand) < max(200, 0.005 * len(flat)):
        return np.full(3, default), False
    # Glass is the brightest neutral cluster.  Its TYPICAL value is I0 — a high
    # percentile lands on sensor noise and dust highlights instead, which sets
    # I0 a few levels too bright, unequally per channel, and deconvolution
    # turns that cast into false stain on pale tissue.
    top = np.percentile(cand.mean(1), percentile)
    glass = cand[cand.mean(1) >= top - 8]
    if len(glass) < 100:
        glass = cand[cand.mean(1) >= np.percentile(cand.mean(1), 90)]
    return np.clip(np.median(glass, axis=0), 170, 255), True


def estimate_white(rgb: np.ndarray, percentile: float = 99.5) -> np.ndarray:
    """I0 from glass; falls back to a neutral default when the field has none."""
    return find_white(rgb, percentile)[0]


def rgb_to_od(rgb: np.ndarray, i0=255.0) -> np.ndarray:
    """OD = -log10(I / I0), per channel. Input uint8 or float 0-255."""
    i = np.asarray(rgb, dtype=np.float64)
    i0 = np.asarray(i0, dtype=np.float64)
    od = -np.log10(np.clip(i + 1.0, 1.0, None) / (i0 + 1.0))
    return np.clip(od, 0.0, None)


def od_to_rgb(od: np.ndarray, i0=255.0) -> np.ndarray:
    i = (np.asarray(i0, dtype=np.float64) + 1.0) * np.power(10.0, -np.asarray(od)) - 1.0
    return np.clip(np.round(i), 0, 255).astype(np.uint8)


def deconvolve(rgb: np.ndarray, matrix: np.ndarray | None = None, i0=None) -> np.ndarray:
    """Separate an RGB image into per-stain OD concentrations.

    Returns float array (H, W, 3) ordered as the rows of `matrix`
    (default: hematoxylin, DAB, residual).  Units are OD, so a value of
    1.0 in the DAB channel means that pixel absorbs one decade of light in
    the DAB direction.
    """
    if matrix is None:
        matrix = stain_matrix()
    if i0 is None:
        i0 = estimate_white(rgb)
    od = rgb_to_od(rgb, i0)
    h, w, _ = od.shape
    conc = od.reshape(-1, 3) @ np.linalg.inv(matrix)
    conc = np.clip(conc, 0.0, None)
    return conc.reshape(h, w, 3)


def reconstruct(conc: np.ndarray, matrix: np.ndarray, which: int, i0=255.0) -> np.ndarray:
    """Render a single stain channel back to RGB (for QC images)."""
    single = np.zeros_like(conc)
    single[..., which] = conc[..., which]
    od = single.reshape(-1, 3) @ matrix
    return od_to_rgb(od.reshape(conc.shape), i0)


def estimate_stain_vectors(rgb: np.ndarray, od_min: float = 0.15, alpha: float = 1.0, i0=None) -> np.ndarray:
    """Macenko et al. (2009) estimate of the two dominant stain vectors.

    Projects tissue OD onto its top two principal components and takes the
    extreme angles.  Returns a 3×3 matrix (stain1, stain2, residual) with the
    rows sorted so that the hematoxylin-like vector comes first.  Use this to
    build a slide-specific profile when the textbook vectors don't fit.
    """
    if i0 is None:
        i0 = estimate_white(rgb)
    od = rgb_to_od(rgb, i0).reshape(-1, 3)
    od = od[od.sum(1) > od_min]
    if len(od) < 500:
        raise ValueError("not enough stained pixels to estimate stain vectors")
    cov = np.cov(od.T)
    evals, evecs = np.linalg.eigh(cov)
    basis = evecs[:, np.argsort(evals)[-2:]]
    proj = od @ basis
    ang = np.arctan2(proj[:, 1], proj[:, 0])
    lo, hi = np.percentile(ang, [alpha, 100 - alpha])
    v1 = basis @ np.array([np.cos(lo), np.sin(lo)])
    v2 = basis @ np.array([np.cos(hi), np.sin(hi)])
    v1, v2 = _unit(np.abs(v1)), _unit(np.abs(v2))
    # Row 0 is whichever fitted vector is closer to textbook hematoxylin; the
    # other is the second stain (DAB, eosin, ...).  A colour-component rule
    # ("hematoxylin has less blue") fails for eosin, which has less still.
    h = _unit(STAIN_VECTORS["hematoxylin"])
    if v1 @ h < v2 @ h:
        v1, v2 = v2, v1
    return stain_matrix(vectors=[v1, v2])


def identify_second_stain(rgb: np.ndarray, i0=None) -> dict:
    """What is the non-hematoxylin stain on this image?

    Fits the two dominant stain vectors (Macenko) and compares the second one
    with the textbook DAB and eosin vectors.  On chromogenic IHC the second
    vector sits within ~20° of DAB and >40° from eosin; on H&E it is the
    reverse.  Returns {"stain": "dab" | "eosin" | "unknown", "angle_to_dab",
    "angle_to_eosin"}; "unknown" covers a field with too little second stain
    to fit (a fully negative IHC field looks like this) or an ambiguous
    vector (melanin and some red chromogens land between the two).
    """
    try:
        m = estimate_stain_vectors(rgb, i0=i0)
    except ValueError:
        return {"stain": "unknown", "angle_to_dab": None, "angle_to_eosin": None}
    v = m[1]
    dab, eos = _unit(STAIN_VECTORS["dab"]), _unit(STAIN_VECTORS["eosin"])
    a_d = float(np.degrees(np.arccos(np.clip(v @ dab, -1, 1))))
    a_e = float(np.degrees(np.arccos(np.clip(v @ eos, -1, 1))))
    # DAB IHC fields measured so far sit 2–19° from DAB; H&E fields 9–30° from
    # eosin.  A confident call needs both a small angle and clear separation.
    if a_d < 20 and a_e - a_d > 10:
        stain = "dab"
    elif a_e < 30 and a_d - a_e > 5:
        stain = "eosin"
    else:
        stain = "unknown"
    return {"stain": stain, "angle_to_dab": round(a_d, 1), "angle_to_eosin": round(a_e, 1)}
