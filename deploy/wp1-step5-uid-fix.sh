#!/usr/bin/env bash
# WP1, step 5: new uids for adele and adele-query.
#
# Step 4 gave adele the uid 999 (the first free system uid). In the Docker containers of
# steacher.org, postgres and redis also run as uid 999, and Docker keeps the uids of the host
# (no user namespace). So every process of the fetch units (fetch.py and its dependencies) has
# the uid of the production database: it may send it signals, and the kernel's same-uid rule
# lets it open /proc/<pid>/environ and /proc/<pid>/root of those processes. adele-query (997)
# shares no uid today, but the top of the system range is where images put their users.
#
# This script stops the backfills and adele-server, gives adele uid 5100 and adele-query uid 5101
# (groups unchanged: adele 987, adele-query 986), hands the files of adele's three folders to the
# new uids, and starts everything again; the drop-ins of the backfill stay, so the backfills
# continue (weathernext3 skips the runs already stored, entsoe starts again).
# `usermod -u adele` refuses while a process has uid 999, and postgres has it: so the user is
# removed (userdel -f, which touches no process and no file) and created again.
#
# Run from the repository root on the Mac:
#   ssh s 'sudo bash -s' < deploy/wp1-step5-uid-fix.sh 2>&1 | tee deploy/wp1-step5-uid-fix.txt
set -euo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

NEW_ADELE=5100
NEW_QUERY=5101
DIRS="/var/lib/adele /var/log/adele /var/cache/adele"
UNITS="adele-fetch@entsoe_day_ahead_prices.service adele-fetch@weathernext3.service adele-server.service"

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ "$(id -u adele)" = 999 ] || { echo "adele has uid $(id -u adele), not 999: nothing to do"; exit 1; }
for u in $NEW_ADELE $NEW_QUERY; do
  getent passwd "$u" >/dev/null && { echo "uid $u is taken in passwd"; exit 1; }
  ps -eo uid= | grep -qx " *$u" && { echo "a process runs as uid $u"; exit 1; }
done

pg=$(pgrep -u 999 -o -x postgres || true)
probe() {  # what the user adele can do with the oldest postgres process (no content printed)
  if [ -z "$pg" ]; then echo "no postgres process with uid 999"; return; fi
  setpriv --reuid=adele --regid=adele --init-groups sh -c "
    head -c1 /proc/$pg/environ >/dev/null 2>&1 && echo '  environment of postgres: readable' || echo '  environment of postgres: not readable'
    ls /proc/$pg/root/ >/dev/null 2>&1 && echo '  root folder of its container: listable' || echo '  root folder of its container: not listable'
    kill -0 $pg 2>/dev/null && echo '  signals to postgres: allowed' || echo '  signals to postgres: refused'" </dev/null
}

echo "== 1. before: adele = uid $(id -u adele); postgres pid ${pg:-none}"
probe

echo "== 2. stop the backfills and adele-server"
systemctl stop $UNITS
for u in $UNITS; do echo "$u: $(systemctl show -p ActiveState --value "$u")"; done

echo "== 3. new uids"
userdel -f adele || true   # keeps the group adele: adele-query is a member
id adele >/dev/null 2>&1 && { echo "adele still exists: stop"; exit 1; }
useradd --system --uid "$NEW_ADELE" --gid adele --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin adele
usermod -u "$NEW_QUERY" adele-query
id adele; id adele-query; getent group adele

echo "== 4. files of the old uids in $DIRS"
find $DIRS -xdev -uid 999 -exec chown -h "$NEW_ADELE" {} +
find $DIRS -xdev -uid 997 -exec chown -h "$NEW_QUERY" {} +
install -d -o adele -g adele -m 2750 /var/lib/adele
install -d -o adele -g adele -m 2770 /var/log/adele
echo "left with uid 999 or 997: $(find $DIRS -xdev \( -uid 999 -o -uid 997 \) | wc -l) (expected 0)"
ls -ldn $DIRS

echo "== 5. after: adele = uid $(id -u adele)"
probe

echo "== 6. start again"
systemctl start adele-server.service
for _ in $(seq 1 20); do curl -fsS http://127.0.0.1:8000/health && { echo; break; }; sleep 1; done
systemctl start --no-block adele-fetch@entsoe_day_ahead_prices.service adele-fetch@weathernext3.service
sleep 10
for u in $UNITS; do echo "$u: $(systemctl show -p ActiveState --value "$u")"; done
ps -o uid,user,etime,comm -u "$NEW_ADELE,$NEW_QUERY" || true
echo "== done"
