"""End-to-end tests of the local server: every endpoint the UI uses."""
import io, json, threading, time, urllib.request as U
from http.server import ThreadingHTTPServer
import numpy as np
import pytest
from PIL import Image

from ihcq import app
from ihcq.synth import make_field


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    app.SESSION["server"] = srv
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(b, p): return json.loads(U.urlopen(b + p).read())
def post(b, p, body=b""):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return json.loads(U.urlopen(U.Request(b + p, data=data, method="POST")).read())
def png(rgb):
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, "PNG"); return buf.getvalue()


def test_score_rebin_roi_regions(server):
    rgb, truth, ts, _ = make_field(n_cells=200, fractions=(0.5, 0.2, 0.2, 0.1), seed=3, size=(384, 512))
    j = post(server, "/api/score?name=t", png(rgb)); s = j["summary"]
    assert abs(s["h_score"] - ts["true_h_score"]) < 12 and len(j["cells"]) == s["n_cells"]
    r = post(server, f"/api/rebin?id={j['id']}&weak=0.3&moderate=0.6&strong=0.9")
    assert r["summary"]["pct_positive"] < s["pct_positive"] and r["summary"]["thr_weak"] == 0.3
    half = [[0, 0], [256, 0], [256, 384], [0, 384]]
    a = post(server, f"/api/roi?id={j['id']}", {"include": [half]})["summary"]
    assert 0 < a["n_cells"] < s["n_cells"] and a["roi_fraction"] < 0.8
    g = post(server, f"/api/regions?id={j['id']}", {"include": [half, [[256, 0], [512, 0], [512, 384], [256, 384]]]})
    assert len(g["regions"]) == 2 and g["test"] is not None
    b = post(server, f"/api/roi?id={j['id']}", {"include": [], "exclude": []})["summary"]
    assert b["n_cells"] == s["n_cells"]                      # clearing restores the full field


def test_membrane_her2_and_classifier(server):
    rgb, *_ = make_field(n_cells=180, fractions=(0.3, 0.0, 0.0, 0.7), seed=5, size=(384, 512), dab_cyto=0.9)
    j = post(server, "/api/score?name=m&compartment=membrane&statistic=p90", png(rgb)); s = j["summary"]
    assert s["her2_score"] in ("2+", "3+") and s["pct_complete_any"] > 10
    cells = j["cells"]; pos = [c[:2] for c in cells if c[7] == 2][:6]; neg = [c[:2] for c in cells if c[7] == 0][:6]
    k = post(server, f"/api/classify?id={j['id']}", {"tumour": pos, "stroma": neg})
    assert k["summary"]["scored_population"] == "tumour-like cells" and k["classifier"]["clicks_matched"] == [len(pos), len(neg)]
    r = post(server, f"/api/rebin?id={j['id']}&weak=0.12&moderate=0.3&strong=0.6")["summary"]
    assert r["her2_score"] is not None and r["scored_population"] == "tumour-like cells"   # survives re-binning


def test_negative_membrane_field_scores_zero(server):
    rgb, *_ = make_field(n_cells=150, fractions=(1, 0, 0, 0), seed=6, size=(384, 512))
    s = post(server, "/api/score?name=neg&compartment=membrane&statistic=p90", png(rgb))["summary"]
    assert s["her2_score"] == "0"


def test_project_roundtrip(server):
    rgb, *_ = make_field(n_cells=150, seed=8, size=(384, 512))
    j = post(server, "/api/score?name=proj", png(rgb))
    post(server, f"/api/rebin?id={j['id']}&weak=0.12&moderate=0.3&strong=0.6")
    post(server, "/api/group", {"id": j["id"], "group": "treated"})
    a = post(server, f"/api/roi?id={j['id']}", {"include": [[[0, 0], [300, 0], [300, 384], [0, 384]]]})["summary"]
    blob = U.urlopen(server + "/api/project/save").read()
    app.SESSION["cache"].clear()                                  # simulate a restart: nothing cached
    d = post(server, "/api/project/open", blob)
    got = [r["summary"] for r in d["results"] if r["summary"]["image"] == "proj"][-1]
    assert not d["mismatches"] and got["h_score"] == a["h_score"] and got["n_cells"] == a["n_cells"] and got["group"] == "treated"


def test_slide_job(server, tmp_path):
    import tifffile
    rgb, *_ = make_field(n_cells=600, seed=9, size=(1536, 2048))
    p = tmp_path / "s.svs"
    with tifffile.TiffWriter(p, bigtiff=True) as tw:
        tw.write(rgb, tile=(256, 256), photometric="rgb", subifds=1, description="Aperio test|MPP = 0.5")
        tw.write(rgb[::4, ::4].copy(), tile=(256, 256), photometric="rgb", subfiletype=1)
    d = post(server, "/api/slide?name=s.svs", p.read_bytes())
    for _ in range(240):
        time.sleep(0.5); jb = get(server, "/api/job?id=" + d["job"])
        if jb["state"] != "running": break
    assert jb["state"] == "done", jb.get("error")
    s = jb["result"]["summary"]
    assert s["image"] == "s" and s["mpp"] == 0.5 and s["tiles_analyzed"] >= 1
    from ihcq import Config, analyze
    direct = analyze(rgb, Config(mpp=0.5, white_point=s["white_point"])).summary
    assert abs(s["n_cells"] - direct["n_cells"]) <= 0.01 * direct["n_cells"]        # slide plumbing == direct analysis
    assert abs(s["pct_positive"] - direct["pct_positive"]) < 1.0


def test_measure_regions(server):
    """Traced media / adventitia ring: exact areas, additive nuclei, no false overlap on the shared edge."""
    import math
    rgb, *_ = make_field(n_cells=450, seed=12, size=(768, 1024))
    rid = post(server, "/api/score?name=vessel", png(rgb))["id"]
    circ = lambda r, n=720: [[512 + r * math.cos(2 * math.pi * k / n), 384 + r * math.sin(2 * math.pi * k / n)] for k in range(n)]
    sq = [[20, 20], [120, 20], [120, 120], [20, 120]]
    regs = [{"name": "Adventitia", "include": [circ(250)], "exclude": [circ(180)]},
            {"name": "Media", "include": [circ(180)], "exclude": [circ(120)]},
            {"name": "Square", "include": [sq]}]
    m = post(server, f"/api/measure?id={rid}", json.dumps({"regions": regs, "mpp": 0.5}).encode())
    r = {x["name"]: x for x in m["regions"]}
    assert r["Square"]["area_px"] == 10000 and r["Square"]["perimeter_px"] == 400
    assert abs(r["Media"]["area_px"] / (math.pi * (180**2 - 120**2)) - 1) < 0.002
    assert abs(r["Adventitia"]["area_um2"] / (0.25 * math.pi * (250**2 - 180**2)) - 1) < 0.002
    ratio = next(x for x in m["ratios"] if x["a"] == "Adventitia" and x["b"] == "Media")["area_ratio"]
    assert abs(ratio - 1.6722) < 0.005
    assert m["overlaps"] == []
    whole = post(server, f"/api/measure?id={rid}", json.dumps({"regions": [{"name": "All", "include": [circ(250)], "exclude": [circ(120)]}]}).encode())
    assert whole["regions"][0]["nuclei"] == r["Media"]["nuclei"] + r["Adventitia"]["nuclei"]
