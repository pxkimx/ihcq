import numpy as np
import pandas as pd
from ihcq import Config, analyze
from ihcq.synth import make_field


def _match(truth: pd.DataFrame, cells: pd.DataFrame, tol=6.0):
    """Pair each true nucleus with the nearest detected one; return matched bins."""
    from scipy.spatial import cKDTree
    t = cKDTree(cells[["y", "x"]].to_numpy())
    d, i = t.query(truth[["y", "x"]].to_numpy())
    ok = d < tol
    return truth["true_bin"].to_numpy()[ok], cells["bin"].to_numpy()[i[ok]], ok.mean()


def test_recovers_h_score_and_bins():
    rgb, truth, ts, _ = make_field(n_cells=350, fractions=(0.4, 0.2, 0.25, 0.15), seed=11)
    res = analyze(rgb, Config())
    s = res.summary
    assert abs(s["n_cells"] - ts["true_n_cells"]) <= 8
    assert abs(s["h_score"] - ts["true_h_score"]) < 6
    assert abs(s["pct_positive"] - ts["true_pct_positive"]) < 2.5
    tb, mb, recall = _match(truth, res.cells)
    assert recall > 0.97
    assert (tb == mb).mean() > 0.95          # per-cell bin agreement


def test_negative_control_is_negative():
    rgb, truth, ts, _ = make_field(n_cells=300, fractions=(1, 0, 0, 0), seed=5)
    s = analyze(rgb, Config()).summary
    assert s["h_score"] == 0.0 and s["pct_positive"] == 0.0
    assert s["dab_area_fraction_pct"] < 0.5


def test_area_fraction_tracks_truth():
    rgb, truth, ts, aux = make_field(n_cells=300, seed=7)
    cfg = Config()
    s = analyze(rgb, cfg).summary
    true_af = (aux["dab"][aux["tissue"]] >= cfg.thresholds.weak).mean() * 100
    assert abs(s["dab_area_fraction_pct"] - true_af) < 1.5


def test_membrane_compartment_and_no_segment():
    rgb, *_ = make_field(n_cells=200, seed=2, dab_cyto=0.8)
    a = analyze(rgb, Config(compartment="membrane"))
    assert a.summary["n_cells"] > 150 and a.score_labels.max() == a.labels.max()
    b = analyze(rgb, Config(segment=False))
    assert "n_cells" not in b.summary and b.summary["dab_area_fraction_pct"] > 0


def test_config_roundtrip(tmp_path):
    c = Config(compartment="membrane", mpp=0.25, profile_name="x")
    c.thresholds.strong = 0.9
    c.to_json(tmp_path / "p.json")
    d = Config.from_json(tmp_path / "p.json")
    assert d.compartment == "membrane" and d.mpp == 0.25 and d.thresholds.strong == 0.9 and d.profile_name == "x"


def test_qc_flags_saturation():
    rgb, *_ = make_field(n_cells=100, seed=1)
    rgb = rgb.copy(); rgb[100:300, 100:600] = 0
    res = analyze(rgb, Config())
    assert any("clipped" in f for f in res.qc)


def test_calibration_keeps_negative_control_negative(tmp_path):
    from PIL import Image
    from ihcq.calibrate import calibrate, fit_to_scores
    paths = {}
    for name, fr, seed in (("negative", (1, 0, 0, 0), 20), ("weak", (0.5, 0.5, 0, 0), 21),
                           ("moderate", (0.5, 0, 0.5, 0), 22), ("strong", (0.5, 0, 0, 0.5), 23)):
        rgb, *_ = make_field(n_cells=250, fractions=fr, seed=seed)
        p = tmp_path / f"{name}.png"; Image.fromarray(rgb).save(p); paths[name] = [str(p)]
    cfg, table = calibrate(paths, name="t")
    th = cfg.thresholds
    assert 0.06 <= th.weak < 0.2 and th.weak < th.moderate < th.strong
    neg = analyze(np.array(Image.open(paths["negative"][0]).convert("RGB")), cfg).summary
    assert neg["pct_positive"] < 1.0
    strong = analyze(np.array(Image.open(paths["strong"][0]).convert("RGB")), cfg).summary
    assert strong["pct_3plus"] > 40

    # fit-to-scores should land near the truth from four scored fields
    rows = []
    for name, fr, seed in (("a", (0.4, 0.2, 0.25, 0.15), 30), ("b", (0.8, 0.1, 0.1, 0), 31),
                           ("c", (0.1, 0.1, 0.3, 0.5), 32), ("d", (1, 0, 0, 0), 33)):
        rgb, truth, ts, _ = make_field(n_cells=250, fractions=fr, seed=seed)
        p = tmp_path / f"s_{name}.png"; Image.fromarray(rgb).save(p)
        rows.append({"image": str(p), "h_score": ts["true_h_score"]})
    cfg2, tab = fit_to_scores(pd.DataFrame(rows), grid_step=0.1)
    assert tab["abs_error"].mean() < 8
