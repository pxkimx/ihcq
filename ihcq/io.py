"""Image loading.  Handles ordinary PNG/JPEG/TIFF fields and ROIs; for
pyramidal whole-slide TIFFs it reads the level closest to a requested size."""
from __future__ import annotations

from pathlib import Path
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # we manage memory ourselves; don't refuse large exports


def _to_rgb8(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.shape[-1] == 4:
        arr = arr[..., :3]
    if arr.dtype != np.uint8:
        a = arr.astype(np.float64)
        if a.max() > 255:               # 16-bit
            a = a / 257.0
        elif a.max() <= 1.0:            # float 0–1
            a = a * 255.0
        arr = np.clip(np.round(a), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def load_image(path, max_side: int | None = None) -> np.ndarray:
    """Return an RGB uint8 array.

    `max_side`: for pyramidal TIFFs, pick the pyramid level whose longest side
    is closest to (but not below) this; for flat images, it is ignored — we
    never silently resample a flat image because that changes nucleus sizes.
    """
    path = Path(path)
    if path.suffix.lower() in (".tif", ".tiff", ".svs", ".ndpi", ".btf"):
        try:
            import tifffile
            with tifffile.TiffFile(path) as tf:
                series = tf.series[0]
                levels = getattr(series, "levels", [series])
                pick = levels[0]
                if max_side and len(levels) > 1:
                    for lv in levels:
                        h, w = lv.shape[:2]
                        pick = lv
                        if max(h, w) <= max_side * 1.5:
                            break
                return _to_rgb8(pick.asarray())
        except ImportError:
            pass
    with Image.open(path) as im:
        return _to_rgb8(np.array(im.convert("RGB")))
