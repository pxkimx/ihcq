"""ihcq — reproducible chromogenic IHC quantification."""
from .config import Config, Thresholds
from .pipeline import analyze, analyze_file, Result
from .stains import deconvolve, stain_matrix, rgb_to_od, estimate_white, estimate_stain_vectors
from .metrics import h_score, allred, bin_intensity

__version__ = "0.2.0"
__all__ = ["Config", "Thresholds", "analyze", "analyze_file", "Result", "deconvolve", "stain_matrix",
           "rgb_to_od", "estimate_white", "estimate_stain_vectors", "h_score", "allred", "bin_intensity"]
