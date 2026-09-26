# ihcq — chromogenic IHC quantification

Reproducible scoring of DAB-stained immunohistochemistry from ordinary image
files: **H-score**, **Allred**, **positivity area fraction**, **optical density**
and **0 / 1+ / 2+ / 3+ binning**, per cell and per pixel, with QC overlays and
every threshold written into every result.

No deep learning is required. Nuclei are found by a hematoxylin-driven
watershed; StarDist can be dropped in for crowded or irregular tissue.

## Install

```bash
pip install -e .            # core: numpy, scipy, scikit-image, pandas, pillow
pip install -e '.[wsi]'     # + tifffile for pyramidal / whole-slide TIFF
pip install -e '.[dl]'      # + StarDist nucleus segmentation (needs TensorFlow)
```

## Sixty-second tour

```bash
ihcq demo -o demo/                               # synthetic slides with known truth, scored end to end
ihcq inspect demo/mixed.png                      # OD histogram + white point: are the default cuts sane?
ihcq score demo/*.png -o results.csv --overlays qc/ --cells-dir cells/
open qc/mixed_cells.png                          # every nucleus outlined in its bin colour
```

## What is measured, and how

All arithmetic is done in **optical density** (OD = −log10 I/I₀), because under
Beer–Lambert OD is linear in chromogen amount while RGB brightness is not.
Hematoxylin and DAB are separated by **colour deconvolution** (Ruifrok &
Johnston 2001) using either the textbook stain vectors or ones fitted to your
slide (Macenko 2009, `--estimate-stains`). The white point I₀ is estimated from
the glass in each image, so a dim scan does not read as lightly stained.

### Cell level (needs nuclei)

| output | definition |
|---|---|
| `bin` per cell | DAB OD in the scoring compartment → 0 / 1+ / 2+ / 3+ by three cut points |
| `pct_positive`, `pct_1plus` … | share of cells in each bin |
| `h_score` | 1·%1+ + 2·%2+ + 3·%3+, range 0–300 |
| `allred_ps / _is / _total` | proportion score 0–5 + intensity score 0–3 = 0–8 |
| `cells_per_mm2`, `positive_cells_per_mm2` | with `--mpp` |

The **compartment** is where DAB is read for each cell: `nuclear` (Ki-67, ER,
PR, p53), `membrane` (a ring outside the nucleus — HER2, PD-L1, EGFR) or
`cytoplasm` (a wider band). The per-cell summary statistic is the mean by
default; `p90` is more faithful for punctate or membranous staining.

### Pixel level (no nuclei needed, `--no-segment` for stroma, ECM, secreted markers)

| output | definition |
|---|---|
| `dab_area_fraction_pct` | tissue pixels with DAB OD ≥ weak cut ÷ all tissue pixels |
| `pct_px_1plus` … | tissue pixels in each intensity bin |
| `pixel_h_score` | same arithmetic as H-score, over pixels instead of cells |
| `mean_dab_od_tissue`, `mean_dab_od_positive`, `p95_dab_od_tissue` | intensity |
| `integrated_dab_od` | Σ DAB OD over tissue — proportional to total chromogen |
| `tissue_area_mm2`, `dab_area_mm2` | with `--mpp` |

*Tissue* is the footprint after hole-filling, so a lumen or fat vacuole counts
as tissue area; bare glass never does.

## Calibration — do this before reporting anything

The 1+/2+/3+ cut points are the whole result. The defaults (0.15 / 0.40 /
0.80 OD) are a reasonable start for a nuclear DAB stain at 20× and nothing
more. Every result row records the cuts used and the profile name, and the QC
flags nag until you calibrate. Two ways:

**From control tissue** — a negative control plus fields whose positive cells a
pathologist calls 1+, 2+ and 3+:

```bash
ihcq calibrate --negative neg1.png neg2.png --weak w1.png --moderate m1.png --strong s1.png \
               -o ki67_profile.json --estimate-stains
ihcq score cases/*.png --profile ki67_profile.json -o results.csv --overlays qc/
```

The negative control anchors the 0/1+ cut (nothing in it may score positive);
the upper cuts sit between the positive-cell populations of adjacent controls.

**From pathologist-scored slides** — the route for a concordance study:

```bash
# scores.csv:  image,h_score
ihcq calibrate --scored scores.csv -o fitted_profile.json
```

This searches cut-point triples for the best agreement with the pathologist's
H-scores and prints the per-slide residuals. Fit on one set of slides,
validate on another — never the same ones.

## QC you get for free

Every scored image can write three PNGs (`--overlays DIR`):

- `*_cells.png` — nuclei outlined in bin colour (blue 0, yellow 1+, orange 2+, red 3+); membrane rings drawn when that compartment is used
- `*_positivity.png` — every tissue pixel painted by its bin: the picture behind the area fraction
- `*_stains.png` — original | hematoxylin only | DAB only: proves the deconvolution separated your stains

And every result row carries `qc_flags`: clipped pixels (over-exposed scan),
too little tissue, too few cells for a stable H-score, chromogen saturation,
and uncalibrated thresholds.

## Python API

```python
from ihcq import Config, analyze
from ihcq.io import load_image

cfg = Config.from_json("ki67_profile.json")
cfg.compartment = "nuclear"; cfg.mpp = 0.25
res = analyze(load_image("case_07.png"), cfg)
res.summary["h_score"], res.summary["dab_area_fraction_pct"]
res.cells.head()                      # per-cell table: x, y, area, DAB OD, hematoxylin OD, bin
res.labels                            # nucleus label image, if you want to compute anything else
```

Adding a new score is one function in `ihcq/metrics.py` that takes the
per-cell `bins` array (or the pixel arrays) — `h_score` and `allred` are the
templates.

## Limits, honestly

- Watershed segmentation is fine for round, well-separated nuclei at 20–40×.
  Crowded tumour, lymphoid tissue or spindle cells want `--backend stardist`.
- Cytoplasmic/membrane compartments are geometric rings around nuclei — an
  approximation, and cells without a visible nucleus are not counted.
- Whole slides: `load_image(..., max_side=N)` reads a pyramid level, but there
  is no tiling yet; analyse at a resolution where nuclei are ≥ 6 px across or
  export ROIs. Tiling with overlap is the next feature.
- Deconvolution assumes two stains. Double-IHC (DAB + red chromogen) needs a
  three-stain matrix — pass `stain_vectors` with three rows.
- Scores are research-use quantification. Validate against a pathologist on
  your own material before any claim.

## Tests

```bash
pytest tests -q
```

The tests build synthetic IHC fields with known per-cell truth through the
same optics the analysis inverts — plus noise, blur, uneven illumination and
hematoxylin quenching by DAB — and check that H-score, Allred, positivity,
area fraction, per-cell bin agreement and calibration are recovered.
