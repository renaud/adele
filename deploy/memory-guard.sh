#!/usr/bin/env bash
# After the freeze of 2026-11-17: the server stopped at 17:00:38 UTC (its journal ends there, no
# message of the OOM killer), 38 s after the hourly tick, with five backfill lanes beside the
# hourly fetches, and had to be rebooted at 17:32. Without swap, a machine out of memory evicts
# files and program code and may never reach the OOM killer. The cap per fetch unit (4.5 GiB)
# limits each fetch, not their sum; since the reboot, without any lane, the fetches together
# peaked at 5.08 GB, with about 5.4 GB available. Sampled every 2 s at 18:00 UTC on 2026-11-18,
# no backfill running: the available memory fell from 5,353 to 1,246 MB at 18:00:28 (four fetches,
# weathernext3 among them), and weathernext3 alone held 3.5-3.6 GB until 18:02. This script, as root:
# 1. pulls main into /opt/adele (fast-forward; deploy/backfill.sh gets its mode chain), uv sync;
# 2. a swap file of 4 GiB (/swapfile, in /etc/fstab) and vm.swappiness=10: idle memory of the
#    other services can go to disk, so a short peak slows the machine instead of stopping it;
# 3. a cap on all adele fetches together: MemoryMax=4608M on the slice that holds every
#    adele-fetch@ unit (systemctl set-property: a persistent drop-in in /etc/systemd/system.control).
#    Past it, the kernel kills a fetch inside the slice, whatever the other services do; the
#    server records the failure, and the dataset is fetched again in its next period (a daily one
#    the next day), from its last success on (D25). MemorySwapMax=0: adele
#    never swaps (a fetch that swaps crawls and holds the disk); the swap stays for the others;
# 4. weathernext3 (3.5 GB per fetch) ticks at minute 30 instead of every minute, away from the
#    hourly fetches that all start at minute 0 (a drop-in on its timer). Its runs appear about
#    7 h after their start time: 30 minutes later changes nothing for the data.
# It starts no backfill. Run from the repository root on the Mac, after the push:
#   ssh s 'sudo bash -s' < deploy/memory-guard.sh 2>&1 | tee deploy/memory-guard.txt
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

SLICE='system-adele\x2dfetch.slice'
CAP=4608M
SWAP=/swapfile
SWAP_SIZE=4G
WN3_DROPIN=/etc/systemd/system/adele-fetch@weathernext3.timer.d/minute.conf

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
fail() { echo "FAILED: $*"; exit 1; }

echo "== 1. pull"
old=$(git -C /opt/adele rev-parse --short HEAD </dev/null)
git -C /opt/adele fetch origin </dev/null || fail "git fetch"
git -C /opt/adele cat-file -e origin/main:deploy/memory-guard.sh </dev/null 2>/dev/null \
  || fail "origin/main has no deploy/memory-guard.sh: push first"
git -C /opt/adele merge --ff-only origin/main </dev/null || fail "git merge --ff-only"
echo "was $old, now: $(git -C /opt/adele log -1 --format='%h %ad %s' --date=short </dev/null)"
(cd /opt/adele/server && UV_PYTHON_INSTALL_DIR=/opt/uv-python /usr/local/bin/uv sync --no-dev --locked </dev/null) \
  || fail "uv sync"
if [ -n "$(git -C /opt/adele diff --name-only "$old" HEAD -- server/src </dev/null)" ]; then
  systemctl restart adele-server.service; echo "server/src changed: adele-server.service restarted"
fi

echo "== 2. swap"
if [ -n "$(swapon --noheadings </dev/null)" ]; then
  echo "swap is on already:"
else
  fs=$(findmnt -no FSTYPE / </dev/null)
  case $fs in ext4|xfs) ;; *) fail "the root file system is $fs: a swap file needs ext4 or xfs" ;; esac
  [ -e "$SWAP" ] && fail "$SWAP exists but is not in use: look at it first"
  free_gb=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
  [ "$free_gb" -ge 10 ] || fail "only $free_gb GB free on /"
  fallocate -l "$SWAP_SIZE" "$SWAP" && chmod 600 "$SWAP" && mkswap "$SWAP" </dev/null && swapon "$SWAP" </dev/null \
    || fail "swap file"
  grep -q "^$SWAP " /etc/fstab || echo "$SWAP none swap sw 0 0" >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/90-adele-swappiness.conf
sysctl -w vm.swappiness=10
swapon --show </dev/null; free -m | sed -n 1,3p; grep swap /etc/fstab

echo "== 3. cap on all adele fetches together"
systemctl set-property "$SLICE" MemoryMax="$CAP" MemorySwapMax=0 </dev/null || fail "set-property"
systemctl show -p MemoryMax -p MemorySwapMax -p MemoryCurrent "$SLICE" </dev/null
echo "(expected: MemoryMax=4831838208, MemorySwapMax=0)"

echo "== 4. weathernext3 at minute 30"
install -d -m 0755 "$(dirname "$WN3_DROPIN")"
{ echo "# deploy/memory-guard.sh (2026-11-18): away from the hourly fetches at minute 0"
  echo "[Timer]"
  echo "OnCalendar="
  echo "OnCalendar=*:30:00"
} > "$WN3_DROPIN"
systemctl daemon-reload
systemctl restart adele-fetch@weathernext3.timer
systemctl list-timers --all --no-pager adele-fetch@weathernext3.timer adele-fetch@entsoe_generation.timer
echo "== done. Backfills: deploy/backfill.sh chain (one lane at a time)"
