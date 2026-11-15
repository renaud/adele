"""Server configuration: one TOML file (see adele-server.example.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = "adele-server.toml"


@dataclass
class QueryLimits:
    max_rows: int = 100
    timeout_s: float = 30.0
    memory_limit: str = "2GB"
    threads: int = 4


@dataclass
class Config:
    path: Path
    datasets_dirs: list[Path]  # each: one dataset folder, or a folder of dataset folders
    data_dir: Path
    log_dir: Path
    env_file: Path | None
    admin_email: str | None
    keys: dict[str, str]  # key name (team member) --> API key
    query: QueryLimits = field(default_factory=QueryLimits)
    fetch_timeout_s: float = 1800.0  # per call of fetch(start, end); a hung source must not go unnoticed
    cache_dir: Path | None = None  # files that the server can write again (the uv runners); see cache_path

    @property
    def datasets_dir(self) -> Path:
        """The first entry of datasets_dirs (configs and tests with a single folder)."""
        return self.datasets_dirs[0]

    @property
    def cache_path(self) -> Path:
        """`cache_dir` of the config, else $CACHE_DIRECTORY (systemd sets it for a unit with
        `CacheDirectory=`; the first entry), else $XDG_CACHE_HOME/adele or ~/.cache/adele."""
        if self.cache_dir is not None:
            return self.cache_dir
        from_systemd = os.environ.get("CACHE_DIRECTORY", "").split(":")[0]
        if from_systemd:
            return Path(from_systemd)
        return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "adele"


def load(path: str | os.PathLike | None = None) -> Config:
    p = Path(path or os.environ.get("ADELE_SERVER_CONFIG") or DEFAULT_PATH).resolve()
    if not p.exists():
        raise SystemExit(f"config file not found: {p} (set --config or ADELE_SERVER_CONFIG)")
    raw = tomllib.loads(p.read_text())
    base = p.parent

    def path_of(key: str, default: str | None = None) -> Path | None:
        v = raw.get(key, default)
        return None if v is None else (base / v).resolve()

    keys = {str(k): str(v) for k, v in raw.get("keys", {}).items()}
    if len(set(keys.values())) != len(keys):
        raise SystemExit("config: two team members have the same API key")
    data_dir = path_of("data_dir")
    if "datasets_dirs" in raw and "datasets_dir" in raw:
        raise SystemExit("config: set datasets_dirs or datasets_dir, not both")
    dirs = raw.get("datasets_dirs", [raw["datasets_dir"]] if "datasets_dir" in raw else None)
    if not dirs or not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
        raise SystemExit("config: datasets_dirs must be a non-empty list of folders")
    return Config(
        path=p,
        datasets_dirs=[(base / d).resolve() for d in dirs],
        data_dir=data_dir,
        log_dir=path_of("log_dir") or data_dir / "logs",
        env_file=path_of("env_file"),
        admin_email=raw.get("admin_email"),
        keys=keys,
        query=QueryLimits(**raw.get("query", {})),
        fetch_timeout_s=float(raw.get("fetch_timeout_s", 1800)),
        cache_dir=path_of("cache_dir"),
    )


def load_env_file(path: Path | None) -> None:
    """Load KEY=VALUE lines (source credentials) into the environment. Values are never printed."""
    if path is None or not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
