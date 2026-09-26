import numpy as np
from ihcq.config import Thresholds
from ihcq.metrics import bin_intensity, h_score, allred


def test_bins():
    th = Thresholds(0.15, 0.4, 0.8)
    assert list(bin_intensity(np.array([0.0, 0.149, 0.15, 0.39, 0.4, 0.79, 0.8, 2.0]), th)) == [0, 0, 1, 1, 2, 2, 3, 3]


def test_h_score_range_and_definition():
    assert h_score(np.zeros(10)) == 0.0
    assert h_score(np.full(10, 3)) == 300.0
    # 50% 1+, 25% 2+, 25% 3+ → 50 + 50 + 75 = 175
    b = np.array([1] * 2 + [2] + [3])
    assert h_score(b) == 175.0
    assert np.isnan(h_score(np.array([])))


def test_allred():
    assert allred(np.zeros(100))["allred_total"] == 0
    r = allred(np.array([3] * 80 + [0] * 20))       # 80% positive (PS 5), all strong (IS 3)
    assert (r["allred_ps"], r["allred_is"], r["allred_total"]) == (5, 3, 8)
    r = allred(np.array([1] * 5 + [0] * 95))        # 5% weak → PS 2, IS 1
    assert (r["allred_ps"], r["allred_is"], r["allred_total"]) == (2, 1, 3)


def test_irs_and_profiler_and_hotspot():
    from ihcq.metrics import irs, profiler_score, hotspot
    import pandas as pd
    assert irs(np.zeros(20))["irs"] == 0
    r = irs(np.array([3] * 60 + [0] * 40))             # 60 % positive → PS 3, all strong → IS 3 → 9
    assert (r["irs_ps"], r["irs_is"], r["irs"]) == (3, 3, 9)
    assert profiler_score(np.zeros(100))["profiler_zone"] == "negative"
    assert profiler_score(np.array([0] * 50 + [2] * 40 + [3] * 10))["profiler_zone"] == "positive"
    rng = np.random.default_rng(0); n = 800
    x = rng.uniform(0, 1000, n); y = rng.uniform(0, 1000, n)
    b = ((x < 300) & (y < 300)).astype(int) * 3     # a positive corner
    h = hotspot(pd.DataFrame({"x": x, "y": y, "bin": b}), window_cells=40)
    assert h["hotspot_pct_positive"] > 85 and h["coldspot_pct_positive"] < 5 and h["hotspot_xy"][0] < 400


def test_wilson_interval():
    from ihcq.metrics import wilson
    lo, hi = wilson(27, 150)           # 18 % of 150
    assert 0.12 < lo < 0.13 and 0.24 < hi < 0.26
    lo, hi = wilson(0, 40)
    assert lo == 0.0 and 0.08 < hi < 0.10
