#!/usr/bin/env bash
# The update of the server to main (2026-11-17), phase B: the backfills of the new datasets, then
# the timer of each. Phase A (deploy/update-main.sh) must have run. This script runs from the
# checkout on the server, as root:
#   ssh s 'sudo bash /opt/adele/deploy/backfill.sh start' 2>&1 | tee deploy/backfill-start.txt
#   ssh s 'sudo bash /opt/adele/deploy/backfill.sh chain entsoe files ens' 2>&1 | tee deploy/backfill-chain.txt
#   ssh s 'sudo bash /opt/adele/deploy/backfill.sh swissgrid <folder>' 2>&1 | tee deploy/backfill-swissgrid.txt
#   ssh s 'sudo bash /opt/adele/deploy/backfill.sh report' 2>&1 | tee deploy/backfill-report.txt
#   ssh s 'sudo bash /opt/adele/deploy/backfill.sh stop'
#
# start [lane ...]: starts each lane (default: entsoe files ens openmeteo) as a transient root unit,
#   adele-backfill-<lane>.service (systemd-run), which goes on after the SSH session ends. A lane
#   runs its items one after the other (the list is in lane_items below):
#   - bf <id> <args>: `adele-server backfill <id> <args>` in the dataset's own fetch unit (user
#     adele, its sandbox, its memory limit, its secrets), through a runtime drop-in with a single
#     ExecStart (/run/systemd/system/adele-fetch@<id>.service.d/backfill.conf; a chain of
#     ExecStart=- lines made the stop hang in WP1). `systemctl start` waits for the end and gives
#     the exit code; then the drop-in is removed.
#   - timer <id>: systemctl enable --now adele-fetch@<id>.timer.
#   - ds <id> <args>: bf, then timer.
#   - import <id> <folder>: `adele-server import`, the same way as bf.
#   - openmeteo-windows <instance>: deploy/backfill_by_window.py over the plan of WP5.10, in
#     adele-fetch@<instance>, which is not a dataset; the timers of the openmeteo_* datasets are
#     on (WP5.10: one lock per window, the scheduled fetches get the larger call budget).
#   A timer comes after the backfill of its dataset: an import is refused after the first
#   scheduled run, and in an append-only dataset rows backfilled after the first scheduled run
#   would get a fetched_at later than versions_since (D30). After a failed item, the later items
#   of that dataset are skipped, so its timer stays off.
#   Each result is a line of /var/lib/adele-deploy/backfill.tsv (readable by Claude with sc-run).
#   A lane started again skips the items written there as ok: after a fix or a reboot, `start`
#   again.
# chain <lane> ...: the lanes one after the other, in one unit (adele-backfill-chain). Since the
#   freeze of 2026-11-17 (five lanes at once beside the hourly fetches, at 17:00 UTC): one lane
#   at a time, beside at most openmeteo (light: one window of station points at a time), and
#   only with the memory cap of deploy/memory-guard.sh.
# swissgrid <folder>: WP4 step 6, after Renaud's three confirmations (WP4 doc, "To confirm before
#   the server"). <folder> holds the poller's folders total-system-imbalance/ and
#   control-area-balance-daily/. They are copied to /srv/adele-import/swissgrid-poller/ (the
#   fetch units can't read /home), then the lane swissgrid: the two imports, their timers, the
#   backfill of swissgrid_balance, its timer.
# report: at any time. The lanes, the results, the drop-ins, per dataset its status and problems
#   (state.json) and per table the rows, first and last time through the HTTP API (the API key
#   is read by Python, never printed), the timers, disk and memory.
# stop: stops the lanes and the backfills they started (each backfill records "interrupted"),
#   removes the drop-ins.
set -uo pipefail

BIN=/opt/adele/server/.venv/bin/adele-server
PY=/opt/adele/server/.venv/bin/python
CONF=/etc/adele/adele-server.toml
RUN=/run/systemd/system
STATE=/var/lib/adele-deploy
RESULTS=$STATE/backfill.tsv
RELOAD_LOCK=/run/adele-backfill.lock
DONE=/var/cache/adele/state/adele/backfill-done.tsv   # backfill_by_window.py: the windows done
IMPORT=/srv/adele-import/swissgrid-poller
LANES="entsoe files ens openmeteo"
# dataset,start,end,days per window, in this order: the backfill plan of
# docs/work-packages/WP5.10-weather-forecasts.md (as in deploy/wp5.10-backfill.sh).
OPENMETEO_PLAN="openmeteo_previous_runs,2024-01-18,today,13 openmeteo_previous_runs,2021-03-22,2024-01-18,13
openmeteo_cams,2022-08-01,today,14 openmeteo_single_runs,2026-04-02,today,1 openmeteo_era5,2015-01-01,today,13
openmeteo_single_runs,2024-03-14,2026-04-02,1"

lane_items() {
  case $1 in
    # One token for all: one ENTSO-E dataset at a time. entsoe_generation first: 14 checks of
    # entsoe_wind_solar_forecast read it (D34). Starts as on the Mac (WP3, WP5.1 to WP5.3).
    entsoe) cat <<'EOF'
ds entsoe_generation --start 2014-12-31
ds entsoe_wind_solar_forecast --start 2014-12-31
ds entsoe_wind_solar_forecast_neighbours --start 2014-12-31
ds entsoe_load --start 2014-12-31
ds entsoe_physical_flows --start 2014-12-31
ds entsoe_scheduled_exchanges --start 2014-12-31
ds entsoe_imbalance_volume --start 2014-12-31
ds entsoe_imbalance_prices --start 2014-12-31
ds entsoe_imbalance_volume_neighbours --start 2014-12-31
ds entsoe_activated_balancing_prices --start 2014-12-31
ds entsoe_balancing_state --start 2014-12-31
ds entsoe_installed_capacity --start 2014-12-31
EOF
    ;;
    # Files of MeteoSwiss, Pronovo, Energy-Charts, Swissgrid: one at a time, because the hourly
    # MeteoSwiss windows take up to 2.75 GB (WP5.7: windows that end where the decade files end).
    files) cat <<'EOF'
ds meteoswiss_smn_stations --start 2026-11-01 --step-days 30
ds meteoswiss_obs_daily --start 2010-01-01 --step-days 7000
ds meteoswiss_nime_daily --start 2010-01-01 --step-days 7000
ds meteoswiss_smn_daily --start 2009-12-31T23:40:00Z --step-days 7000
bf meteoswiss_smn_hourly --start 2015-01-01 --end 2019-12-31T23:00:00Z --step-days 2000
bf meteoswiss_smn_hourly --start 2019-12-31T23:00:00Z --end 2025-12-31T23:00:00Z --step-days 2500
bf meteoswiss_smn_hourly --start 2025-12-31T23:00:00Z --step-days 400
timer meteoswiss_smn_hourly
bf meteoswiss_smn_tenmin --start 2023-10-01 --end 2025-12-31T23:50:00Z --step-days 1000
bf meteoswiss_smn_tenmin --start 2025-12-31T23:50:00Z --step-days 400
timer meteoswiss_smn_tenmin
ds pronovo_production --start 2019-12-31T23:00:00Z
ds energy_charts_intraday_prices --start 2014-12-31T23:00:00Z
ds swissgrid_imbalance_prices --start 2022-12-31T23:00:00Z
EOF
    ;;
    # dynamical.org's S3, all 19 variables: about 140 GB read, 2 days or more (WP5.10)
    ens) cat <<'EOF'
ds ecmwf_ifs_ens --start 2024-04-01
EOF
    ;;
    # About 220,000 Open-Meteo calls at 7,500 a day: about 30 days (WP5.10)
    openmeteo) cat <<'EOF'
timer openmeteo_stations
timer openmeteo_previous_runs
timer openmeteo_single_runs
timer openmeteo_era5
timer openmeteo_cams
openmeteo-windows openmeteo-backfill
EOF
    ;;
    swissgrid) cat <<EOF
import swissgrid_tsi $IMPORT/total-system-imbalance
timer swissgrid_tsi
import swissgrid_balance_daily $IMPORT/control-area-balance-daily
timer swissgrid_balance_daily
ds swissgrid_balance --start 2024-10-31
EOF
    ;;
    # IEM's METAR (2026-11-23): 12 requests, about 4 min and 0.5 GB on the Mac. Not at minute 0 or 30
    # (hourly fetches, weathernext3). Then the slot of iem_metar: deploy/spread-fetches.sh.
    metar) cat <<'EOF'
ds iem_metar --start 2015-01-01 --step-days 366
EOF
    ;;
    *) return 1 ;;
  esac
}

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
mode=${1:-}
[ $# -gt 0 ] && shift

now() { date -u '+%Y-%m-%d %H:%M:%S'; }
reload() { flock "$RELOAD_LOCK" systemctl daemon-reload; }
active() { systemctl show -p ActiveState --value "$1"; }

in_unit() {  # $1: instance; the rest: the command, run as ExecStart of adele-fetch@<instance>.service
  local inst=$1; shift
  local u="adele-fetch@$inst.service" d="$RUN/adele-fetch@$inst.service.d" rc=0
  if systemctl is-enabled --quiet "adele-fetch@$inst.timer" 2>/dev/null; then
    echo "the timer of $inst is on: its ticks would run this command instead of a fetch"; return 3
  fi
  [ "$(active "$u")" = activating ] && { echo "$u runs already"; return 3; }
  install -d -m 0755 "$d"
  { echo "# written by deploy/backfill.sh, lane $LANE, $(now) UTC; removed when the command ends"
    echo "[Service]"
    echo "ExecStart="
    echo "ExecStart=$*"
    echo "TimeoutStartSec=infinity"
  } > "$d/backfill.conf"
  reload
  systemctl start "$u" </dev/null || rc=$?
  rm -rf "$d"
  reload
  return $rc
}

done_before() {  # $1: the item; true when the lane wrote it as ok
  awk -F'\t' -v l="$LANE" -v i="$1" '$2 == "ok" && $3 == l && $4 == i {f = 1} END {exit !f}' "$RESULTS"
}

record() {  # $1: result, $2: item
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$LANE" "$2" >> "$RESULTS"
  echo "== $(now) $1: $2"
}

lane() {  # runs inside adele-backfill-<lane>.service or adele-backfill-chain.service: the lanes in turn
  for l in "$@"; do run_lane "$l"; done
}

run_lane() {
  LANE=$1
  local items kind id rest item rc t0 failed=" "
  items=$(lane_items "$LANE") || { echo "unknown lane $LANE"; return 64; }
  install -d -m 0755 "$STATE"; touch "$RESULTS"; chmod 0644 "$RESULTS"
  while read -r kind id rest <&3; do
    [ -n "$kind" ] || continue
    item="$kind $id${rest:+ $rest}"
    if done_before "$item"; then echo "== ok before: $item"; continue; fi
    case $failed in *" $id "*) record "skipped (an earlier item of $id failed)" "$item"; continue ;; esac
    echo "== $(now) start: $item"
    rc=0; t0=$(date +%s)
    case $kind in
      bf|ds) in_unit "$id" "$BIN" --config "$CONF" backfill "$id" $rest || rc=$? ;;
      import) in_unit "$id" "$BIN" --config "$CONF" import "$id" $rest || rc=$? ;;
      timer) ;;
      openmeteo-windows)
        plan=$(echo $OPENMETEO_PLAN)
        in_unit "$id" "$PY" /opt/adele/deploy/backfill_by_window.py --bin "$BIN" --config "$CONF" --done "$DONE" $plan \
          || rc=$? ;;
      *) echo "unknown item"; rc=64 ;;
    esac
    case $kind in bf|ds|import|openmeteo-windows)
      journalctl -u "adele-fetch@$id.service" --since "@$t0" --no-pager -o cat </dev/null \
        | grep -E "^$id: |^  (failed|problem|not merged|the scheduled)| done: [0-9]+ windows failed|^[0-9: -]+  [a-z_]+ --start " \
        | tail -15 ;;
    esac
    if [ "$rc" = 0 ] && { [ "$kind" = timer ] || [ "$kind" = ds ]; }; then
      systemctl enable --now "adele-fetch@$id.timer" </dev/null || rc=$?
    fi
    if [ "$rc" = 0 ]; then
      record ok "$item"
    else
      record "failed (exit $rc)" "$item"
      failed="$failed$id "
    fi
  done 3<<<"$items"
  echo "== $(now) lane $LANE ended. Its results:"
  awk -F'\t' -v l="$LANE" '$3 == l' "$RESULTS"
}

check_phase_a() {
  cmp -s /opt/adele/deploy/adele-fetch@.service /etc/systemd/system/adele-fetch@.service \
    || { echo "the installed fetch unit is not the one of /opt/adele: run deploy/update-main.sh first"; exit 1; }
  [ -f /etc/adele/env.d/entsoe_generation ] || { echo "no /etc/adele/env.d/entsoe_generation: run deploy/update-main.sh first"; exit 1; }
}

start_lane() {  # $1: lane
  local unit="adele-backfill-$1"
  lane_items "$1" >/dev/null || { echo "unknown lane $1"; return 1; }
  if [ "$(active "$unit.service")" = active ]; then echo "$unit runs already"; return 0; fi
  systemd-run --collect --unit="$unit" --description="adele: backfill lane $1 (deploy/backfill.sh)" \
    /bin/bash /opt/adele/deploy/backfill.sh lane "$1" </dev/null
}

show_started() {
  sleep 20
  systemctl list-units --all --no-pager 'adele-backfill-*' 'adele-fetch@*.service'
  for l in "$@"; do
    echo "-- adele-backfill-$l"
    journalctl -u "adele-backfill-$l.service" -n 4 --no-pager -o cat </dev/null
  done
  echo "Follow: sc-run 'journalctl -u adele-backfill-entsoe -f', results: /var/lib/adele-deploy/backfill.tsv"
}

start() {
  check_phase_a
  local lanes=${*:-$LANES}
  for l in $lanes; do start_lane "$l"; done
  show_started $lanes
}

chain() {  # the lanes one after the other, in one unit: adele-backfill-chain
  [ $# -gt 0 ] || { echo "usage: backfill.sh chain <lane> <lane> ..."; exit 64; }
  check_phase_a
  for l in "$@"; do lane_items "$l" >/dev/null || { echo "unknown lane $l"; exit 64; }; done
  [ "$(active adele-backfill-chain.service)" = active ] && { echo "a chain runs already"; exit 1; }
  systemd-run --collect --unit=adele-backfill-chain --description="adele: backfill lanes $* in turn (deploy/backfill.sh)" \
    /bin/bash /opt/adele/deploy/backfill.sh lane "$@" </dev/null
  show_started chain
}

swissgrid() {
  local src=${1:-}
  [ -n "$src" ] || { echo "usage: backfill.sh swissgrid <folder that holds total-system-imbalance/ and control-area-balance-daily/>"; exit 64; }
  check_phase_a
  for s in total-system-imbalance control-area-balance-daily; do
    [ -d "$src/$s" ] || { echo "no folder $src/$s"; exit 1; }
  done
  [ "$(active adele-backfill-swissgrid.service)" = active ] && { echo "the lane swissgrid runs already"; exit 1; }
  echo "== copy of the poller's answers to $IMPORT"
  install -d -o root -g adele -m 0750 /srv/adele-import "$IMPORT"
  for s in total-system-imbalance control-area-balance-daily; do
    cp -a "$src/$s" "$IMPORT/" || exit 1
    echo "$s: $(find "$IMPORT/$s" -name '*.gz' | wc -l) answers, $(du -sh "$IMPORT/$s" | cut -f1), last day $(ls "$IMPORT/$s" | grep -E '^[0-9]{4}-' | sort | tail -1)"
  done
  chown -R root:adele "$IMPORT"; chmod -R u=rwX,g=rX,o= "$IMPORT"
  start_lane swissgrid
  show_started swissgrid
}

report() {
  echo "== $(now) UTC, lanes"
  systemctl list-units --all --no-pager --no-legend 'adele-backfill-*'
  echo "== backfills running"
  systemctl list-units --no-pager --no-legend --state=activating 'adele-fetch@*.service'
  echo "== drop-ins"
  ls "$RUN"/adele-fetch@*.service.d/ 2>/dev/null || echo "none"
  echo "== results ($RESULTS)"
  cat "$RESULTS" 2>/dev/null
  echo "== datasets: status from state.json, rows through the HTTP API"
  "$PY" - <<'PY'
import json, urllib.error, urllib.request
from adele_server import catalog, config
cfg = config.load("/etc/adele/adele-server.toml")
cat = catalog.load_catalog(cfg.datasets_dirs)
key = next(iter(cfg.keys.values()))

def q(sql):
    req = urllib.request.Request("http://127.0.0.1:8000/query", data=json.dumps({"sql": sql}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["rows"][0]
    except urllib.error.HTTPError as e:
        return f"error {e.code}: {e.read().decode()[:300]}"
    except Exception as e:
        return f"error: {e}"

for ds_id in sorted(cat):
    p = cfg.data_dir / ds_id / "state.json"
    st = json.loads(p.read_text()) if p.exists() else {}
    pc = st.get("published_checks") or {}
    print(f"{ds_id}: {st.get('status', 'never fetched')}, last scheduled {st.get('last_scheduled_at', '-')}, "
          f"checks {pc.get('count', '-')}, versions_since {st.get('versions_since', '-')}")
    for pr in (st.get("problems") or [])[:5]:
        print(f"  problem: {pr}")
    if not p.exists():
        continue
    for t in cat[ds_id].tables.values():
        f = (t.window or t.time_field) if t.has_time else None  # forecasts: the run (init_time)
        sql = f"SELECT count(*), min({f}), max({f}) FROM {t.sql_name}" if f else f"SELECT count(*) FROM {t.sql_name}"
        print(f"  {t.sql_name}: {q(sql)}")
PY
  echo "== timers"
  systemctl list-units --all --plain --no-legend 'adele-fetch@*.timer' \
    | awk '{sub(/^adele-fetch@/, "", $1); sub(/\.timer$/, "", $1); printf "%s ", $1} END {print ""; print NR " timers"}'
  echo "== disk, memory"
  du -sh /var/lib/adele/* 2>/dev/null | sort -h | tail -12
  df -h / | tail -1; free -m | sed -n 2p
}

stop() {
  for u in $(systemctl list-units --all --plain --no-legend 'adele-backfill-*' | awk '{print $1}'); do
    echo "stop $u"; systemctl stop "$u"
  done
  for d in "$RUN"/adele-fetch@*.service.d; do
    [ -d "$d" ] || continue
    inst=${d#"$RUN"/adele-fetch@}; inst=${inst%.service.d}
    echo "stop adele-fetch@$inst.service"; systemctl stop "adele-fetch@$inst.service"
    rm -rf "$d"
  done
  reload
  systemctl list-units --all --no-pager 'adele-backfill-*' 'adele-fetch@*.service'
}

case $mode in
  start) start "$@" ;;
  chain) chain "$@" ;;
  swissgrid) swissgrid "$@" ;;
  report) report ;;
  stop) stop ;;
  lane) lane "$@" ;;
  *) echo "usage: backfill.sh start [lane ...] | chain <lane> <lane> ... | swissgrid <folder> | report | stop   (lanes: $LANES)"; exit 64 ;;
esac
