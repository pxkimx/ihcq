"""Analysis configuration.  Every number that changes a score lives here and is
written into every result, so a score can always be traced to its settings."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Thresholds:
    """DAB optical-density cut points between intensity bins.

    A cell (or pixel) with DAB OD below `weak` is negative (0); between
    `weak` and `moderate` is 1+; between `moderate` and `strong` is 2+;
    at or above `strong` is 3+.  The defaults are sensible for a typical
    nuclear DAB stain scanned at 20× but are NOT universal — calibrate them
    against control tissue (see `ihcq calibrate`) before reporting.
    """
    weak: float = 0.15
    moderate: float = 0.40
    strong: float = 0.80

    def validate(self):
        if not (0 < self.weak < self.moderate < self.strong):
            raise ValueError("thresholds must satisfy 0 < weak < moderate < strong")


@dataclass
class Config:
    # optics
    stains: tuple = ("hematoxylin", "dab")
    stain_vectors: Optional[list] = None          # overrides `stains` when set (from calibration)
    fit_stains: bool = False                      # fit the two stain vectors to each image (Macenko) instead of textbook/profile
    white_point: Optional[list] = None            # per-channel I0; None → estimate per image
    # tissue
    tissue_od_threshold: float = 0.08
    tissue_smooth_sigma: float = 4.0
    tissue_min_size_px: int = 400
    # nuclei
    segment: bool = True
    segment_on: str = "auto"                      # auto | hema | hema+dab | gray
    nucleus_min_area_px: int = 20
    nucleus_max_area_px: int = 5000
    nucleus_smooth_sigma: float = 1.0
    nucleus_radius_px: Optional[int] = None       # typical nuclear radius in px; None → from mpp or estimated
    nucleus_od_threshold: Optional[float] = None  # None → Otsu on the segmentation channel
    backend: str = "watershed"                    # watershed | stardist | hybrid
    stardist_prob: Optional[float] = 0.35         # detection probability; the H&E model's own 0.69 misses pale IHC nuclei
    stardist_nms: Optional[float] = None          # None → model default (0.3)
    # scoring
    compartment: str = "nuclear"                  # nuclear | membrane | cytoplasm
    ring_px: int = 3                              # ring width for membrane/cytoplasm compartments
    cell_statistic: str = "mean"                  # mean | median | p90 — how DAB is summarised per cell
    thresholds: Thresholds = field(default_factory=Thresholds)
    pixel_positive_od: Optional[float] = None     # None → thresholds.weak
    # scale
    mpp: Optional[float] = None                   # microns per pixel, for area in µm² and density per mm²
    # bookkeeping
    profile_name: str = "default"

    def validate(self):
        self.thresholds.validate()
        if self.segment_on not in ("auto", "hema", "hema+dab", "gray"):
            raise ValueError("segment_on must be auto, hema, hema+dab or gray")
        if self.compartment not in ("nuclear", "membrane", "cytoplasm"):
            raise ValueError("compartment must be nuclear, membrane or cytoplasm")
        if self.cell_statistic not in ("mean", "median", "p90"):
            raise ValueError("cell_statistic must be mean, median or p90")
        return self

    # --- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["stains"] = list(self.stains)
        return d

    def to_json(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        d = dict(d)
        th = d.pop("thresholds", {}) or {}
        cfg = cls(**d)
        cfg.thresholds = Thresholds(**th) if isinstance(th, dict) else th
        cfg.stains = tuple(cfg.stains)
        return cfg.validate()

    @classmethod
    def from_json(cls, path) -> "Config":
        return cls.from_dict(json.loads(Path(path).read_text()))
