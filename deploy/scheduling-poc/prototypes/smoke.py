"""Smoke test: build a run folder, fetch each synthetic dataset once through the real CLI (short time limit)."""
import subprocess, sys, time, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
print("adele_server from:", common.use_copy())
root = Path(sys.argv[1]).resolve()
if root.exists():
    shutil.rmtree(root)
ds = dict(common.STANDARD); ds["slow"] = ("PT3M", "ok", 3)
cfg = common.build(root, ds, fetch_timeout_s=6)
env = common.child_env(root)
for name in ("fast", "failing", "slow", "hanging", "fast"):
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "adele_server.cli", "--config", str(cfg), "fetch", name], env=env, cwd=root, capture_output=True, text=True)
    print(f"== fetch {name}: rc={p.returncode} wall={time.perf_counter()-t:.2f}s\n   stdout: {p.stdout.strip()[:300]}\n   stderr(last): {p.stderr.strip().splitlines()[-1][:200] if p.stderr.strip() else ''}")
p = subprocess.run([sys.executable, "-m", "adele_server.cli", "--config", str(cfg), "fetch", "--due"], env=env, cwd=root, capture_output=True, text=True)
print("== fetch --due right after:", p.returncode, repr(p.stdout[:200]))
print((root / "fetch_calls.jsonl").read_text())
print(sorted(str(p.relative_to(root)) for p in (root / "data").rglob("*") if p.is_file()))
print("left in tmp:", sorted(p.name for p in (root / "tmp").iterdir()))
