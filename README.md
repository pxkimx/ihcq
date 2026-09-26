# IHCq — chromogenic IHC quantification

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
```

**StarDist backend — use a separate environment.** TensorFlow drags in
NumPy 2 and a Keras build that segfaults next to packages compiled against
NumPy 1.x, which is what a typical Anaconda base carries. Don't install it
into base; give it its own env:

```bash
python3 -m venv .venv-dl                      # inside the project; any Python ≥3.9 works
.venv-dl/bin/pip install "numpy>=2,<2.3" scipy scikit-image pandas pillow tifffile "tensorflow>=2.16" stardist
.venv-dl/bin/pip install -e . --no-deps
.venv-dl/bin/ihcq score fields/*.png --backend stardist -o results.csv
```

(A conda env works the same way if your conda is healthy; a plain venv has
fewer moving parts.)

The classical backend needs none of this and runs anywhere the core installs.

## The desktop app

The interface follows Apple's design language: system typography, one accent colour, quiet grouped surfaces, translucent toolbars, and colour reserved for data (the four bin colours). It follows the system light/dark setting.

```bash
ihcq app                    # opens http://127.0.0.1:8765 in your browser
```

`IHCq.app` on the Desktop (rebuild with `scripts/build_app.sh`) launches
the same thing with a click. It is a local server on the loopback
interface; nothing leaves the machine. What it does:

- **Score** — drop any number of images (a queue with per-file status), or
  open the built-in demo: a real colon field with membranous DAB, or
  synthetic fields with known truth. Presets for nuclear, membrane,
  cytoplasmic and pixel-only markers; every setting exposed; **Re-analyze**
  re-runs the current image when you change compartment, finder, scale or
  statistic. Results as colour-coded tiles, a stain-identity badge, and QC
  flags.
- **Viewer** — original / labelled nuclei / positivity / positive-density
  heat layers with opacity, scroll-zoom (never below fit) and drag-pan,
  hover on any nucleus for its bin and ODs, a hotspot marker, and ROI
  include/exclude polygons with *Score inside ROI*.
- **Regions** — draw several ＋ ROIs and *Compare regions* scores each one
  separately (nuclei, % positive with 95 % CI, H-score, IRS, 3+ %, DAB area,
  density), with a Fisher exact test when there are two — e.g. invasive
  margin vs tumour centre. On the demo, nest vs stroma: 93.1 % (CI 78–98)
  vs 0 % (CI 0–14), p < 0.001.
- **Stain & white point eyedroppers** — click bare glass, a blue negative
  nucleus and solid brown staining; IHCq computes the OD vectors from a 9×9
  median, reports the angle to the textbook vector, and uses them on
  re-analysis. Saved profiles carry them, so a calibration is done once.
- **Apply settings to all images** — re-analyzes every image in the session
  with the current settings, cut points and stain vectors.
- **Cell table** — every nucleus with bin, DAB and hematoxylin OD, area and
  position; sortable, filterable by bin, and clicking a row flies the viewer
  to that nucleus.
- **Live cut points** — a per-cell DAB histogram with three draggable cut
  points; H-score, % positive, Allred and the bin composition update as you
  drag; *Apply* re-bins the image and its overlays.
- **Downloads** — original, labelled-nuclei overlay, positivity map and
  stain-separation panels as separate PNGs; per-cell and session CSVs;
  profile JSON to reuse with `ihcq score --profile`.
- **Session** — sortable table, bin-composition and H-score plots per
  image, copy as TSV. Give images a **group** to unlock *Compare groups*
  (box + strip plots; Welch t-test, Mann–Whitney, Cohen's d for two groups;
  ANOVA and Kruskal–Wallis with Bonferroni-corrected pairwise tests for
  more) and *Correlate* (scatter with Pearson and Spearman).
- **PDF report** — cover table, one page per image with all four panels,
  metrics, flags and its DAB histogram, a between-group statistics page, and
  a methods page.
- **Calibrate** — mark scored images as negative / 1+ / 2+ / 3+ controls,
  fit the cut points, apply them to everything scored so far.

The launcher uses `.venv-dl` when it exists (hybrid and StarDist finders
available in the menu); otherwise the base Python and the classical finder.
Logs go to `~/Library/Logs/ihcq.log`; *Quit* stops the server.

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
| `irs_ps / _is / irs` | Remmele–Stegner immunoreactive score: proportion 0–3 × intensity 0–3 = 0–12 |
| `pct_positive_ci95` | Wilson 95 % interval on % positive — the counting uncertainty (18 % of 150 cells is 12–25 %) |
| `hotspot_pct_positive`, `coldspot_…`, `hotspot_xy` | highest / lowest positive fraction among neighbourhoods of the nearest *k* cells (k = min(500, ¼ of the cells)); the IKWG hotspot counts ≥500 |
| `cells_per_mm2`, `positive_cells_per_mm2` | with `--mpp` |

Nuclei are found on the hematoxylin channel after background flattening,
so faintly counterstained nuclei on a tinted field are still detected; the
threshold is sampled from DAB-free pixels so chromogen crosstalk cannot push
pale negative nuclei below the cut; strongly stained nuclei that quenched
their counterstain are recovered by a shape test on compact DAB blobs. Each
nucleus is scored on its 1-px-eroded core so the mask's rim of pale membrane
does not dilute the intensity.

**Tell it the scale.** The nuclear radius sets the background flattening
and the seed spacing. Pass `--mpp` (microns per pixel, from your scanner —
the radius is taken as 4 µm) or `--radius` in pixels; otherwise 8 px is
assumed, which suits 20× at ~0.5 µm/px. It is deliberately *not* estimated
from the image: every cheap estimator is fooled either by fragmented large
nuclei or by merged clusters, and a wrong guess silently halves or doubles
the cell count. The summary reports `median_nucleus_radius_px` next to the
assumed value and flags a gross mismatch.

The **compartment** is where DAB is read for each cell: `nuclear` (Ki-67, ER,
PR, p53), `membrane` (a ring outside the nucleus — HER2, PD-L1, EGFR),
`cytoplasm` (a wider band) or `cell` (nucleus plus band — QuPath's "Cell"
compartment, which QuPath recommends for diffuse cytoplasmic staining). The per-cell summary statistic is the mean by
default; `p90` is more faithful for punctate or membranous staining.

### Pixel level (no nuclei needed, `--no-segment` for stroma, ECM, secreted markers)

| output | definition |
|---|---|
| `dab_area_fraction_pct` | tissue pixels with DAB OD ≥ weak cut ÷ all tissue pixels |
| `pct_px_1plus` … | tissue pixels in each intensity bin |
| `pixel_h_score` | same arithmetic as H-score, over pixels instead of cells |
| `profiler_zone` | four-tier pixel call in the spirit of IHC Profiler (Varghese 2014): the intensity zone holding most stained pixels |
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

## How well does it work? (public data)

Evaluated against the **DeepLIIF** breast-cancer Ki-67 validation set
(Ghahremani et al. 2022, CC-BY 4.0; `scripts/eval_deepliif.py`): 66 fields
at 40×, six distinct tissue regions with flipped/rotated copies, each with a
nucleus mask marking positive and negative cells derived from *multiplex
immunofluorescence* — an independent modality, not a re-reading of the DAB.
Default settings, no calibration, no training:

| metric | value |
|---|---|
| nuclei detected vs truth | 10,919 vs 9,141 |
| detection recall / precision (centroid within 10 px) | 0.77 / 0.65 |
| positive-vs-negative agreement on matched nuclei | 96.1 % |
| Ki-67 index, mean absolute error | 5.3 percentage points |
| Ki-67 index, Pearson r across fields | 0.97 |

**Three nucleus finders, same truth:**

| backend | recall | precision | pos/neg agreement | Ki-67 index MAE | bias |
|---|---|---|---|---|---|
| `watershed` (classical, default) | 0.77 | 0.65 | 96.1 % | 5.3 pp | +4.4 |
| `stardist` (pretrained H&E model, p = 0.35) | 0.65 | 0.89 | 99.2 % | 18.9 pp | +18 |
| `hybrid` (StarDist, then classical for what it missed) | **0.82** | 0.71 | 96.9 % | **5.2 pp** | **+3.0** |

StarDist alone is the most *precise* — what it outlines is a nucleus — and
on well-counterstained fields it beats the classical detector outright
(recall 0.91–0.93 on regions 22 and 31). But it was trained on H&E and is
blind to the ghost-pale negatives of regions 40 and 7 (recall 0.3–0.5),
which is exactly where the Ki-67 index goes wrong. The hybrid keeps
StarDist's outlines and adds classical detections it has no match for; it is
the best overall and the recommended backend when the `.venv-dl` environment
is available. The classical default needs no model and is within a point of
it on this set.

Per region, classical, truth vs measured Ki-67 index: 6.1 → 5.2 %, 8.5 → 8.3 %,
13.6 → 19.2 %, 34.7 → 33.4 %, 36.5 → 43.3 %, 48.3 → 65.0 %. The two that
miss are instructive. Region 40's negative nuclei are ghost-pale and sit in
heavy brown cytoplasm; the truth there comes from DAPI and includes nuclei
that are barely visible in the IHC — a recall limit of the classical
watershed, and the reason the StarDist backend exists. Region 326 has
nuclei twice the radius of the rest of the set (≈16 px); at the default
8 px they fragment (125 objects for 34 nuclei), and `--radius 16` brings
that to 58 — better, not fixed, because those large pale nuclei have
internal texture that also splits a distance-transform watershed.

### Membrane scoring against HER2 labels (BCI)

**BCI** (Liu et al. 2022; non-commercial licence) has 977 test patches of
HER2 IHC at 1024², each carrying its *slide's* pathologist score — so a
tumour-free patch cut from a 3+ slide is labelled 3+. That makes patch-level
agreement a lower bound; what a correct membrane score must show is a clean,
monotonic trend across classes. Membrane compartment, 90th-percentile cell
statistic, default cut points, no calibration:

| HER2 class | n | % positive cells (median) | % cells ≥ 2+ | H-score | DAB area % |
|---|---|---|---|---|---|
| 0 | 38 | 2.1 | 0.0 | 2 | 2.3 |
| 1+ | 235 | 5.9 | 0.0 | 6 | 4.6 |
| 2+ | 446 | 14.8 | 0.0 | 16 | 11.1 |
| 3+ | 258 | 40.7 | 7.3 | 58 | 25.0 |

All 977 patches pass the stain check as DAB. Threshold-free separation by
`% cells ≥ 2+`: 3+ vs the rest AUC 0.84, 2+ vs 3+ 0.81, HER2-negative
(0/1+) vs positive (2+/3+) 0.74, and 0 vs 1+ only 0.59 — the low end is
where a slide-level label says least about one patch (by the tool's own
count, 61 % of "0" patches and 37 % of "1+" patches have under 3 % positive
cells, i.e. little or no tumour in the field). The hybrid backend gives the
same numbers within noise (AUC 0.83 / 0.80 / 0.73): on this material the
nucleus finder is not the limiting factor.

**Calibrating to this scanner.** Fitting the three cut points on the
even-numbered patches (`scripts/bci_calibrate.py`) gives 0.12 / 0.20 / 0.36
— about half the DeepLIIF-era defaults, because this material is scanned
paler — and on the odd-numbered patches raises balanced accuracy from 0.28
to 0.48, exact agreement from 0.15 to 0.43 and HER2-negative-vs-positive
agreement from 0.39 to 0.60, with rank agreement unchanged (Spearman ≈ 0.42,
as re-binning cannot change ranks). One caution learned the hard way: fit
to *balanced* accuracy. Maximising exact accuracy on these labels returns
cut points of 0.04 / 0.08 that call nearly every patch "2+" — the majority
class — and looks better while measuring nothing.

Two things this evaluation cannot do, and says so: it has no tumour/stroma
distinction, so percentages are over *all* cells and stroma dilutes them
(an ASCO/CAP score is over tumour cells); and it cannot separate label
noise from scoring error without slide identifiers, which BCI does not
publish.

### Stain vectors: textbook beats fitted here

`--fit-stains` fits the two stain vectors to each image (Macenko) instead of
using the textbook values. On DeepLIIF it *ranks* fields better (r 0.972 →
0.987) but shifts the OD scale, so the cut points no longer mean the same
thing: Ki-67 index error rises from 5.3 to 11.0 pp, and even with the cut
point refitted on half the fields the held-out error is 7.5 pp against
4.6 pp for textbook vectors with default cuts. It stays off by default; use
it only where brown visibly bleeds into the hematoxylin panel, and
recalibrate afterwards.

### Scoring inside a region

Every serious IHC workflow scores tumour, not the whole field. In the app,
draw include (＋ ROI) and exclude (－ Exclude) polygons on the viewer; cells
count by centroid, pixels by mask, and every ROI and re-bin is derived from
the full-field result rather than from the previous one. On the colon demo:
full field 64.7 % positive (H 145); one epithelial nest 93 % (H 200); pure
stroma 0 %.

### Handing it the wrong stain (H&E)

Tested on **HERE101** (101 pathologist-annotated H&E fields, 25 tissue
sites). An IHC tool given H&E should say so, not invent a score. Eosin is
not orthogonal to DAB, so a purely eosinophilic field can read as heavily
"positive" (skeletal muscle: 81 % of cells, 51 % DAB area). Every image is
therefore checked: the two dominant stain vectors are fitted and the second
is compared with DAB and eosin. On all 101 H&E fields it lies 9–30° from
eosin; on every DAB field tested, 2–19° from DAB. The result is written to
`second_stain` and `scores_valid`, and an H&E field carries a loud QC flag
— 100 of 101 were caught; the last has 2.8 % spurious positivity. Two
honest gaps: **melanin** is genuinely brown and reads as "unrecognised",
not as DAB, so it is flagged but not identified; and a *fully negative* IHC
field has no second stain to fit and reads "unknown" with ~0 % DAB area,
which is correct and unflagged.

What *is* valid on H&E — nucleus count, `cells_per_mm2`,
`mean_nucleus_area`, `nuclear_area_fraction_pct` — is reported regardless.
On HERE101 the classical and hybrid finders agree on counts (r = 0.98) and
nuclear density follows biology: tumour fields are less dense than normal
ones because their nuclei are larger.

Two scikit-image / DeepLIIF sample images with membranous and nuclear
staining are in `data/public/` and are scored in `results/final/`.

## QC you get for free

Every scored image can write three PNGs (`--overlays DIR`):

- `*_cells.png` — nuclei outlined in bin colour (blue 0, yellow 1+, orange 2+, red 3+); membrane rings drawn when that compartment is used
- `*_positivity.png` — every tissue pixel painted by its bin: the picture behind the area fraction
- `*_stains.png` — original | hematoxylin only | DAB only: proves the deconvolution separated your stains

And every result row carries `qc_flags`: clipped pixels (over-exposed scan),
too little tissue, too few cells for a stable H-score, chromogen saturation,
uncalibrated thresholds, **no glass in the field** (the white point had to be
assumed — pass `--white R G B` measured on a blank area of the slide), and a
**compartment hint** when most DAB+ pixels lie outside the nuclei (a
membranous or cytoplasmic stain scored as nuclear, or vice versa).

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

- No nucleus finder here fully recovers ghost-pale negatives next to heavy
  brown cytoplasm (regions 40 and 7 in the evaluation). `--backend hybrid`
  is the best available; the rest of the pipeline is identical across
  backends, so a better segmenter drops straight in.
- Cytoplasmic/membrane compartments are geometric rings around nuclei — an
  approximation, and cells without a visible nucleus are not counted.
- Whole slides: `load_image(..., max_side=N)` reads a pyramid level, but there
  is no tiling yet; analyse at a resolution where nuclei are ≥ 6 px across or
  export ROIs. Tiling with overlap is the next feature.
- Deconvolution assumes two stains. Double-IHC (DAB + red chromogen) needs a
  three-stain matrix — pass `stain_vectors` with three rows.
- Melanin, hemosiderin and some red chromogens are not DAB but are not eosin
  either; they are flagged "unrecognised", and the DAB scores on such a field
  should be treated as invalid until you have looked at the stain overlay.
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
