import numpy as np
from ihcq.stains import stain_matrix, rgb_to_od, od_to_rgb, deconvolve, estimate_white, estimate_stain_vectors


def test_od_roundtrip():
    rgb = np.random.default_rng(0).integers(0, 256, (8, 8, 3)).astype(np.uint8)
    back = od_to_rgb(rgb_to_od(rgb, 255.0), 255.0)
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


def test_pure_stains_separate():
    m = stain_matrix()
    for which in (0, 1):
        conc = np.zeros((4, 4, 3)); conc[..., which] = 0.7
        od = conc.reshape(-1, 3) @ m
        rgb = od_to_rgb(od.reshape(4, 4, 3), 255.0)
        got = deconvolve(rgb, m, 255.0)
        assert abs(got[..., which].mean() - 0.7) < 0.03
        other = 1 - which
        assert got[..., other].mean() < 0.03


def test_matches_skimage_hed_direction():
    # skimage's rgb2hed uses the same Ruifrok vectors; our DAB channel should
    # rank pixels identically to theirs.
    from skimage.color import rgb2hed
    rng = np.random.default_rng(1)
    m = stain_matrix()
    conc = np.zeros((32, 32, 3)); conc[..., 0] = rng.uniform(0, .8, (32, 32)); conc[..., 1] = rng.uniform(0, 1.2, (32, 32))
    rgb = od_to_rgb((conc.reshape(-1, 3) @ m).reshape(32, 32, 3), 255.0)
    ours = deconvolve(rgb, m, 255.0)[..., 1].ravel()
    theirs = rgb2hed(rgb)[..., 2].ravel()
    assert np.corrcoef(ours, theirs)[0, 1] > 0.99


def test_white_point_estimate():
    rgb = np.full((50, 50, 3), 120, np.uint8)
    rgb[:10] = (243, 241, 238)          # glass
    w = estimate_white(rgb)
    assert np.allclose(w, (243, 241, 238), atol=1)


def test_macenko_recovers_vectors():
    from ihcq.synth import make_field
    rgb, *_ = make_field(n_cells=300, seed=3)
    m = estimate_stain_vectors(rgb)
    ref = stain_matrix()
    # cosine similarity between fitted and textbook vectors
    for i in (0, 1):
        assert float(m[i] @ ref[i]) > 0.97
