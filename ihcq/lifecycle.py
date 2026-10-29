"""Quit completely when the app's window is closed.

IHCq is a local server whose window is a browser tab. Left alone, the server keeps
running after the tab is closed. This module ends the two together:

* Every open page holds one event stream (``/api/presence``) open, so the server knows
  how many pages are connected. As a page goes away it sends a beacon
  (``/api/closing``). If no page is connected a few seconds later, the server stops.
  A reload reconnects within that time, so it does not stop the app.
* If no page has been connected for three minutes and no beacon came (the browser
  crashed or was force-quit), the server stops as well.
* If the launcher that started the server is gone (the app was quit or force-quit
  from the Dock), the server stops.
* Whatever the reason, whole-slide worker processes are stopped with it; each worker
  also exits on its own if the server disappears without cleaning up.

Checks are counted, not timed by the clock, so waking the Mac from sleep does not
count as a long silence.
"""
from __future__ import annotations

import multiprocessing
import os
import signal
import sys
import threading
import time

CHECK_S = 2.0            # how often the server looks at who is connected
AFTER_CLOSE = 3          # checks with nobody connected after a page said it was closing (about 6 s)
AFTER_SILENCE = 90       # checks with nobody connected and no such message (about 3 min)
LAUNCHER_ENV = "IHCQ_LAUNCHER_PID"

_lock = threading.Lock()
_state = {"connected": 0, "closing": False, "started": False, "server": None}


def _log(text: str) -> None:
    print(f"[{time.strftime('%F %T')}] {text}", file=sys.stderr, flush=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def should_quit(connected: int, seen: bool, empty: int, closing: bool) -> tuple:
    """One step of the rule. Returns (quit now?, seen, empty checks, closing)."""
    if connected > 0:              # the closing page's beacon can land before its stream drops,
        return False, True, 0, closing   # so only a newly opened page (a reload) clears "closing"
    if not seen:                                           # nobody has opened the app yet
        return False, False, 0, closing
    empty += 1
    return (closing and empty >= AFTER_CLOSE) or empty >= AFTER_SILENCE, True, empty, closing


# ---- called by the HTTP handler ------------------------------------------------------

def page_opened() -> None:
    with _lock:
        _state["connected"] += 1
        _state["closing"] = False


def page_closed() -> None:
    with _lock:
        _state["connected"] = max(0, _state["connected"] - 1)


def page_closing() -> None:
    _state["closing"] = True


# ---- stopping -----------------------------------------------------------------------

def stop_children() -> None:
    """Stop every worker process this server started (the whole-slide tile pool)."""
    kids = multiprocessing.active_children()
    for p in kids:
        p.terminate()
    for p in kids:
        p.join(2)
        if p.is_alive():
            p.kill()


def quit_now(reason: str) -> None:
    _log(f"quitting: {reason}")
    stop_children()
    srv = _state["server"]
    if srv is not None:
        threading.Thread(target=srv.shutdown, daemon=True).start()
    time.sleep(3)
    os._exit(0)                                            # do not wait on pool bookkeeping at interpreter exit


def _watch() -> None:
    launcher = int(os.environ.get(LAUNCHER_ENV, "0") or 0)
    seen, empty = False, 0
    while True:
        time.sleep(CHECK_S)
        if launcher and not _alive(launcher):
            quit_now("the launcher was closed")
        stop, seen, empty, closing = should_quit(_state["connected"], seen, empty, _state["closing"])
        _state["closing"] = closing
        if stop:
            quit_now("its window was closed" if closing else "no window has been connected for three minutes")


def start(server) -> None:
    """Start watching (once per process) and stop cleanly on SIGTERM / SIGHUP."""
    with _lock:
        _state["server"] = server
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_watch, daemon=True, name="ihcq-lifecycle").start()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: threading.Thread(target=quit_now, args=("stopped by a signal",), daemon=True).start())


def die_with_parent(parent: int | None = None) -> None:
    """For a worker process: exit if the server that started it disappears, however it went.

    Pass the server's pid: a worker still starting up when the server is killed would
    otherwise record the process it was handed to (launchd) as its parent."""
    parent = parent or os.getppid()
    if not _alive(parent) or os.getppid() != parent:
        os._exit(1)

    def watch():
        while True:
            time.sleep(CHECK_S)
            if os.getppid() != parent:
                os._exit(1)

    threading.Thread(target=watch, daemon=True).start()
