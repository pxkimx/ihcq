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
