"""IHCq quits completely when its window closes or its launcher goes — and not on a reload."""
import os, socket, subprocess, sys, time, urllib.request as U
from pathlib import Path

import pytest

from ihcq.lifecycle import AFTER_CLOSE, AFTER_SILENCE, should_quit

ROOT = Path(__file__).resolve().parents[1]


def test_rule():
    assert should_quit(0, False, 0, True)[0] is False              # nobody has opened it yet: keep waiting
    q, seen, empty, closing = should_quit(1, False, 0, False); assert (q, seen, empty) == (False, True, 0)
    state = (True, 0, True)
    for k in range(AFTER_CLOSE):
        q, *state = should_quit(0, *state)
    assert q                                                        # closed tab: quit after a few checks
    q, *state = should_quit(1, True, 2, True); assert not q and state == [True, 0, True]    # still connected: no quit yet
    state = (True, 0, False)
    for k in range(AFTER_SILENCE - 1):
        q, *state = should_quit(0, *state); assert not q
    assert should_quit(0, *state)[0]                                # silent disconnect: quit after ~3 min


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def _start(env_extra=None):
    port = _free_port()
    code = ("import ihcq.lifecycle as L; L.CHECK_S = 0.25; L.AFTER_SILENCE = 400\n"
            f"from ihcq import app; app.main(open_browser=False, port={port})")
    env = dict(os.environ, **(env_extra or {}))
    p = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            U.urlopen(base + "/", timeout=1).read(); return p, base, port
        except OSError:
            time.sleep(0.1)
    p.kill(); pytest.fail("server did not start")


def _open_page(base):
    return U.urlopen(base + "/api/presence", timeout=5)            # what the page's EventSource holds open


def _beacon(base):
    U.urlopen(U.Request(base + "/api/closing", data=b"", method="POST"), timeout=2).read()


def _gone(p, port, within):
    try:
        p.wait(within)
    except subprocess.TimeoutExpired:
        return False
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0              # and nothing listens on the port


def test_closing_the_window_quits():
    p, base, port = _start()
    try:
        page = _open_page(base); page.read(4); time.sleep(0.6)
        _beacon(base); page.close()
        assert _gone(p, port, 6)
    finally:
        p.kill()


def test_reload_does_not_quit():
    p, base, port = _start()
    try:
        page = _open_page(base); page.read(4); time.sleep(0.6)
        _beacon(base); page.close()
        page = _open_page(base); page.read(4)                      # the reloaded page reconnects at once
        assert not _gone(p, port, 2.5)
        _beacon(base); page.close()
        assert _gone(p, port, 6)
    finally:
        p.kill()


def test_launcher_gone_quits():
    launcher = subprocess.Popen(["sleep", "60"])
    p, base, port = _start({"IHCQ_LAUNCHER_PID": str(launcher.pid)})
    try:
        page = _open_page(base); page.read(4)
        assert not _gone(p, port, 1)
        launcher.kill(); launcher.wait()                           # Dock force-quit is a SIGKILL
        assert _gone(p, port, 6)
    finally:
        p.kill(); launcher.kill()


def test_sigterm_and_quit_button():
    p, base, port = _start()
    try:
        p.terminate(); assert _gone(p, port, 6)
    finally:
        p.kill()
    p, base, port = _start()
    try:
        U.urlopen(U.Request(base + "/api/quit", data=b"", method="POST"), timeout=2).read()
        assert _gone(p, port, 6)
    finally:
        p.kill()


def test_output_folder_removed_on_quit():
    """Overlays, CSVs and reports live in a per-run temp folder; closing the window must delete it."""
    import tempfile
    tmp = Path(tempfile.gettempdir())
    before = set(tmp.glob("ihcq_*"))
    p, base, port = _start()
    try:
        page = _open_page(base); page.read(4)
        U.urlopen(base + "/api/demo?kind=low", timeout=60).read()
        mine = [d for d in set(tmp.glob("ihcq_*")) - before if any(d.iterdir())]
        assert len(mine) == 1                                       # found it, and it holds files: an empty find must fail
        _beacon(base); page.close()
        assert _gone(p, port, 8)
        assert not mine[0].exists()
    finally:
        p.kill()
