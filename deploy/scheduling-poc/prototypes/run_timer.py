"""Build a run folder and run timer_sim.py in one mode for 14 ticks.

    cd server && uv run python <this file> <run folder> today|lanes|overlap <second of the minute>
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

print("adele_server from:", common.use_copy(), flush=True)
root, mode, offset = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]
if root.exists():
    shutil.rmtree(root)
common.build(root, fetch_timeout_s=180)
here = Path(__file__).resolve().parent
with open(root / "timer_sim.out", "w") as out:
    rc = subprocess.run([sys.executable, str(here / "timer_sim.py"), "--root", str(root), "--ticks", "14", "--mode", mode, "--offset", offset],
                        stdout=out, stderr=subprocess.STDOUT).returncode
print("done", rc, flush=True)
