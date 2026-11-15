# Deploying adele-server on Linux (draft of 2026-11-13; installed on steacher1 on 2026-11-15)

POC step 6 (TODOs.md). The units share one install and one data folder:

| unit | runs | user | data folder |
|---|---|---|---|
| `adele-server.service` | `adele-server serve` (agent SQL) | `adele-query` | read-only (`ReadOnlyPaths=`) |
| `adele-fetch@<id>.service` + `.timer`, one pair per dataset | `adele-server fetch <id> --if-due`, every minute | `adele` | read-write |

One timer and one service per dataset (D27, 2026-11-15): fetches of different datasets run side
by side, a slow one never delays another, and each dataset has its own journal, time limit and
file of secrets. The timer only gives the tick: `adele.refresh.every` in the descriptor decides
whether a fetch happens. The claims about systemd behind this were tested in a container
(`scheduling-poc/container-test/`) and on steacher1 (`scheduling-poc/result-steacher1.txt`).

The query process can't write the data, by two layers: its user (`adele-query`, group `adele`, files
group-readable) and its mount namespace (`ReadOnlyPaths=/var/lib/adele`). DuckDB's own settings and
the statement filter come on top (D10, D24). Source credentials reach only the fetch units, and
each fetch unit gets the variables of its own dataset: systemd reads `/etc/adele/env.d/<id>`
(root only) before it changes to the user `adele`, so no `fetch.py` can read the file of another
dataset. Within the unit, `fetch.py` gets only the variables that its descriptor declares in
`adele.secrets` (entsoe: `ENTSO_TOKEN`; weathernext3: `GOOGLE_APPLICATION_CREDENTIALS`), plus
what uv and Python need (`PATH`, `HOME`, locale, certificates, proxies, `UV_*`, `PYTHON*`,
`XDG_*`). A credential that is a file and not a variable (`/etc/adele/gcloud-adc.json`) must be
readable by the user `adele`, so every fetch can read it: `adele-server.service` hides it from
the query process (`InaccessiblePaths=`). Separating such files needs one user per fetch (later,
with datasets from other repositories).

## Layout

```
/opt/adele/                  git checkout; `cd server && uv sync --no-dev --locked`
/usr/local/bin/uv, uvx       uv, pinned version          root:root 0755
/opt/uv-python/              the Python of the venv and of the fetch.py runners (UV_PYTHON_INSTALL_DIR)
/etc/adele/                  config and secrets          root:adele 0750
/etc/adele/adele-server.toml config with the API keys    root:adele 0640
/etc/adele/env.d/<id>        variables of one dataset    root:root 0600 (read by systemd)
                             entsoe_day_ahead_prices: ENTSO_TOKEN=...
                             weathernext3: GOOGLE_APPLICATION_CREDENTIALS=/etc/adele/gcloud-adc.json
/etc/adele/gcloud-adc.json   Google credentials (WeatherNext 3)     root:adele 0640 (fetch units only)
/var/cache/adele/uv/         uv cache of the fetch units (CacheDirectory=)
/var/lib/adele/              data_dir                    adele:adele 2750
/var/log/adele/              queries.jsonl, alerts.log   adele:adele 2770
```

In `/etc/adele/adele-server.toml`: `datasets_dirs = ["/opt/adele/datasets"]`, `data_dir = "/var/lib/adele"`,
`log_dir = "/var/log/adele"`, no `env_file` (systemd passes the environment). A dataset kept in its
own repository is one more entry in `datasets_dirs` (its checkout folder, e.g.
`/opt/adele-datasets/<repo>`); an entry with a `datapackage.yaml` is one dataset, any other entry a
folder of dataset folders.

## Install

The install that ran on steacher1 is `wp1-step4-install.sh` (root; it can be run again, and it
keeps an existing config). The secret that is a variable is copied first, from the admin's
machine, never printed (see the script's header). The script, in order:

1. users `adele` and `adele-query` (system users, no home: `/nonexistent`, no shell);
2. the folders of the layout above, with their owners and modes;
3. uv from its GitHub release archive, checked against the `.sha256` of the same release;
4. `uv python install 3.13` with `UV_PYTHON_INSTALL_DIR=/opt/uv-python`;
5. `git clone` into `/opt/adele`, then `uv sync --no-dev --locked` in `server/`, with the same
   `UV_PYTHON_INSTALL_DIR`, so that the venv links to `/opt/uv-python` and not to `/root`;
6. `/etc/adele/adele-server.toml` with one API key generated on the server (never printed);
7. the Google file and `/etc/adele/env.d/weathernext3`; checks that the ENTSO-E token is there;
8. the three units into `/etc/systemd/system/`, `daemon-reload`, and `systemd-analyze verify`
   on copies named after the instances (`%i` comes from the unit's name);
9. `validate` as the user `adele`, from `/tmp`;
10. `systemctl enable` and `restart` of `adele-server.service`, then `GET /health`;
11. with `nsenter`, what the query process sees of `env.d` and `gcloud-adc.json` (mode 0).

It enables no fetch timer. After the backfill (WP1 step 5):

```bash
for id in entsoe_day_ahead_prices weathernext3; do sudo systemctl enable --now "adele-fetch@$id.timer"; done
```

Add a dataset (root, once per dataset; the id is the `name` of its descriptor):

```bash
sudo systemctl enable --now adele-fetch@<id>.timer
# its secrets, if it has any: /etc/adele/env.d/<id> (root:root 0600)
```

Look at what ran (the journal needs root or the group `systemd-journal`):

```bash
systemctl list-timers 'adele-fetch@*'                # next and last tick per dataset
systemctl list-units --all 'adele-fetch@*.service'   # running (activating) and failed instances
journalctl -u adele-fetch@<id>.service --since -1h   # one dataset
```

A backfill holds the lock of its dataset until it ends: the ticks of the timer skip the dataset
meanwhile. The first scheduled run after it fetches the time that the backfill took (D25).

The data folder holds nothing but data: no home directory, credentials or caches go there. Agent
SQL reads only the folders of the tables since 2026-11-14 (`allowed_directories`, D24; before, it
could read any file under `data_dir`), and this rule stays as a second layer. That is why
`adele` has no home (an earlier draft used `/var/lib/adele`).

Fetches run `fetch.py` with `uv run --script` (PEP 723 dependencies per dataset, both datasets
since 2026-11-13). So the fetch unit needs `uv` in `/usr/local/bin`, a Python that uv can use
without downloading one (`UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install 3.13` as root),
a writable uv cache (`/var/cache/adele/uv`), and access to PyPI for the first run of each fetch.py
and after a dependency changes. WeatherNext 3 reads Google's Zarr stores with Application Default
Credentials: run `gcloud auth application-default login --no-browser` as an admin and copy the
file to `/etc/adele/gcloud-adc.json`. If those credentials carry a quota project, fetch.py drops it
(reads must stay billed to Google).

`uv sync` links the venv to a Python that uv installs under the home of the user who runs it,
which `ProtectHome=yes` hides from the units. So the install sets `UV_PYTHON_INSTALL_DIR=/opt/uv-python`
for `uv sync` too (on steacher1: `.venv/bin/python` --> `/opt/uv-python/cpython-3.13.9-linux-x86_64-gnu`).

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
