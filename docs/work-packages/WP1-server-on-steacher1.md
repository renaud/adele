# WP1: server on steacher1

Draft by Claude, 2026-11-15, not accepted. From `PLAN.md` (WP1) and `TODOs.md` (POC step 6).
Renaud's answers of 2026-11-15 are in.

## Where WP1 stands (2026-11-15, 12:20 UTC)

- Steps 0-4 done. Step 5 (backfill) in progress: the backfills run on steacher1 as the fetch
  units with a runtime drop-in each; they were stopped at 12:16 to give `adele` a new uid
  (`deploy/wp1-step5-uid-fix.sh`, see the log) and start again at the end of that script.
  Next: `deploy/wp1-step5-backfill.sh finish` once both have stopped, then the timers, step 6
  (HTTPS, once Renaud opens the port), step 7 (the week), step 8.
- steacher1 runs commit f1766c9 (`/opt/adele`). It stays there during the week: the evidence
  of the week holds for one version. Only a fix that WP1 needs is pulled there, and it goes
  into the log below.
- Rules for other sessions (WP3 runs in its own worktree from 2026-11-15, Renaud):
  - `main` holds what steacher1 runs plus WP1 fixes. WP3 lands in `main` after the week, and
    reaches steacher1 only once WP1 is done (as `WP3-versions.md` says).
  - Don't touch `deploy/` or this file; WP1 may still change `server/` for a fix.
  - Don't run anything on steacher1. Claude's only route there is `/usr/local/bin/sc-run`
    (user `claude`, no sudo), and root steps are scripts that Renaud runs.

## Goal

adele runs on steacher1 with the two datasets that are in adele today (`entsoe_day_ahead_prices`,
`weathernext3`), one systemd timer per dataset, and fetches unattended for a week. A laptop
outside the server can query it over HTTPS.

## What is settled

- Claude works on steacher1 through SSH from this machine as the user `claude`, which has no
  sudo (Renaud, 2026-11-15, after step 0 showed that `ubuntu` has sudo without a password).
  The user is created by `deploy/wp1-claude-user.sh`. Claude's only route is
  `/usr/local/bin/sc-run '<command>'` (owned by root, host, user and key written in it, no ssh
  option passed through); `ssh` and `scp` stay denied to Claude (see the log, 2026-11-15).
  Renaud keeps `ssh s` (user `ubuntu`). Renaud types the `sudo` commands himself. Claude groups the root steps into
  short scripts in `deploy/`; Renaud reads each one and runs it in his own terminal on
  steacher1. Each script writes its output to a log file in his home, which Claude reads over
  SSH.
- The code comes from `github.com/renaud/adele` (remote added by Renaud, 2026-11-15). Renaud
  pushes; steacher1 clones it into `/opt/adele`. The repository is public (checked 2026-11-15),
  so no deploy key. An update of the server is `git pull` and `uv sync` in `/opt/adele`.
- entsoe is backfilled again on steacher1 from 2015, to test the backfill (Renaud).
- The ENTSO-E token is in `.env` on the Mac (ignored by git), not on steacher1 (step 0). Step 4
  copies it to `/etc/adele/env.d/entsoe_day_ahead_prices` without printing it.
- Ports 80 and 443 serve steacher.org, which nobody touches. adele gets another port, which
  Renaud opens in Infomaniak's panel, with adele's own certificate authority (HTTPS below,
  way b, Renaud 2026-11-15).
- Google: Renaud ran `gcloud auth application-default login --no-browser` on steacher1, which
  writes the file that `fetch.py` reads. The file is in his home folder, which the fetch units
  can't read (`ProtectHome=yes`), so step 4 copies it to `/etc/adele/gcloud-adc.json`.

## Steps

0. **Look first, change nothing.** On steacher1: what listens on 80 and 443, and which program;
   the OS and the systemd version; where the ENTSO-E token is; that the Google file is there;
   that port 8443 is free. If the other site runs Caddy, `apt install caddy` (as `deploy/README.md` says)
   would change its config: adele then gets a second Caddy service with its own config file.
1. **Server changes that the units need.** Done: commit a1629d0, pushed to `origin/main`, with
   D27 in `DECISIONS.md`. `fetch <id> --if-due`, a time limit per dataset, a fixed path for the
   uv runner (0.3 s instead of 8.7 s per fetch), SIGTERM stops `fetch.py` and is recorded, a
   broken descriptor no longer stops the other datasets.
2. **Two defects in `deploy/adele-server.service`**, to fix before the first start. Fixed in
   the working tree (2026-11-15): `InaccessiblePaths=-/etc/adele/env.d -/etc/adele/gcloud-adc.json`,
   and `WorkingDirectory=/tmp` (the private `/tmp` of the unit) in both units, since
   `adele-fetch@.service` had no working directory either. Checked by `systemd-analyze verify`
   at step 4.
   - `InaccessiblePaths=/etc/adele/env` names a file that the layout replaced with `env.d/`.
     systemd refuses to start a unit when such a path is missing, unless it starts with `-`.
   - no working directory, so DuckDB would write its temporary files to `/.tmp`, which is
     read-only there.
3. **Test systemd on the real server.** Run `deploy/scheduling-poc/adele-systemd-claims-test.sh`
   (about 6 minutes, writes only under `/run`). Its claims were tested only in a container on
   the Mac. Done (2026-11-15): 27 passed, 0 failed, as in the container
   (`deploy/scheduling-poc/result-steacher1.txt`, see the log).
4. **Install** as `deploy/README.md` says: users, folders, uv and a Python in `/opt/uv-python`,
   the clone in `/opt/adele`, the config, the secrets per dataset (ENTSO-E token, Google file),
   the units, `validate`. Every step that differs from the draft goes into `deploy/README.md`.
   Done (2026-11-15): `deploy/wp1-step4-install.sh`, run twice by Renaud; `adele-server.service`
   runs on 127.0.0.1:8000. See the log.
5. **Backfill**, then enable the timers. entsoe: from 2015. weathernext3: a few days, plus the 7
   sample runs again to add their clouds (`TODOs.md`).
6. **HTTPS on another port**, once Renaud has opened it (see below). One API key for Renaud;
   test with the CLI from a laptop. The CLI uses Python's `urllib`, which trusts only the
   system's authorities: it gets a setting `ADELE_CA_FILE` (the root certificate of adele's
   authority), a few lines in `client/src/adele/_api.py`. Pointing `SSL_CERT_FILE` at that
   file would also work, but it breaks every other HTTPS call of the shell that sets it.
7. **The week.** Once a day: `adele list` (freshness, status), the failed units, the alert log.
   Each problem goes into the log at the end of this file, with its fix.
8. **Faults on purpose**, each on a copy of a dataset under another id, so that the real data
   stays clean: a renamed column, a duplicated row, an undeclared zone code. Each must set the
   status to failing. Added by Claude: stop the timers for two hours; the next run must fetch
   the hole (D25).

## HTTPS on another port

adele listens on a port such as 8443, which Renaud opens in Infomaniak's panel (limited to the
university network and the VPN, if IT wants that). The certificate is the difficulty: Let's
Encrypt checks that we control the domain through port 80 or 443, and both are taken. Two ways:

- a. **Check through DNS.** Caddy proves control with a record in the domain's DNS. A real
  certificate, nothing to install on the laptops. Cost: a Caddy build with the plugin of the
  DNS provider (one exists for Infomaniak; to check), and an API token on the server that can
  change the DNS of the domain. Risk: a stolen token can change the domain's DNS.
- b. **adele's own certificate authority** (Caddy's `tls internal`). No DNS, no token. Cost:
  each laptop needs the root certificate of that authority, and the CLI needs a setting that
  points to it. Risk: a member who has trouble with it turns off the check.

Chosen: b (Renaud, 2026-11-15). Not chosen: the other site's web server as the front for adele
(Renaud: don't touch it), an SSH tunnel (one shell account per member, rejected 2026-11-13).

## Done when

- 7 days in a row, both datasets are fetched on schedule: no hole (every delivery day of the
  prices, every hourly run of weathernext3), status ok, the published figures pass after each
  fetch.
- the faults of step 8 are caught.
- a query over HTTPS from a laptop answers.
- `deploy/README.md` describes what was run, and is no longer a draft.

## Not in WP1

The other datasets (WP5), one key per team member (WP9), email alerts and the status `stale`,
backups of the data folder, one repository per dataset.

## Open questions

None on 2026-11-15.

## Log

### 2026-11-15, step 0 (`deploy/wp1-step0-look.sh`, run by Renaud)

- Ubuntu 24.04.4, kernel 6.8, systemd 255 (255.4-1ubuntu8.18; the container test had
  255.4-1ubuntu8.4). Clock in UTC, synchronized by NTP. 4 CPUs, 7.8 GiB RAM (5.1 available).
- Disk: one file system, 48 GB, 38 GB used (80 %), 9.7 GB free. adele's data on the Mac is
  14 MB; the growth of weathernext3 over the week is to measure.
- Ports 80 and 443: nginx in a Docker container (docker-proxy --> 172.20.0.2), 7 containers
  running. No Caddy, so installing Caddy changes nothing of the other site. Nothing listens
  on 8443. Only 22, 80 and 443 listen on the network.
- `deploy/Caddyfile` is still written for Let's Encrypt on 80/443: for way b it needs port
  8443, `tls internal`, and no listener on port 80 (Caddy opens 80 for its redirects
  otherwise, and 80 is taken). The Ubuntu package starts Caddy with a default config on :80,
  which fails until our Caddyfile replaces it.
- Missing: uv, Caddy. Present: git 2.43, Python 3.12.3, Docker 29.7, gcloud 593.
- Google file present: `~/.config/gcloud/application_default_credentials.json`, 351 bytes,
  2026-10-26. It is a user credential: it stops working if Google ends the session.
- ENTSO-E token: not found. No readable file under `~`, `/opt`, `/srv` or
  `/etc/environment` contains `ENTSO` (the name `fetch.py` reads is `ENTSO_TOKEN`).
- `ubuntu` has sudo without a password, and is in the `docker` group (which also amounts to
  root). So `ssh s` with an allow rule gives Claude root on steacher1 without a prompt.
- Auto mode refused every `ssh s ...` command, also after Renaud added `Bash(ssh s:*)` to
  `.claude/settings.local.json`.
- No trace of adele (no `/opt/adele`, `/etc/adele`, `/var/lib/adele`, no users).

### 2026-11-15, the user `claude` (`deploy/wp1-claude-user.sh`)

- `ssh sc` logs in: uid 1001 `claude`, groups `claude` and `systemd-journal` (no sudo, not in
  `docker`). Run by Renaud with the `!` prefix.
- Claude's `ssh sc ...` was refused in auto mode and in the mode "accept edits", although
  `.claude/settings.local.json` allows `Bash(ssh sc:*)`. Cause: `~/.claude/settings.json`
  denies `Bash(ssh:*)`, and a deny rule wins over every allow rule, in every mode. The same
  rule explains the refusals of `ssh s` at step 0 (not auto mode, as written there).
- Rules alone can't allow only `ssh sc` (advice by Fable, from the Claude Code docs): a deny
  rule can't have an exception, and `Bash(ssh sc:*)` would not limit anything, because ssh also
  reads options after the host (`ssh sc -l ubuntu -i ~/.ssh/id_rsa ...` matches the rule).
- Chosen: a wrapper `/usr/local/bin/sc-run`, installed by Renaud with `sudo install -o root`.
  It runs `/usr/bin/ssh -F none -i ~/.ssh/steacher1_claude ... -- claude@37.156.44.113 "$*"`, so
  `~/.ssh/config` plays no part and every argument becomes the remote command. Allowed by
  `Bash(/usr/local/bin/sc-run *)` in `.claude/settings.local.json`; the deny on `ssh` and `scp`
  is unchanged.
- Checks: `sc-run id` prints `uid=1001(claude)`. `sc-run -l ubuntu id` fails on the server
  with `bash: - : invalid option` (the usage lists `--pretty-print`, which only the bash 5.2 of
  the server has, not the bash 3.2 of the Mac): sshd runs `bash -c '-l ubuntu id'`, and bash
  reads a command that starts with `-` as more of its own options. No login as `ubuntu`.
- Open: in auto mode the allow rule skips the classifier, so nothing reviews the remote
  commands; the limit is what `claude` can do. Indirect ssh (`/usr/bin/ssh`, `bash -c`, Python,
  git over ssh) is not matched by the deny rules: it asks in the default mode, and the
  classifier decides in auto mode.

### 2026-11-15, step 3 (systemd claims test, run by Renaud)

- 27 passed, 0 failed (`deploy/scheduling-poc/result-steacher1.txt`). systemd 255.4-1ubuntu8.18,
  kernel 6.8. Same verdicts as the container (`container-test/result-2026-11-15.txt`), once
  the PIDs and times are masked.
- Seen only on the server, since the container had no journal: a tick that falls while the
  unit runs leaves no line in the journal (section 3: starts at :15, :27, :39 for a timer every
  5 s); the journal of one instance holds only its own lines (section 4).
- Section 5: the refusal reads `Interactive authentication required` (rc 1, polkit is present);
  the container said `Access denied` (rc 4). Both are refusals.
- Section 7: `KillMode=mixed` stopped in 0 s, as in the container; already known (`TODOs.md`,
  `DECISIONS.md`).
- Section 8: with the default accuracy, the timer also fired in the first second (00.15), as in
  the container (00.48), not "anywhere in the minute". Claude's reading, not tested: the timer
  with `AccuracySec=1s` of the same test wakes systemd at :00, and the other timer, whose window
  is open, fires in the same wakeup. No effect on adele: `adele-fetch@.timer` sets
  `AccuracySec=1s`.
- After the run: no unit, unit file or folder `adelepoc*` left. The only failed unit,
  `systemd-networkd-wait-online.service`, failed at boot on 2026-10-19, before adele.

### 2026-11-15, step 4 (`deploy/wp1-step4-install.sh`, run by Renaud)

- The ENTSO-E token went first, through a pipe from `.env` on the Mac to `sudo tee` (the
  first form, with `sh -c "... cat > ..."`, broke when the long line was copied: `sh` stopped
  on a syntax error before it wrote anything).
- The script ran twice (first at 11:59, the second run is in `deploy/wp1-step4-result.txt`);
  the second run kept the config and changed nothing.
- uv 0.9.8 (checksum OK), Python 3.13.9 in `/opt/uv-python`, `.venv/bin/python` links there.
  `systemd-analyze verify`: rc 0, no warning. `validate`: both datasets ok.
- `adele-server.service` enabled and running; `/health` answers after about 2 s, both datasets
  `failing` with "never fetched" (`state.load` for a dataset without state). Inside the
  service's namespace, `env.d` and `gcloud-adc.json` have mode 0 (the file has size 0).
- Disk: 9.4 GB free; `/opt/adele` 216 MB, `/opt/uv-python` 104 MB.
- Differences from the draft, now in `deploy/README.md`: `adele-query` has the home
  `/nonexistent`; `/etc/adele` is `root:adele 0750`; uv from its release archive;
  `UV_PYTHON_INSTALL_DIR` also for `uv sync`; `--locked`; `validate` from `/tmp`.

### 2026-11-15, step 5 (`deploy/wp1-step5-backfill.sh start`, run by Renaud at 12:11)

- A runtime drop-in per dataset (`/run/systemd/system/adele-fetch@<id>.service.d/backfill.conf`)
  replaces `fetch --if-due` with the backfill commands; the units started without waiting.
  entsoe: `--start 2014-12-31`. weathernext3: the 2024-11-12 00 run, the 2025-11-12 00 and 03
  runs, then every run from 2026-11-12 00 UTC (three `ExecStart` lines, the first two with `-`).
- First measures: uv built both environments in about a minute; a weathernext3 run of 2026
  takes 47-48 s on steacher1 (the 2024 run took 236 s, environment included); the fetch uses
  2.3 GB of memory.
- **uid collision.** `useradd --system` gave `adele` the uid 999, and postgres and redis in the
  Docker containers of steacher.org also run as 999 (Docker keeps the host's uids). Checked
  with `setpriv` as `adele` against postgres: environment not readable, root folder of the
  container not listable (Claude had predicted both readable: wrong), signals allowed. So a
  `fetch.py` or a library that calls `kill(-1, ...)` would stop the production database.
  Fix: `deploy/wp1-step5-uid-fix.sh`, `adele` 5100, `adele-query` 5101 (`usermod -u` refuses
  while postgres runs as 999, so `userdel -f` and `useradd` again; the groups stay). The
  install script and `deploy/README.md` now set these uids.
- **A stop that hangs.** The fix script's `systemctl stop` did not end for weathernext3: the
  SIGTERM ended the second `ExecStart` (the 2025 runs), the `-` made that a success, and systemd
  started the third line at 12:16:49 although the unit was stopping. That process got no
  SIGTERM, and the stop's 90 s limit did not kill it (Claude's reading: the timer was set again
  with `TimeoutStartSec=infinity` from the drop-in). Way out: `systemctl kill` on the unit. To
  stop a backfill unit with these drop-ins, use `systemctl kill`, not `systemctl stop`.
- The fix script then ran to its end on steacher1 (12:22), but its output after step 2 never
  reached the Mac (`deploy/wp1-step5-uid-fix.txt` stops there; the SSH session stayed open
  with no process under it). Checked over `sc-run` instead: `adele` 5100, the three folders
  owned by 5100 with their modes, `adele-server` running, both backfills started again at
  12:22:46 as 5100. After: `setpriv --reuid=adele ... kill -0 <postgres pid>` --> `Operation
  not permitted`.
- Pace after the restart: entsoe about 35 s per year window, weathernext3 about 53 s per run.
