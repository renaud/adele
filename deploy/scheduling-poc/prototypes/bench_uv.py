"""fetch_window of a dataset whose fetch.py has a PEP 723 block: the real path through `uv run --script`."""
import json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
print("adele_server from:", common.use_copy())
from adele_server import config as config_mod, ingest, state
from adele_server.catalog import load_catalog
root = Path(sys.argv[1]).resolve()
if root.exists():
    shutil.rmtree(root)
cfg_path = common.build(root, {"fast": ("PT1M", "ok", 0)}, fetch_timeout_s=120, pep723=("fast",))
env = common.child_env(root)
os.environ.update({k: env[k] for k in ("TMPDIR", "ADELE_POC_LOG")})
cfg = config_mod.load(cfg_path)
catalog = load_catalog(cfg.datasets_dirs)
ds = catalog["fast"]
print("script block found:", ds.script_metadata)
for i in range(3):
    t = time.perf_counter()
    o = ingest.fetch_window(cfg, catalog, ds, *ingest.scheduled_window(ds, state.now()))
    print(f"fetch {i + 1}: ok={o.ok} {time.perf_counter() - t:.2f} s {o.error or ''}")
calls = [json.loads(l) for l in (root / "fetch_calls.jsonl").read_text().splitlines()]
prefixes = [c["prefix"] for c in calls if c["event"] == "fetch_start"]
print("environment of each fetch.py:")
for p in prefixes:
    print("  ", p)
(root / "uv_envs.txt").write_text("\n".join(prefixes) + "\n")
