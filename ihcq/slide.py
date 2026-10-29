"""Whole-slide images: tiled region reads from pyramidal TIFF (Aperio SVS,
NDPI-style tiled TIFF, OME-TIFF) without loading the slide into memory,
and tiled analysis with overlap, de-duplication and progress.

Region reads decode only the TIFF tiles a region touches (tifffile's own
tile decoder; JPEG/LZW/deflate via imagecodecs), so no zarr is needed.
"""
from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import tifffile

SLIDE_EXT = (".svs", ".tif", ".tiff", ".ndpi", ".btf", ".scn", ".ome.tif", ".ome.tiff")


class Slide:
    def __init__(self, path):
        self.path = str(path)
        self.tf = tifffile.TiffFile(self.path)
        s = self.tf.series[0]
        levels = list(getattr(s, "levels", None) or [s])
        self.pages = []
        for lv in levels:
            pg = lv.pages[0] if getattr(lv, "pages", None) else lv.keyframe
            self.pages.append(pg)
        self.dims = [(int(p.imagewidth), int(p.imagelength)) for p in self.pages]
        self.mpp = self._mpp()
        self._lock = threading.Lock()
        self._full = {}

    def _mpp(self):
        desc = self.pages[0].description or ""
        m = re.search(r"MPP\s*=\s*([0-9.]+)", desc)                       # Aperio
        if m:
            return float(m.group(1))
        m = re.search(r'PhysicalSizeX="([0-9.eE+-]+)"', self.tf.pages[0].description or "")  # OME
        if m:
            return float(m.group(1))
        try:                                                               # resolution tags in cm⁻¹
            tags = self.pages[0].tags
            unit = tags["ResolutionUnit"].value
            xr = tags["XResolution"].value
            px_per_unit = xr[0] / xr[1]
            if int(unit) == 3 and px_per_unit > 100:                       # centimetre
                return 1e4 / px_per_unit
            if int(unit) == 2 and px_per_unit > 1000:                      # inch
                return 25400 / px_per_unit
        except Exception:
            pass
        return None

    @property
    def size(self):
        return self.dims[0]

    def best_level(self, max_side: int) -> int:
        for i in range(len(self.dims) - 1, -1, -1):
            if max(self.dims[i]) >= max_side:
                return i
        return 0

    def read(self, level: int, x: int, y: int, w: int, h: int) -> np.ndarray:
        """RGB uint8 region at `level` (coordinates in that level's pixels), clipped to the image."""
        page = self.pages[level]
        W, H = self.dims[level]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        out = np.full((h, w, 3), 255, np.uint8)
        if x1 <= x0 or y1 <= y0:
            return out
        if not page.is_tiled:
            if level not in self._full:
                with self._lock:
                    a = page.asarray()
                self._full[level] = _rgb(a)
            out[y0 - y:y1 - y, x0 - x:x1 - x] = self._full[level][y0:y1, x0:x1]
            return out
        tw, th = page.tilewidth, page.tilelength
        ntx = math.ceil(W / tw)
        fh = self.tf.filehandle
        for ty in range(y0 // th, (y1 - 1) // th + 1):
            for tx in range(x0 // tw, (x1 - 1) // tw + 1):
                idx = ty * ntx + tx
                off, cnt = page.dataoffsets[idx], page.databytecounts[idx]
                if cnt == 0:
                    continue
                with self._lock:
                    fh.seek(off); data = fh.read(cnt)
                seg, _, _ = page.decode(data, idx, jpegtables=page.jpegtables)
                tile = _rgb(np.asarray(seg).reshape(th, tw, -1))
                gx0, gy0 = tx * tw, ty * th
                ix0, iy0, ix1, iy1 = max(x0, gx0), max(y0, gy0), min(x1, gx0 + tw), min(y1, gy0 + th)
                out[iy0 - y:iy1 - y, ix0 - x:ix1 - x] = tile[iy0 - gy0:iy1 - gy0, ix0 - gx0:ix1 - gx0]
        return out

    def overview(self, max_side: int = 2000):
        """(rgb, scale) — the whole slide downsampled so its long side ≤ max_side; scale = overview px per level-0 px."""
        lv = self.best_level(max_side)
        W, H = self.dims[lv]
        f = min(1.0, max_side / max(W, H))
        if max(W, H) * 1.0 <= 12000:
            img = self.read(lv, 0, 0, W, H)
        else:                                                            # huge single level: read in strips
            img = np.concatenate([self.read(lv, 0, y, W, min(4096, H - y)) for y in range(0, H, 4096)], 0)
        if f < 1:
            from PIL import Image
            img = np.array(Image.fromarray(img).resize((max(1, int(W * f)), max(1, int(H * f))), Image.LANCZOS))
        return img, img.shape[1] / self.dims[0][0]

    def close(self):
        self.tf.close()


def _rgb(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    if a.shape[-1] > 3:
        a = a[..., :3]
    if a.dtype != np.uint8:
        a = np.clip(a / (257.0 if a.max() > 255 else 1.0), 0, 255).astype(np.uint8)
    return a


def is_slide(path) -> bool:
    p = str(path).lower()
    if not p.endswith(SLIDE_EXT):
        return False
    try:
        with tifffile.TiffFile(p) as tf:
            pg = tf.pages[0]
            return pg.is_tiled or len(tf.series[0].levels) > 1 or pg.imagewidth * pg.imagelength > 40e6
    except Exception:
        return False


# ---------------------------------------------------------------------------
# tiled analysis
# ---------------------------------------------------------------------------
_W = {}


def _worker_init(path, server_pid=None):
    from .lifecycle import die_with_parent
    die_with_parent(server_pid)                                    # never outlive the app that started us
    _W["slide"] = Slide(path)


def _tile_job(args):
    """Analyze one tile (with overlap); return cells whose centroid lies in the tile core, plus core pixel stats."""
    import warnings; warnings.filterwarnings("ignore")
    from .config import Config
    from .pipeline import analyze
    from .metrics import bin_intensity
    (tx, ty, x, y, w, h, ov, cfgd) = args
    cfg = Config.from_dict(cfgd)
    rgb = _W["slide"].read(0, x - ov, y - ov, w + 2 * ov, h + 2 * ov)
    res = analyze(rgb, cfg)
    core = np.zeros(rgb.shape[:2], bool); core[ov:ov + h, ov:ov + w] = True
    t = res.tissue & core
    dab = res.conc[..., 1]
    stats = {"tissue_px": int(t.sum())}
    if t.any():
        d = dab[t]; b = bin_intensity(d, cfg.thresholds)
        stats.update({"pos_px": int((d >= cfg.thresholds.weak).sum()), "sum_od": float(d.sum()), "bins": np.bincount(b, minlength=4).tolist(),
                      "hist": np.histogram(np.clip(d, 0, 2.999), bins=300, range=(0, 3))[0].tolist(),
                      "hema_pos_px": int((res.conc[..., 0][t] >= cfg.thresholds.weak).sum())})
    cells = res.cells
    if len(cells):
        keep = (cells.x >= ov) & (cells.x < ov + w) & (cells.y >= ov) & (cells.y < ov + h)
        cells = cells[keep].copy()
        cells["x"] = cells["x"] + x - ov; cells["y"] = cells["y"] + y - ov
        cells["tile"] = f"{tx},{ty}"
    return cells, stats


def slide_white(sl: "Slide", ovw: np.ndarray, scale: float, n: int = 8, box: int = 256):
    """White point from bare glass sampled at FULL resolution.

    The overview is downsampled, so glass pixels near tissue are blended with
    it; a 1–2 grey-level error per channel is enough to shift nucleus counts
    and positivity measurably (the channels shift unequally, which colour
    deconvolution reads as a faint stain).  So: find glass on the overview,
    read small level-0 boxes there, and estimate the white point from those."""
    from scipy import ndimage as ndi
    from .stains import find_white
    g = ovw.astype(np.int16)
    ref, _ = find_white(ovw)                         # brightest neutral level on the overview
    # glass is the BRIGHTEST neutral material; pale stroma is neutral too but a few levels darker
    glass = (g.min(-1) >= float(np.min(ref)) - 5) & ((g.max(-1) - g.min(-1)) <= 12)
    # glass pixels farthest from anything that isn't glass — works for small corners too
    dist = ndi.distance_transform_edt(glass)
    ys, xs = np.nonzero(dist >= max(2.0, min(dist.max(), box * scale / 2)))
    if len(ys) == 0:
        wp, found = find_white(ovw)
        return wp, "overview" if found else "default"
    order = np.argsort(-dist[ys, xs])
    pick = order[:: max(1, len(order) // n)][:n]
    W0, H0 = sl.size
    clampx = lambda v: int(min(max(0, v), W0 - box)); clampy = lambda v: int(min(max(0, v), H0 - box))   # never read past the edge (padding is white)
    boxes = [sl.read(0, clampx(xs[i] / scale - box // 2), clampy(ys[i] / scale - box // 2), box, box) for i in pick]
    wp, found = find_white(np.concatenate(boxes, 0))
    return wp, ("glass (full resolution)" if found else "default")


def analyze_slide(path, cfg=None, tile: int = 2048, overlap: int = 64, workers: int | None = None,
                  progress=None, max_tiles: int | None = None, min_tissue: float = 0.03):
    """Analyze a whole slide at full resolution.  Returns (summary, cells, overview_rgb, overview_scale, info)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from .config import Config
    from .stains import find_white, stain_matrix, deconvolve
    from .tissue import tissue_mask
    from .metrics import h_score
    from .pipeline import score_cells
    cfg = Config.from_dict((cfg or Config()).to_dict())
    sl = Slide(path)
    W, H = sl.size
    if sl.mpp and not cfg.mpp:
        cfg.mpp = sl.mpp
    ovw, scale = sl.overview(2000)
    white_src = "config"
    if not cfg.white_point:
        wp, white_src = slide_white(sl, ovw, scale)
        cfg.white_point = [float(v) for v in wp]
    # tissue at overview scale decides which tiles are worth reading
    conc = deconvolve(ovw, stain_matrix(cfg.stains, cfg.stain_vectors), np.asarray(cfg.white_point))
    tmask = tissue_mask(conc.sum(-1), cfg.tissue_od_threshold, 50, smooth_sigma=2)
    jobs = []
    for ty in range(math.ceil(H / tile)):
        for tx in range(math.ceil(W / tile)):
            x, y = tx * tile, ty * tile; w, h = min(tile, W - x), min(tile, H - y)
            sx0, sy0 = int(x * scale), int(y * scale); sx1, sy1 = max(sx0 + 1, int((x + w) * scale)), max(sy0 + 1, int((y + h) * scale))
            if tmask[sy0:sy1, sx0:sx1].mean() >= min_tissue:
                jobs.append((tx, ty, x, y, w, h, overlap, cfg.to_dict()))
    total_tiles = math.ceil(H / tile) * math.ceil(W / tile)
    if max_tiles:
        jobs = jobs[:max_tiles]
    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 2))
    cells_parts, agg = [], {"tissue_px": 0, "pos_px": 0, "sum_od": 0.0, "bins": np.zeros(4, np.int64), "hist": np.zeros(300, np.int64), "hema_pos_px": 0}
    done = 0
    if progress: progress(0, len(jobs))
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=(sl.path, os.getpid())) as ex:
        futs = [ex.submit(_tile_job, j) for j in jobs]
        for f in as_completed(futs):
            c, st = f.result()
            if len(c): cells_parts.append(c)
            agg["tissue_px"] += st["tissue_px"]
            if st.get("bins"):
                agg["pos_px"] += st["pos_px"]; agg["sum_od"] += st["sum_od"]; agg["bins"] += np.array(st["bins"]); agg["hist"] += np.array(st["hist"]); agg["hema_pos_px"] += st["hema_pos_px"]
            done += 1
            if progress: progress(done, len(jobs))
    cells = pd.concat(cells_parts, ignore_index=True) if cells_parts else pd.DataFrame()
    if len(cells): cells["cell"] = np.arange(1, len(cells) + 1)
    tp = max(agg["tissue_px"], 1)
    cdf = np.cumsum(agg["hist"]) / max(agg["hist"].sum(), 1)
    summary = {"image": Path(path).name, "width": W, "height": H, "levels": len(sl.dims), "mpp": cfg.mpp,
               "tiles_analyzed": len(jobs), "tiles_total": total_tiles, "tile_px": tile,
               "white_point": [round(v, 1) for v in cfg.white_point], "white_point_source": white_src,
               "tissue_px": int(agg["tissue_px"]), "tissue_fraction": round(float(tmask.mean()), 4),
               "dab_area_fraction_pct": round(agg["pos_px"] / tp * 100, 3), "hema_area_fraction_pct": round(agg["hema_pos_px"] / tp * 100, 3),
               "mean_dab_od_tissue": round(agg["sum_od"] / tp, 4), "p95_dab_od_tissue": round(float(np.searchsorted(cdf, 0.95) * 0.01), 3),
               "integrated_dab_od": round(agg["sum_od"], 1),
               **{f"pct_px_{k}plus": round(float(agg["bins"][k] / tp * 100), 3) for k in (1, 2, 3)},
               "pixel_h_score": round(float((agg["bins"][1] + 2 * agg["bins"][2] + 3 * agg["bins"][3]) / tp * 100), 1),
               "compartment": cfg.compartment, "cell_statistic": cfg.cell_statistic,
               "thr_weak": cfg.thresholds.weak, "thr_moderate": cfg.thresholds.moderate, "thr_strong": cfg.thresholds.strong, "profile": cfg.profile_name}
    if cfg.mpp:
        summary["tissue_area_mm2"] = round(agg["tissue_px"] * (cfg.mpp / 1000) ** 2, 3)
    if len(cells):
        summary.update(score_cells(cells, int(agg["tissue_px"]), cfg, {}))
    sl.close()
    return summary, cells, ovw, scale, {"cfg": cfg, "tissue_overview": tmask}


BIN_RGB = [(59, 130, 246), (245, 197, 24), (255, 138, 0), (229, 56, 59)]


def overview_cells_image(ovw: np.ndarray, cells: pd.DataFrame, scale: float, radius: int = 2) -> np.ndarray:
    """Overview with every scored cell drawn as a dot in its bin colour."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(ovw.copy()); d = ImageDraw.Draw(im)
    if len(cells):
        xs, ys, bs = (cells.x.to_numpy() * scale), (cells.y.to_numpy() * scale), cells["bin"].to_numpy()
        for k in (0, 1, 2, 3):                                  # negatives first so positives sit on top
            m = bs == k
            for x, y in zip(xs[m], ys[m]):
                d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=BIN_RGB[k])
    return np.array(im)
