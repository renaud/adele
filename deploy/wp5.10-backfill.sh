#!/usr/bin/env bash
# Replaced on 2026-11-17 by deploy/backfill.sh (lanes openmeteo and ens, the same plan) in the update
# of steacher1 to main: don't run both.
# WP5.10 (docs/work-packages/WP5.10-weather-forecasts.md): the six datasets of weather forecasts on
# steacher1. Push main first (it must hold WP5.10), then run as root from the repository root on the Mac:
#   ssh s 'sudo bash -s start'  < deploy/wp5.10-backfill.sh 2>&1 | tee deploy/wp5.10-start.txt
#   ssh s 'sudo bash -s finish' < deploy/wp5.10-backfill.sh 2>&1 | tee deploy/wp5.10-finish.txt
#
# start:
#   1. pulls origin/main into /opt/adele (fast-forward only), uv sync in server/;
#   2. installs the fetch unit (new: XDG_STATE_HOME, where the openmeteo_* fetches write down their
#      calls) and reloads systemd; restarts adele-server.service, which reads the catalog at start;
#   3. validate, as adele;
#   4. enables the timers of the six datasets: their scheduled fetches start at once;
#   5. starts two backfills, each in an instance of the fetch unit that is not a dataset (runtime
#      drop-ins under /run, as in WP1 step 5), so that the timers of the datasets stay on:
#      - adele-fetch@openmeteo-backfill: deploy/backfill_by_window.py over the four Open-Meteo
#        datasets, one window at a time, in the order of PLAN. The fetches stop at 7,500 calls per
#        24 h and the script waits for the next room: about 27 days. A reboot stops it; `start`
#        again goes on, skipping the windows done (/var/cache/adele/state/adele/backfill-done.tsv);
#      - adele-fetch@ens-backfill: `backfill ecmwf_ifs_ens --start 2024-04-01`, one run per window
#        (no Open-Meteo calls; about 20 GB read from dynamical.org's S3, a few hours). It holds the
#        lock of ecmwf_ifs_ens: the ticks of that timer skip until it ends.
#   Claude follows both with sc-run: journalctl -u adele-fetch@openmeteo-backfill.service
# finish: once both have stopped: their summary, removal of the drop-ins, the timers.
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

BIN=/opt/adele/server/.venv/bin/adele-server
PY=/opt/adele/server/.venv/bin/python
CONF=/etc/adele/adele-server.toml
RUN=/run/systemd/system
UNIT=adele-fetch@.service
DATASETS="openmeteo_stations openmeteo_previous_runs openmeteo_single_runs openmeteo_era5 openmeteo_cams ecmwf_ifs_ens"
BACKFILLS="openmeteo-backfill ens-backfill"
DONE=/var/cache/adele/state/adele/backfill-done.tsv
# dataset,start,end,days per window; `today` = 00:00 UTC of the day of start. In this order: the
# rows of the backfill plan in docs/work-packages/WP5.10-weather-forecasts.md (calls estimated).
PLAN="openmeteo_previous_runs,2024-01-18,today,13
openmeteo_previous_runs,2021-03-22,2024-01-18,13
openmeteo_cams,2022-08-01,today,14
openmeteo_single_runs,2026-04-02,today,1
openmeteo_era5,2015-01-01,today,13
openmeteo_single_runs,2024-03-14,2026-04-02,1"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
mode=${1:-}
active() { systemctl show -p ActiveState --value "adele-fetch@$1.service"; }

start() {
  for b in $BACKFILLS; do
    [ "$(active "$b")" = activating ] && { echo "adele-fetch@$b.service is running. Stop."; exit 1; }
  done

  echo "== 1. pull"
  old=$(git -C /opt/adele rev-parse --short HEAD </dev/null)
  git -C /opt/adele fetch origin </dev/null || exit 1
  git -C /opt/adele cat-file -e origin/main:deploy/backfill_by_window.py </dev/null 2>/dev/null \
    || { echo "origin/main has no deploy/backfill_by_window.py: land WP5.10 and push first"; exit 1; }
  git -C /opt/adele merge --ff-only origin/main </dev/null || exit 1
  echo "was $old, now: $(git -C /opt/adele log -1 --format='%h %ad %s' --date=short </dev/null)"
  (cd /opt/adele/server && UV_PYTHON_INSTALL_DIR=/opt/uv-python /usr/local/bin/uv sync --no-dev --locked </dev/null) \
    || exit 1

  echo "== 2. the fetch unit, the query server"
  install -o root -g root -m 0644 "/opt/adele/deploy/$UNIT" /etc/systemd/system/
  systemctl daemon-reload
  systemctl show -p Environment adele-fetch@openmeteo_cams.service
  systemctl restart adele-server.service
  sleep 3
  curl -fsS http://127.0.0.1:8000/health </dev/null; echo

  echo "== 3. validate, as the user adele"
  (cd /tmp && sudo -u adele "$BIN" --config "$CONF" validate </dev/null) || exit 1

  echo "== 4. the timers of the six datasets"
  for id in $DATASETS; do systemctl enable --now "adele-fetch@$id.timer"; done

  echo "== 5. the two backfills"
  plan=$(echo "$PLAN" | tr '\n' ' ')
  for b in $BACKFILLS; do
    d="$RUN/adele-fetch@$b.service.d"
    install -d -m 0755 "$d"
    { echo "# WP5.10, written by deploy/wp5.10-backfill.sh; removed by its mode finish"
      echo "[Service]"
      echo "ExecStart="
      case $b in
        openmeteo-backfill) echo "ExecStart=$PY /opt/adele/deploy/backfill_by_window.py --bin $BIN --config $CONF --done $DONE $plan" ;;
        ens-backfill) echo "ExecStart=$BIN --config $CONF backfill ecmwf_ifs_ens --start 2024-04-01" ;;
      esac
      echo "TimeoutStartSec=infinity"
    } > "$d/backfill.conf"
    echo "-- $d/backfill.conf"; cat "$d/backfill.conf"
  done
  systemctl daemon-reload
  for b in $BACKFILLS; do systemctl start --no-block "adele-fetch@$b.service"; done
  sleep 20
  for b in $BACKFILLS; do
    echo "-- adele-fetch@$b.service"
    systemctl show -p ActiveState -p SubState -p MainPID "adele-fetch@$b.service"
    journalctl -u "adele-fetch@$b.service" -n 5 --no-pager -o short-iso </dev/null
  done
  systemctl list-timers --all --no-pager 'adele-fetch@*'
  echo "== started"
}

finish() {
  for b in $BACKFILLS; do
    [ "$(active "$b")" = activating ] && { echo "adele-fetch@$b.service is still running. Run finish later."; exit 1; }
  done
  for b in $BACKFILLS; do
    u="adele-fetch@$b.service"
    echo "== $u"
    systemctl show -p Result -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp "$u"
    echo "-- its last lines (summary, failed windows)"
    journalctl -u "$u" --no-pager -o cat </dev/null | grep -vE ' INFO ' | tail -25
  done
  echo "== remove the drop-ins"
  for b in $BACKFILLS; do rm -rf "$RUN/adele-fetch@$b.service.d"; done
  systemctl daemon-reload
  echo "== calls written down in the last 24 h"
  awk -v now="$(date +%s)" 'now - $1 < 86400 {n += $2} END {print n + 0}' \
    /var/cache/adele/state/adele/openmeteo-calls.tsv 2>/dev/null
  echo "== disk"; du -sh /var/lib/adele/* 2>/dev/null; df -h / | tail -1
  systemctl list-timers --all --no-pager 'adele-fetch@*'
}

case $mode in
  start) start ;;
  finish) finish ;;
  *) echo "usage: bash -s start|finish"; exit 2 ;;
esac
