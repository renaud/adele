#!/usr/bin/env bash
# The update of steacher1 to main (2026-11-17): WP2, WP3, WP4 in the server, 30 new datasets.
# Phase A of the plan: the code, the units and the secrets. It enables no new timer: each new
# dataset gets its timer from deploy/backfill.sh (phase B), once its backfill has ended.
#
# Push main first, then run as root from the repository root on the Mac:
#   ssh s 'sudo bash -s' < deploy/update-main.sh 2>&1 | tee deploy/update-main.txt
#
# 1. checks: /opt/adele without local changes, origin/main holds deploy/backfill.sh, no backfill
#    drop-in left;
# 2. stops the timers of the two datasets that run (entsoe_day_ahead_prices, weathernext3) and
#    waits for their fetches to end;
# 3. backup of /var/lib/adele and /etc/adele (with the secrets) to /root/adele-backup-<time>.tgz;
# 4. git merge --ff-only origin/main, uv sync --no-dev --locked;
# 5. the three units (new in adele-fetch@.service: XDG_STATE_HOME, WP5.10), daemon-reload, verify;
# 6. secrets: each dataset that declares a variable in adele.secrets gets its file
#    /etc/adele/env.d/<id> (root 0600), the line copied from a file of env.d that holds that
#    variable (ENTSO_TOKEN: 12 new ENTSO-E datasets). Values are never printed;
# 7. validate, as adele;
# 8. restarts adele-server.service (it reads the catalog at start), GET /health;
# 9. starts the two timers again: their first runs are the test of the new code on old data, and
#    they fetch the time of the stop (D25).
# On a failure it stops and prints where it stopped; the timers then stay stopped.
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

BIN=/opt/adele/server/.venv/bin/adele-server
PY=/opt/adele/server/.venv/bin/python
CONF=/etc/adele/adele-server.toml
ENVD=/etc/adele/env.d
OLD="entsoe_day_ahead_prices weathernext3"
UNITS="adele-server.service adele-fetch@.service adele-fetch@.timer"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
step=0
old=""
fail() {
  echo "FAILED at step $step: $*"
  if [ "$step" -ge 2 ]; then
    echo "The timers of $OLD are stopped. Start them again: for id in $OLD; do systemctl start adele-fetch@\$id.timer; done"
  fi
  if [ "$step" -ge 4 ] && [ -n "$old" ]; then
    echo "Back to the code that ran ($old): git -C /opt/adele reset --hard $old, then"
    echo "  cd /opt/adele/server && UV_PYTHON_INSTALL_DIR=/opt/uv-python uv sync --no-dev --locked,"
    echo "  the units again (install + daemon-reload), systemctl restart adele-server.service"
  fi
  exit 1
}
active() { systemctl show -p ActiveState --value "adele-fetch@$1.service"; }

step=1; echo "== 1. checks"
[ -z "$(git -C /opt/adele status --porcelain </dev/null)" ] || fail "/opt/adele has local changes (git status)"
git -C /opt/adele fetch origin </dev/null || fail "git fetch"
git -C /opt/adele cat-file -e origin/main:deploy/backfill.sh </dev/null 2>/dev/null \
  || fail "origin/main has no deploy/backfill.sh: push main first"
leftover=$(ls -d /run/systemd/system/adele-fetch@*.service.d 2>/dev/null)
[ -z "$leftover" ] || { echo "$leftover"; fail "runtime drop-ins of fetch units exist (a backfill?): look at them first"; }
old=$(git -C /opt/adele rev-parse --short HEAD </dev/null)
echo "runs: $(git -C /opt/adele log -1 --format='%h %ad %s' --date=short </dev/null)"
echo "origin/main: $(git -C /opt/adele log -1 --format='%h %ad %s' --date=short origin/main </dev/null)"
df -h / | tail -1; free -m | sed -n 2p

step=2; echo "== 2. stop the two timers, wait for their fetches"
for id in $OLD; do systemctl stop "adele-fetch@$id.timer" || fail "stop adele-fetch@$id.timer"; done
for i in $(seq 1 120); do   # at most 20 minutes
  busy=""
  for id in $OLD; do [ "$(active "$id")" = activating ] && busy="$busy $id"; done
  [ -z "$busy" ] && break
  [ $((i % 6)) = 1 ] && echo "running:$busy (waiting)"
  sleep 10
done
[ -z "$busy" ] || fail "still running after 20 minutes:$busy"
echo "no fetch runs"

step=3; echo "== 3. backup (root only)"
backup=/root/adele-backup-$(date -u +%Y%m%dT%H%MZ)-$old.tgz
( umask 077; tar -C / -czf "$backup" var/lib/adele etc/adele </dev/null ) || fail "tar"
ls -l "$backup"

step=4; echo "== 4. code"
git -C /opt/adele merge --ff-only origin/main </dev/null || fail "git merge --ff-only"
echo "now: $(git -C /opt/adele log -1 --format='%h %ad %s' --date=short </dev/null)"
git -C /opt/adele diff --stat "$old" HEAD -- deploy server/pyproject.toml server/uv.lock </dev/null | tail -8
(cd /opt/adele/server && UV_PYTHON_INSTALL_DIR=/opt/uv-python /usr/local/bin/uv sync --no-dev --locked </dev/null) \
  || fail "uv sync"

step=5; echo "== 5. units"
for u in $UNITS; do
  install -o root -g root -m 0644 "/opt/adele/deploy/$u" /etc/systemd/system/ || fail "install $u"
done
systemctl daemon-reload || fail "daemon-reload"
v=$(mktemp -d)   # systemd-analyze verify needs instance names to resolve %i
cp /etc/systemd/system/adele-fetch@.service "$v/adele-fetch@openmeteo_cams.service"
cp /etc/systemd/system/adele-fetch@.timer "$v/adele-fetch@openmeteo_cams.timer"
cp /etc/systemd/system/adele-server.service "$v/"
rc=0; systemd-analyze verify "$v"/* </dev/null || rc=$?
rm -rf "$v"
echo "systemd-analyze verify: rc=$rc (expected 0, no lines above)"
[ "$rc" = 0 ] || fail "systemd-analyze verify"
systemctl show -p Environment adele-fetch@openmeteo_cams.service

step=6; echo "== 6. secrets (names only, never values)"
"$PY" - > /run/adele-secrets.txt <<'PY' || fail "reading adele.secrets of the descriptors"
import glob, yaml
for p in sorted(glob.glob("/opt/adele/datasets/*/datapackage.yaml")):
    d = yaml.safe_load(open(p))
    for v in (d.get("adele") or {}).get("secrets") or []:
        print(d["name"], v)
PY
missing=0
while read -r id var; do
  f="$ENVD/$id"
  if [ -f "$f" ] && grep -q "^$var=" "$f"; then echo "$id: $var there"; continue; fi
  src=$(grep -l "^$var=" "$ENVD"/* 2>/dev/null | head -1)
  if [ -z "$src" ]; then echo "$id: $var MISSING (no file of $ENVD holds it)"; missing=1; continue; fi
  ( umask 077; grep -m1 "^$var=" "$src" >> "$f" ) || fail "writing $f"
  chown root:root "$f"; chmod 0600 "$f"
  echo "$id: $var copied from $(basename "$src")"
done < /run/adele-secrets.txt
rm -f /run/adele-secrets.txt
ls -l "$ENVD"
[ "$missing" = 0 ] || fail "a secret is missing"

step=7; echo "== 7. validate, as adele"
(cd /tmp && sudo -u adele "$BIN" --config "$CONF" validate </dev/null) || fail "validate"

step=8; echo "== 8. the query server"
systemctl restart adele-server.service || fail "restart adele-server.service"
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health </dev/null >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/health </dev/null || fail "GET /health"
echo

step=9; echo "== 9. the two timers again"
for id in $OLD; do systemctl start "adele-fetch@$id.timer" || fail "start adele-fetch@$id.timer"; done
systemctl list-timers --all --no-pager 'adele-fetch@*'
echo "== done. Backup: $backup. Next: phase B, deploy/backfill.sh"
