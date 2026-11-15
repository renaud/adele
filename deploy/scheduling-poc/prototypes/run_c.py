"""Run candidate C for 14 ticks and kill the scheduler once in the middle (SIGKILL, 20 s after
the 7th tick), then start it again 25 s later, as a service manager with Restart=always would.

    cd server && uv run python <this file> <run folder>
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

print("adele_server from:", common.use_copy(), flush=True)
root = Path(sys.argv[1]).resolve()
TICKS, KILL_AFTER_TICK, KILL_OFFSET, RESTART_OFFSET = 14, 6, 20, 45
if root.exists():
    shutil.rmtree(root)
common.build(root, fetch_timeout_s=180)
here = Path(__file__).resolve().parent
out = open(root / "kill_test.log", "w")


def say(msg: str) -> None:
    out.write(f"{common.stamp()} {msg}\n")
    out.flush()


def ps() -> str:
    text = subprocess.run(["ps", "-axo", "pid,ppid,pgid,etime,command"], capture_output=True, text=True).stdout
    keep = [ln for ln in text.splitlines() if str(root) in ln and "ps -axo" not in ln]
    return "\n".join("    " + ln.replace(str(root), "<run>").replace(str(here), "<proto>")[:230] for ln in keep)


def scheduler(ticks: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, str(here / "sched_c.py"), "--root", str(root), "--ticks", str(ticks),
                             "--cap", "3", "--rule", "slot"], stdout=out, stderr=subprocess.STDOUT)


first = scheduler(TICKS)
say(f"scheduler 1 started, pid {first.pid}")
events = root / "events.jsonl"
t0 = None
while t0 is None:
    time.sleep(0.5)
    if events.exists():
        for line in events.read_text().splitlines():
            e = json.loads(line)
            if e["event"] == "tick":
                t0 = e["planned"]
                break
say(f"first tick planned at {common.stamp(t0)}")
time.sleep(max(0, t0 + 60 * KILL_AFTER_TICK + KILL_OFFSET - time.time()))
say("processes of the run before the kill:\n" + ps())
os.kill(first.pid, signal.SIGKILL)
first.wait()
say(f"scheduler 1 killed with SIGKILL (exit status {first.returncode})")
time.sleep(3)
say("processes of the run 3 s after the kill:\n" + ps())
time.sleep(max(0, t0 + 60 * KILL_AFTER_TICK + RESTART_OFFSET - time.time()))
second = scheduler(TICKS - KILL_AFTER_TICK - 1)
say(f"scheduler 2 started, pid {second.pid}")
second.wait()
say(f"scheduler 2 ended (exit status {second.returncode})")
time.sleep(2)
say("processes of the run at the end:\n" + (ps() or "    none"))
print("done", flush=True)
