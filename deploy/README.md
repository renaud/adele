# Deploying adele-server on Linux (in use on adele's server since 2026-11-15, WP1)

POC step 6 (TODOs.md). The units share one install and one data folder:

| unit | runs | user | data folder |
|---|---|---|---|
| `adele-server.service` | `adele-server serve` (agent SQL) | `adele-query` | read-only (`ReadOnlyPaths=`) |
| `adele-caddy.service` | Caddy, HTTPS on 8443 (D35) | `adele-caddy` | none |
| `adele-fetch@<id>.service` + `.timer`, one pair per dataset | `adele-server fetch <id> --if-due`, every minute | `adele` | read-write |

One timer and one service per dataset (D27, 2026-11-15): fetches of different datasets run side
by side, a slow one never delays another, and each dataset has its own journal, time limit and
file of secrets. The timer only gives the tick: `adele.refresh.every` in the descriptor decides
whether a fetch happens. The claims about systemd behind this were tested in a container
(`scheduling-poc/container-test/`) and on the server (`scheduling-poc/result-server.txt`).

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
/usr/local/bin/caddy         Caddy, pinned in access.sh  root:root 0755
/etc/adele-caddy/            Caddyfile, root.crt         root:root 0755
/var/lib/adele-caddy/        the authority of HTTPS      adele-caddy 0700
/var/lib/adele/              data_dir                    adele:adele 2750
/var/log/adele/              queries.jsonl, alerts.log   adele:adele 2770
```

In `/etc/adele/adele-server.toml`: `datasets_dirs = ["/opt/adele/datasets"]`, `data_dir = "/var/lib/adele"`,
`log_dir = "/var/log/adele"`, no `env_file` (systemd passes the environment). A dataset kept in its
own repository is one more entry in `datasets_dirs` (its checkout folder, e.g.
`/opt/adele-datasets/<repo>`); an entry with a `datapackage.yaml` is one dataset, any other entry a
folder of dataset folders.

## Install

The install that ran on the server is `wp1-step4-install.sh` (root; it can be run again, and it
keeps an existing config). The secret that is a variable is copied first, from the admin's
machine, never printed (see the script's header). The script, in order:

1. users `adele` (uid 5100) and `adele-query` (uid 5101): system users, no home (`/nonexistent`),
   no shell. The uids are fixed because the first free system uid (999) is the uid of postgres
   and redis in many Docker images, and Docker keeps the host's uids: on the server the fetch
   units then had the uid of the production database (`wp1-step5-uid-fix.sh`). On a new server,
   check `ps -eo uid=` first;
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

Memory: each fetch unit may use 4.5 GiB (`MemoryMax=`); past that, the kernel kills `fetch.py`
and the server records the failure (`OOMPolicy=continue`). If the whole machine runs out of
memory, the kernel kills a fetch before any other process (`OOMScoreAdjust=1000`). A weathernext3
fetch peaks at 3.5 GB (3.9 GB for a backfill of 80 runs). A dataset or a backfill that needs more
gets a drop-in, `/etc/systemd/system/adele-fetch@<id>.service.d/limits.conf` with `MemoryMax=`.

These limits hold per fetch, not for their sum: on 2026-11-17 five backfills beside the hourly
fetches froze the server for 30 minutes (no swap; the OOM killer never ran). `memory-guard.sh`
adds a cap on all fetches together (`MemoryMax=4608M` and `MemorySwapMax=0` on the slice
`system-adele\x2dfetch.slice`, through `systemctl set-property`), a swap file of 4 GiB for the
other services, and moves weathernext3 to minute 30, away from the hourly fetches at minute 0.
Backfills run one lane at a time (`backfill.sh chain`).

Since 2026-11-23 (`spread-fetches.sh`): all fetches together use at most 2.5 of the 4 cores
(`CPUQuota=250%`, `CPUWeight=20` on the same slice), and the 14 daily datasets have slots from
00:08 to 02:15 UTC, a drop-in per timer (`adele-fetch@<id>.timer.d/slot.conf`: from the slot on, a
tick every 10 minutes). Without a slot, a daily dataset starts at 00:00 UTC with all the others: a
new one gets a line in `SLOTS` of that script, which is then run again.

The result of a fetch that has ended is in its journal. Without an enabled timer, systemd
unloads the service once it ends, and `systemctl show` then prints default values
(`Result=success`, no timestamps).

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
for `uv sync` too (on the server: `.venv/bin/python` --> `/opt/uv-python/cpython-3.13.9-linux-x86_64-gnu`).

## Update to a new `main`

Written 2026-11-17 for the update from 32237db to `main` (WP2 to WP5): two root scripts, run by
the admin; their headers say what each step does.

```bash
# Phase A, the code: stop the running timers, backup to /root, pull, uv sync, units, secrets
# per dataset (copied within env.d, never printed), validate, restart, timers again
ssh s 'sudo bash -s' < deploy/update-main.sh 2>&1 | tee deploy/update-main.txt
# Phase B, the new datasets: backfills in lanes (transient units adele-backfill-<lane>), each
# dataset's timer once its backfill has ended; results in /var/lib/adele-deploy/backfill.tsv
ssh s 'sudo bash /opt/adele/deploy/backfill.sh start' 2>&1 | tee deploy/backfill-start.txt
ssh s 'sudo bash /opt/adele/deploy/backfill.sh report' 2>&1 | tee deploy/backfill-report.txt
```

A later update with no new dataset needs only phase A. A new dataset alone: its secrets file,
its backfill, its timer (the items of a lane in `backfill.sh`).

## Access from outside: HTTPS through Caddy

Decided 2026-11-13 (HTTPS and an API key per person; an SSH account would be a shell) and
2026-11-23 (D35). uvicorn stays on 127.0.0.1:8000; Caddy (`adele-caddy.service`) listens on 8443
and forwards. Ports 80 and 443 of the server belong to another site, so the certificate comes
from Caddy's own authority (`tls internal`); its root certificate is in the client package.

```bash
# 1. after the push: limits on queries, Caddy, the authority, a check on the server
ssh s 'sudo bash -s -- <dns name>' < deploy/access.sh 2>&1 | tee deploy/access.txt
# 2. the root certificate (public) into the client package; commit, push
ssh s 'cat /etc/adele-caddy/root.crt' > client/src/adele/adele-ca.pem
# 3. the port: TCP 8443 from everywhere, in the panel of the hosting provider
# 4. a key per person
ssh s 'sudo bash -s -- <name>' < deploy/add-key.sh
```

What a person gets: the URL (`https://<dns name>:8443`), their key, and `client/README.md`.

The authority is in `/var/lib/adele-caddy` (with its private key, readable by `adele-caddy` only)
and in the backup that `access.sh` writes to `/root`. If both are lost, Caddy makes a new
authority and every client must be updated. The root certificate is valid for years (`access.sh` prints
the date); Caddy renews the others by itself.

Limits: `adele-server.service` may use 3 GB (`MemoryMax=`), two queries run at once with 1 GB of
memory and 2 GB of temporary files each (`[query]` of the config, defaults in `config.py`). The
checks after a fetch run in the fetch units, with their own limits (`[checks]`).
Look: `journalctl -u adele-caddy`, `systemctl show -p MemoryPeak adele-server`,
`/var/log/adele/queries.jsonl` (the key's name, the SQL, `waited_ms`).
