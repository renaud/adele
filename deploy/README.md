# Deploying adele-server on Linux (draft, 2026-11-13, not tried yet)

POC step 6 (TODOs.md). Two systemd units share one install and one data folder:

| unit | runs | user | data folder |
|---|---|---|---|
| `adele-server.service` | `adele-server serve` (agent SQL) | `adele-query` | read-only (`ReadOnlyPaths=`) |
| `adele-fetch.service` + `.timer` | `adele-server fetch --due`, every 15 min | `adele` | read-write |

The query process can't write the data, by two layers: its user (`adele-query`, group `adele`, files
group-readable) and its mount namespace (`ReadOnlyPaths=/var/lib/adele`). DuckDB's own settings and
the statement filter come on top (D10). Source credentials (`ENTSO_TOKEN`, Google's) reach only the fetch
unit: `adele-query` is in group `adele`, so `adele-server.service` hides the two files (`InaccessiblePaths=`).

## Layout

```
/opt/adele/                  git checkout; `cd server && uv sync --no-dev`
/etc/adele/adele-server.toml config with the API keys    root:adele 0640
/etc/adele/env               ENTSO_TOKEN=...             root:adele 0640 (fetch unit only)
/etc/adele/gcloud-adc.json   Google credentials (WeatherNext 3)     root:adele 0640 (fetch unit only)
/var/cache/adele/uv/         uv cache of the fetch unit (CacheDirectory=)
/var/lib/adele/              data_dir                    adele:adele 2750
/var/log/adele/              queries.jsonl, alerts.log   adele:adele 2770
```

In `/etc/adele/adele-server.toml`: `datasets_dir = "/opt/adele/datasets"`, `data_dir = "/var/lib/adele"`,
`log_dir = "/var/log/adele"`, no `env_file` (systemd passes the environment).

## Install

```bash
sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin adele
sudo useradd --system --no-create-home --shell /usr/sbin/nologin -G adele adele-query
sudo install -d -o adele -g adele -m 2750 /var/lib/adele
sudo install -d -o adele -g adele -m 2770 /var/log/adele
sudo cp adele-server.service adele-fetch.service adele-fetch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo -u adele /opt/adele/server/.venv/bin/adele-server --config /etc/adele/adele-server.toml validate
sudo systemctl enable --now adele-server.service adele-fetch.timer
```

The data folder holds nothing but data: agent SQL may read any file under `data_dir`
(`allowed_directories`, D10), so no home directory, credentials or caches go there. That is why
`adele` has no home (an earlier draft used `/var/lib/adele`).

Fetches run `fetch.py` with `uv run --script` (PEP 723 dependencies per dataset, both datasets
since 2026-11-13). So the fetch unit needs `uv` in `/usr/local/bin`, a Python that uv can use
without downloading one (`UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install 3.13` as root),
a writable uv cache (`/var/cache/adele/uv`), and access to PyPI for the first run of each fetch.py
and after a dependency changes. WeatherNext 3 reads Google's Zarr stores with Application Default
Credentials: run `gcloud auth application-default login --no-browser` as an admin and copy the
file to `/etc/adele/gcloud-adc.json`. If those credentials carry a quota project, fetch.py drops it
(reads must stay billed to Google).

Open: `uv sync` links the venv to a Python that uv installs under the home of the user who runs it,
which `ProtectHome=yes` hides from the units; install with `UV_PYTHON_INSTALL_DIR=/opt/uv-python` or use
the system Python. And how team members reach the server (SSH tunnel, VPN, or a reverse proxy with TLS). The API key
travels in a header, so not over plain HTTP outside the machine.
