#!/usr/bin/env bash
# WP1, step 5 (docs/work-packages/WP1-server-on-steacher1.md): the backfills, then the timers.
# Two modes, run as root from the repository root on the Mac:
#   ssh s 'sudo bash -s start'  < deploy/wp1-step5-backfill.sh 2>&1 | tee deploy/wp1-step5-start.txt
#   ssh s 'sudo bash -s finish' < deploy/wp1-step5-backfill.sh 2>&1 | tee deploy/wp1-step5-finish.txt
#
# start: a runtime drop-in per dataset (/run/systemd/system/adele-fetch@<id>.service.d/) replaces
#   the `fetch --if-due` of the fetch unit by backfill commands, and starts the unit without
#   waiting. So each backfill runs as adele, in the sandbox of the real fetch unit, with the
#   secrets of its dataset only, and logs one line per window to the dataset's journal (Claude
#   reads it with sc-run). It goes on after the SSH session ends. A reboot removes the drop-ins.
# finish: once both units have stopped: their result, removal of the drop-ins, row counts through
#   the HTTP API (Claude compares them with the Mac), and the timer of each dataset whose
#   backfill succeeded. Prints no secret (the API key is read by Python and never printed).
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

BIN=/opt/adele/server/.venv/bin/adele-server
CONF=/etc/adele/adele-server.toml
RUN=/run/systemd/system
DATASETS="entsoe_day_ahead_prices weathernext3"
B="$BIN --config $CONF backfill"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
mode=${1:-}

state() { systemctl show -p ActiveState --value "adele-fetch@$1.service"; }

dropin() {  # the [Service] lines that replace ExecStart for one dataset
  case $1 in
    entsoe_day_ahead_prices)
      # 2014-12-31 as on the Mac: delivery day 2015-01-01 00:00 CET is 2014-12-31 23:00 UTC.
      # Windows of 365 days (no max_window); the end is now + horizon, so the backfill counts as
      # a scheduled run (last_scheduled_at moves to its start).
      echo "ExecStart=$B entsoe_day_ahead_prices --start 2014-12-31" ;;
    weathernext3)
      # The 3 sample runs of 2024-2025 first (the - lets the next line run if one fails), then
      # every run from 2026-11-12 00 UTC to now: the 6 sample runs of that day, with their clouds,
      # and a few days. One run per window (max_window PT1H). Runs whose `success` marker is not
      # there yet are left to the timer.
      echo "ExecStart=-$B weathernext3 --start 2024-11-12T00:00 --end 2024-11-12T01:00"
      echo "ExecStart=-$B weathernext3 --start 2025-11-12T00:00 --end 2025-11-12T04:00 --step-hours 4"
      echo "ExecStart=$B weathernext3 --start 2026-11-12" ;;
  esac
}

start() {
  for id in $DATASETS; do
    if systemctl is-enabled --quiet "adele-fetch@$id.timer"; then
      echo "the timer of $id is enabled: its ticks would run the backfill. Stop."; exit 1
    fi
    [ "$(state "$id")" = activating ] && { echo "adele-fetch@$id.service is running. Stop."; exit 1; }
  done
  for id in $DATASETS; do
    d="$RUN/adele-fetch@$id.service.d"
    install -d -m 0755 "$d"
    { echo "# WP1 step 5, written by deploy/wp1-step5-backfill.sh; removed by its mode finish"
      echo "[Service]"
      echo "ExecStart="
      dropin "$id"
      echo "TimeoutStartSec=infinity"
    } > "$d/backfill.conf"
    echo "== $d/backfill.conf"; cat "$d/backfill.conf"
  done
  systemctl daemon-reload
  for id in $DATASETS; do systemctl start --no-block "adele-fetch@$id.service"; done
  sleep 10
  for id in $DATASETS; do
    echo "== adele-fetch@$id.service"
    systemctl show -p ActiveState -p SubState -p MainPID "adele-fetch@$id.service"
    journalctl -u "adele-fetch@$id.service" -n 5 --no-pager -o short-iso
  done
  echo "== started. Follow:  sc-run 'journalctl -u adele-fetch@weathernext3.service -f'"
}

api_query() {  # $1: SQL. Prints the rows, tab-separated. The key never leaves Python.
  python3 - "$1" <<'PY'
import json, sys, tomllib, urllib.error, urllib.request
key = tomllib.load(open("/etc/adele/adele-server.toml", "rb"))["keys"]["renaud"]
req = urllib.request.Request("http://127.0.0.1:8000/query", data=json.dumps({"sql": sys.argv[1]}).encode(),
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.load(r)
except urllib.error.HTTPError as e:
    print("error:", e.code, e.read().decode()[:500]); sys.exit(0)
print(*res["columns"], sep="\t")
for row in res["rows"]:
    print(*row, sep="\t")
if res.get("truncated"):
    print(f"(truncated: {res['total']} rows in all)")
PY
}

finish() {
  for id in $DATASETS; do
    [ "$(state "$id")" = activating ] && { echo "adele-fetch@$id.service is still running. Run finish later."; exit 1; }
  done
  declare -A result
  for id in $DATASETS; do
    u="adele-fetch@$id.service"
    echo "== $u"
    systemctl show -p Result -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp "$u"
    result[$id]=$(systemctl show -p Result --value "$u")
    [ -n "$(systemctl show -p ExecMainStartTimestamp --value "$u")" ] || result[$id]="never ran"
    echo "-- the lines of the backfill command (summary, failed windows, problems)"
    journalctl -u "$u" --no-pager -o cat | grep -E '^(entsoe_day_ahead_prices|weathernext3): |^  (failed|problem|the scheduled)' | tail -20
  done
  echo "== remove the drop-ins"
  rm -rf "$RUN"/adele-fetch@*.service.d
  systemctl daemon-reload
  systemctl show -p DropInPaths adele-fetch@entsoe_day_ahead_prices.service adele-fetch@weathernext3.service

  echo "== health"; curl -fsS http://127.0.0.1:8000/health; echo
  echo "== entsoe: rows per zone and year before 2026 (Mac: 35 rows, 302439 in all)"
  api_query "SELECT bidding_zone, year(delivery_start AT TIME ZONE 'UTC') AS y, count(*) AS n
             FROM entsoe_day_ahead_prices.prices WHERE delivery_start < TIMESTAMPTZ '2026-01-01 00:00:00+00'
             GROUP BY ALL ORDER BY ALL"
  for t in "solar_radiation ssrd_p50" "weather total_cloud_cover_p50"; do
    set -- $t
    echo "== weathernext3.$1: the sample runs (to compare with the Mac)"
    api_query "SELECT strftime(init_time AT TIME ZONE 'UTC', '%Y-%m-%d %H') AS run, count(*) AS n, round(sum($2), 3) AS s
               FROM weathernext3.$1 WHERE init_time < TIMESTAMPTZ '2026-11-12 06:00:00+00' GROUP BY ALL ORDER BY ALL"
    echo "== weathernext3.$1: all runs"
    api_query "SELECT count(DISTINCT init_time) AS runs, count(*) AS n,
               strftime(min(init_time) AT TIME ZONE 'UTC', '%Y-%m-%d %H') AS first,
               strftime(max(init_time) AT TIME ZONE 'UTC', '%Y-%m-%d %H') AS last FROM weathernext3.$1"
  done
  echo "== disk"; du -sh /var/lib/adele/* 2>/dev/null; df -h / | tail -1

  echo "== timers (only for a backfill that succeeded)"
  for id in $DATASETS; do
    if [ "${result[$id]}" = success ]; then
      systemctl enable --now "adele-fetch@$id.timer"
    else
      echo "NOT enabled: adele-fetch@$id.timer (result of the backfill: ${result[$id]})"
    fi
  done
  systemctl list-timers --all --no-pager 'adele-fetch@*'
}

case $mode in
  start) start ;;
  finish) finish ;;
  *) echo "usage: bash -s start|finish"; exit 64 ;;
esac
