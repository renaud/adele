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
Within the fetch unit, each `fetch.py` gets only the variables that its descriptor declares in
`adele.secrets` (entsoe: `ENTSO_TOKEN`; weathernext3: `GOOGLE_APPLICATION_CREDENTIALS`), plus
what uv and Python need (`PATH`, `HOME`, locale, certificates, proxies, `UV_*`, `PYTHON*`,
`XDG_*`). That filters environment variables only: files that the user `adele` can read (e.g.
`/etc/adele/gcloud-adc.json`) stay readable by every fetch. Separating the datasets for real
needs one user per fetch (later, with datasets from other repositories).

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

In `/etc/adele/adele-server.toml`: `datasets_dirs = ["/opt/adele/datasets"]`, `data_dir = "/var/lib/adele"`,
`log_dir = "/var/log/adele"`, no `env_file` (systemd passes the environment). A dataset kept in its
own repository is one more entry in `datasets_dirs` (its checkout folder, e.g.
`/opt/adele-datasets/<repo>`); an entry with a `datapackage.yaml` is one dataset, any other entry a
folder of dataset folders.

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
the system Python.

## Access from outside: HTTPS through Caddy

Decided 2026-11-13: steacher1 has a DNS name and can be reached from outside, so team members call
the server over HTTPS. An SSH tunnel would need an SSH account per member, which is a shell: more
access than an API key. uvicorn stays on 127.0.0.1:8000; Caddy (`deploy/Caddyfile`) terminates TLS
and forwards. The API key travels in a header, so never over plain HTTP outside the machine.

```bash
sudo apt install caddy
sudo cp Caddyfile /etc/caddy/Caddyfile     # after replacing the host name
sudo systemctl reload caddy
```

Clients: `ADELE_URL=https://<steacher1's DNS name>`, plus their own `ADELE_API_KEY` (one key per
person in `[keys]`, so that `queries.jsonl` says who ran what, and one key can be revoked).

Before opening the ports: ask the university's IT whether ports 80 and 443 may be opened on
steacher1, and whether to limit them to the university network and the VPN (the commented
`remote_ip` block in the Caddyfile).
