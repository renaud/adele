#!/usr/bin/env bash
# Spreads the daily datasets over two hours, and limits the CPU of all adele fetches (2026-11-23).
# Why: every daily dataset is due at 00:00 UTC (a daily period is the UTC day), together with the
# hourly, 3-hourly and 6-hourly ones: 30 of 32 datasets. The machine's monitoring reports more than
# 85 % CPU for 5 minutes (1,125 CPU s of adele on 2026-11-23, almost all in 6 minutes of 4 cores),
# and the memory cap kills fetches at that time. This script, as root:
# 1. gives each of the 13 daily datasets a slot between 00:08 and 02:08 UTC (SLOTS below), through a
#    drop-in on its timer. The slots keep 8 minutes from minute 0 (the hourly fetches) and minute 30
#    (weathernext3), and 7 minutes from each other; heavy and light datasets alternate. The
#    timer doesn't tick between 00:00 and its slot. From the slot on it ticks every 10 minutes until
#    the end of the day, not every minute: a tick lost to a reboot, or to a backfill that holds
#    the lock, is made up 10 minutes later. A dataset fetched in its day is not due again, so the
#    other ticks do nothing;
# 2. limits adele's fetches together to 2.5 of the 4 cores (CPUQuota=250%) and gives them a low
#    share when others want the CPU (CPUWeight=20, the default is 100): systemctl set-property on
#    the slice that memory-guard.sh caps. The query server is not in that slice.
# It changes no code and needs no pull. It starts no fetch: today's daily fetches are done, the
# slots count from the next UTC day. `describe` still says that the next fetch of a daily dataset is
# at 00:00 (next_fetch_eta doesn't know the timers).
#
# Run from the repository root on the Mac:
#   ssh s 'sudo bash -s' < deploy/spread-fetches.sh 2>&1 | tee deploy/spread-fetches.txt
# Undo, as root:
#   rm /etc/systemd/system/adele-fetch@*.timer.d/slot.conf; systemctl daemon-reload
#   systemctl restart 'adele-fetch@*.timer'
#   systemctl set-property 'system-adele\x2dfetch.slice' CPUQuota= CPUWeight=
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

PY=/opt/adele/server/.venv/bin/python
DATASETS_DIR=/opt/adele/datasets
UNITS=/etc/systemd/system
SLICE='system-adele\x2dfetch.slice'
QUOTA=250%
WEIGHT=20
# dataset, slot (UTC)
SLOTS="meteoswiss_smn_stations 00:08
meteoswiss_smn_daily 00:15
entsoe_balancing_state 00:22
meteoswiss_smn_hourly 00:38
openmeteo_cams 00:45
pronovo_production 00:52
meteoswiss_nime_daily 01:08
swissgrid_imbalance_prices 01:15
openmeteo_era5 01:22
meteoswiss_smn_tenmin 01:38
openmeteo_previous_runs 01:45
entsoe_installed_capacity 01:52
meteoswiss_obs_daily 02:08"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
fail() { echo "FAILED: $*"; exit 1; }

calendars() {  # $1: slot HH:MM. The OnCalendar values: every 10 minutes from the slot to the end of the day
  local h=$((10#${1%:*})) m=$((10#${1#*:}))
  printf '*-*-* %02d:%02d..59/10:00 UTC\n' "$h" "$m"
  printf '*-*-* %02d..23:%02d/10:00 UTC\n' "$((h + 1))" "$((m % 10))"
}

echo "== 1. checks (nothing is changed before they pass)"
DATASETS_DIR="$DATASETS_DIR" SLOTS="$SLOTS" "$PY" -c '
import glob, os, sys, yaml
slots = dict(line.split() for line in os.environ["SLOTS"].splitlines())
daily = set()
for p in glob.glob(os.environ["DATASETS_DIR"] + "/*/datapackage.yaml"):
    d = yaml.safe_load(open(p))
    if str(d["adele"]["refresh"]["every"]) == "P1D":
        daily.add(d["name"])
if set(slots) != daily:
    sys.exit(f"without a slot: {sorted(daily - set(slots))}; not daily here: {sorted(set(slots) - daily)}")
if len(set(slots.values())) != len(slots):
    sys.exit("two datasets have the same slot")
print(f"{len(slots)} daily datasets, {len(slots)} slots from {min(slots.values())} to {max(slots.values())} UTC")
' </dev/null || fail "the slots are not the daily datasets"
while read -r id slot <&3; do
  systemctl is-enabled --quiet "adele-fetch@$id.timer" </dev/null || fail "adele-fetch@$id.timer is not enabled"
  while read -r c <&4; do
    systemd-analyze calendar "$c" </dev/null >/dev/null || fail "systemd refuses '$c'"
  done 4< <(calendars "$slot")
done 3<<<"$SLOTS"
[ "$(systemctl show -p LoadState --value "$SLICE" </dev/null)" = loaded ] || fail "no slice $SLICE"
echo "timers enabled, calendar expressions valid, slice loaded"

echo "== 2. the slots of the daily datasets"
while read -r id slot <&3; do
  d="$UNITS/adele-fetch@$id.timer.d"
  install -d -m 0755 "$d" || fail "$d"
  { echo "# deploy/spread-fetches.sh (2026-11-23): slot $slot UTC, then every 10 minutes"
    echo "[Timer]"
    echo "OnCalendar="
    calendars "$slot" | sed 's/^/OnCalendar=/'
  } > "$d/slot.conf" || fail "$d/slot.conf"
done 3<<<"$SLOTS"
systemctl daemon-reload </dev/null || fail "daemon-reload"
while read -r id slot <&3; do
  systemctl restart "adele-fetch@$id.timer" </dev/null || fail "restart adele-fetch@$id.timer"
done 3<<<"$SLOTS"
echo "example: $UNITS/adele-fetch@meteoswiss_smn_daily.timer.d/slot.conf"
cat "$UNITS/adele-fetch@meteoswiss_smn_daily.timer.d/slot.conf"

echo "== 3. the CPU of all adele fetches together"
systemctl set-property "$SLICE" CPUQuota="$QUOTA" CPUWeight="$WEIGHT" </dev/null || fail "set-property"
systemctl show -p CPUQuotaPerSecUSec -p CPUWeight -p MemoryMax -p MemorySwapMax "$SLICE" </dev/null
echo "(expected: CPUQuotaPerSecUSec=2.500s, CPUWeight=20, MemoryMax=4831838208, MemorySwapMax=0)"

echo "== 4. the timers now"
systemctl list-timers --all --no-pager 'adele-fetch@*' </dev/null | cut -c1-110
echo "== done. Look at the first night with: sar -u, the kills in memory.events, the statuses in /health"
