#!/usr/bin/env bash
# WP1: memory limits for the fetch units (OOMScoreAdjust, MemoryMax, OOMPolicy in
# deploy/adele-fetch@.service; why: the comment there and the WP1 log of 2026-11-15).
# Pulls main into /opt/adele, but only if no file of server/, client/, datasets/ or skills/
# changed since the commit that runs: the week tests one version of the code. Then installs the
# fetch unit and reloads systemd. The timers keep running: a fetch that runs keeps the old
# settings, the next one gets the new ones.
#
# Push first, then run from the repository root on the Mac:
#   ssh s 'sudo bash -s' < deploy/wp1-memory-limits.sh 2>&1 | tee deploy/wp1-memory-limits.txt
set -euo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

UNIT=adele-fetch@.service
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

echo "== 1. pull"
old=$(git -C /opt/adele rev-parse --short HEAD </dev/null)
git -C /opt/adele fetch origin </dev/null
new=$(git -C /opt/adele rev-parse --short origin/main </dev/null)
echo "running: $old; origin/main: $new"
grep -q '^OOMScoreAdjust=' <(git -C /opt/adele show "origin/main:deploy/$UNIT" </dev/null) \
  || { echo "origin/main has no OOMScoreAdjust in deploy/$UNIT: push first"; exit 1; }
changed=$(git -C /opt/adele diff --name-only "$old" origin/main -- server client datasets skills </dev/null)
[ -z "$changed" ] || { echo "code changed since $old, not pulled:"; echo "$changed"; exit 1; }
git -C /opt/adele merge --ff-only origin/main </dev/null
git -C /opt/adele log -1 --format='%h %ad %s' --date=short </dev/null

echo "== 2. install the fetch unit"
install -o root -g root -m 0644 "/opt/adele/deploy/$UNIT" /etc/systemd/system/
systemctl daemon-reload
v=$(mktemp -d)   # systemd-analyze verify needs an instance name to resolve %i
cp "/etc/systemd/system/$UNIT" "$v/adele-fetch@weathernext3.service"
rc=0; systemd-analyze verify "$v/adele-fetch@weathernext3.service" || rc=$?
echo "systemd-analyze verify: rc=$rc (expected 0, no lines above)"
rm -rf "$v"

echo "== 3. what systemd now applies (expected: 4831838208, 1000, continue)"
for id in entsoe_day_ahead_prices weathernext3; do
  echo "-- adele-fetch@$id.service"
  systemctl show -p MemoryMax -p OOMScoreAdjust -p OOMPolicy "adele-fetch@$id.service"
done
systemctl list-timers --all --no-pager 'adele-fetch@*'
echo "== done"
