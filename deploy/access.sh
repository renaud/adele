#!/usr/bin/env bash
# Access from outside (D35, 2026-11-23): the limits on queries, then HTTPS on port 8443.
#
# Push main first, then run as root from the repository root on the Mac, with the DNS name of the
# server (it is in SERVER.md, not in git):
#   ssh s 'sudo bash -s -- <dns name>' < deploy/access.sh 2>&1 | tee deploy/access.txt
# The output shows "<host>" in place of the name. The script can be run again.
#
# 1. checks (nothing is changed before they pass): /opt/adele without local changes, origin/main
#    holds this version, port 8443 and uid 5102 free (or already adele-caddy's), 5 GB of disk;
# 2. /opt/adele to origin/main, uv sync, validate. The timers and a backfill go on: each fetch is a
#    new process, as with memory-guard.sh;
# 3. adele-server.service with its limits (MemoryMax=3G), restart, GET /health; prints the limits
#    that the config gives (never the keys);
# 4. the user adele-caddy (uid 5102) and Caddy, pinned, in /usr/local/bin (its sha512 is below);
# 5. /etc/adele-caddy/Caddyfile from deploy/Caddyfile, checked with `caddy validate`;
# 6. adele-caddy.service. It listens on 8443; the internet reaches it once the port is open in the
#    panel of the hosting provider;
# 7. check on this machine, with the Python of adele (3.13 checks certificates strictly): /health
#    answers 200 and /datasets without a key 401, both over HTTPS. If not, Caddy is stopped;
# 8. the root certificate (public) to /etc/adele-caddy/root.crt, readable by everyone: it goes into
#    the client package (client/src/adele/adele-ca.pem). A backup of the authority, with its
#    private key, to /root (root only).
#
# Undo HTTPS, as root: systemctl disable --now adele-caddy.service
# Undo the limits: git -C /opt/adele reset --hard <the commit printed at step 1>, uv sync,
#   install deploy/adele-server.service, systemctl daemon-reload, restart adele-server.service
set -uo pipefail
# bash reads this script from stdin (bash -s): external programs that could read stdin get </dev/null.

HOST=${1:-}
CADDY_VERSION=2.11.9
CADDY_SHA512=0e85544340290a16ce4bfb76fe7d65e9de1bf3a6e67f5ccfff30b30d27ea4c73e078077b7bf3e58ae60b6b12e44327705287059c775bca5782e8ee85ea7edd75
PORT=8443
CADDY_UID=5102
PY=/opt/adele/server/.venv/bin/python
export PYTHONDONTWRITEBYTECODE=1  # root must not leave __pycache__ in /opt/adele
CONF=/etc/adele/adele-server.toml
STATE=/var/lib/adele-caddy
ETC=/etc/adele-caddy

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[[ $HOST =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$ ]] || { echo "usage: bash -s -- <dns name of the server>"; exit 1; }
step=0
fail() { echo "FAILED at step $step: $*"; exit 1; }

main() {
step=1; echo "== 1. checks"
getent ahosts "$HOST" >/dev/null </dev/null || fail "the DNS name doesn't resolve"
# tracked files only: git merge refuses by itself to overwrite an untracked file
[ -z "$(git -C /opt/adele status --porcelain --untracked-files=no </dev/null)" ] || fail "/opt/adele has local changes (git status)"
git -C /opt/adele fetch -q origin </dev/null || fail "git fetch"
git -C /opt/adele cat-file -e origin/main:deploy/adele-caddy.service </dev/null 2>/dev/null \
  || fail "origin/main has no deploy/adele-caddy.service: push main first"
if [ -n "$(ss -ltnH "sport = :$PORT" </dev/null)" ] && ! systemctl is-active -q adele-caddy.service; then
  fail "port $PORT is taken by another service"
fi
owner=$(getent passwd "$CADDY_UID" </dev/null | cut -d: -f1)
[ -z "$owner" ] || [ "$owner" = adele-caddy ] || fail "uid $CADDY_UID belongs to $owner"
# Docker keeps the uids of its images: a process may have a uid that /etc/passwd doesn't know
[ -n "$owner" ] || [ -z "$(ps -eo uid= </dev/null | tr -d ' ' | grep -x "$CADDY_UID")" ] || fail "uid $CADDY_UID is in use"
free_gb=$(df --output=avail -BG / </dev/null | tail -1 | tr -dc 0-9)
[ "$free_gb" -ge 5 ] || fail "only $free_gb GB free on /"
echo "runs: $(git -C /opt/adele log -1 --format='%h %ad' --date=short </dev/null); $free_gb GB free"
free -m </dev/null | sed -n 1,3p

step=2; echo "== 2. code"
git -C /opt/adele merge -q --ff-only origin/main </dev/null || fail "git merge --ff-only"
(cd /opt/adele/server && UV_PYTHON_INSTALL_DIR=/opt/uv-python /usr/local/bin/uv sync -q --no-dev --locked </dev/null) \
  || fail "uv sync"
echo "now: $(git -C /opt/adele log -1 --format='%h %ad' --date=short </dev/null)"
(cd /tmp && sudo -u adele /opt/adele/server/.venv/bin/adele-server --config "$CONF" validate </dev/null | tail -2) \
  || fail "validate"

step=3; echo "== 3. the query server, with its limits"
"$PY" - "$CONF" <<'PY' || fail "reading the config"
import sys
from adele_server import config
c = config.load(sys.argv[1])
print("queries:", c.query); print("checks: ", c.checks); print("keys:   ", len(c.keys))
if c.query != config.QueryLimits():
    print("NOTE: [query] of the config changes the defaults of D35")
PY
install -o root -g root -m 0644 /opt/adele/deploy/adele-server.service /etc/systemd/system/ || fail "install the unit"
systemctl daemon-reload || fail "daemon-reload"
systemctl restart adele-server.service || fail "restart adele-server.service"
ok=no
for _ in $(seq 1 30); do
  curl -fsS -o /dev/null http://127.0.0.1:8000/health </dev/null 2>/dev/null && { ok=yes; break; }
  sleep 1
done
[ "$ok" = yes ] || { journalctl -u adele-server.service -n 20 --no-pager -o cat </dev/null; fail "GET /health"; }
systemctl show -p MemoryMax -p MemorySwapMax -p OOMScoreAdjust adele-server.service </dev/null
echo "(expected: MemoryMax=3221225472, MemorySwapMax=0, OOMScoreAdjust=900)"

step=4; echo "== 4. user and Caddy $CADDY_VERSION"
id adele-caddy >/dev/null 2>&1 || useradd --system --uid "$CADDY_UID" --user-group --no-create-home \
  --home-dir /nonexistent --shell /usr/sbin/nologin adele-caddy || fail "useradd"
id adele-caddy
if [ "$(/usr/local/bin/caddy version 2>/dev/null </dev/null | cut -d' ' -f1)" = "v$CADDY_VERSION" ]; then
  echo "already there"
else
  tmp=$(mktemp -d); f=caddy_${CADDY_VERSION}_linux_amd64.tar.gz
  curl -fsSL -o "$tmp/$f" "https://github.com/caddyserver/caddy/releases/download/v$CADDY_VERSION/$f" </dev/null \
    || fail "download"
  echo "$CADDY_SHA512  $tmp/$f" | sha512sum -c --quiet - || fail "the sha512 of Caddy differs: nothing installed"
  tar -xzf "$tmp/$f" -C "$tmp" caddy </dev/null && install -o root -g root -m 0755 "$tmp/caddy" /usr/local/bin/caddy \
    || fail "install caddy"
  rm -rf "$tmp"
fi
/usr/local/bin/caddy version </dev/null

step=5; echo "== 5. Caddyfile"
install -d -o root -g root -m 0755 "$ETC"
install -d -o adele-caddy -g adele-caddy -m 0700 "$STATE"
sed "s/ADELE_HOST/$HOST/" /opt/adele/deploy/Caddyfile > "$ETC/Caddyfile.new" || fail "Caddyfile"
chmod 0644 "$ETC/Caddyfile.new"
# as adele-caddy: validate already makes the authority in $STATE
(cd /tmp && sudo -u adele-caddy env XDG_DATA_HOME="$STATE" XDG_CONFIG_HOME="$STATE" \
  /usr/local/bin/caddy validate --config "$ETC/Caddyfile.new" --adapter caddyfile </dev/null 2>&1 | tail -5) \
  || fail "caddy validate"
mv "$ETC/Caddyfile.new" "$ETC/Caddyfile"

step=6; echo "== 6. adele-caddy.service"
install -o root -g root -m 0644 /opt/adele/deploy/adele-caddy.service /etc/systemd/system/ || fail "install the unit"
systemctl daemon-reload || fail "daemon-reload"
systemd-analyze verify /etc/systemd/system/adele-server.service /etc/systemd/system/adele-caddy.service </dev/null \
  || fail "systemd-analyze verify"
systemctl enable -q adele-caddy.service && systemctl restart adele-caddy.service || fail "start adele-caddy.service"
root=$STATE/pki/authorities/local/root.crt
for _ in $(seq 1 30); do
  [ -s "$root" ] && [ -n "$(ss -ltnH "sport = :$PORT" </dev/null)" ] && break
  sleep 1
done
if [ ! -s "$root" ]; then
  journalctl -u adele-caddy.service -n 20 --no-pager -o cat </dev/null
  systemctl disable -q --now adele-caddy.service
  fail "no root certificate at $root"
fi
systemctl is-active adele-caddy.service
ss -ltnH "sport = :$PORT" </dev/null

step=7; echo "== 7. HTTPS on this machine"
if ! "$PY" - "$HOST" "$PORT" "$root" <<'PY'
import socket, ssl, sys, time
host, port, ca = sys.argv[1], int(sys.argv[2]), sys.argv[3]
ctx = ssl.create_default_context(cafile=ca)
print("python", sys.version.split()[0], "strict:", bool(ctx.verify_flags & ssl.VERIFY_X509_STRICT))
def get(path):
    with socket.create_connection(("127.0.0.1", port), 10) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        t.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n".encode())
        return int(t.makefile("rb").readline().split()[1])
for i in range(15):  # the first certificate takes a moment
    try:
        got = get("/health"), get("/datasets")
        break
    except OSError as e:
        got = e
        time.sleep(1)
print("GET /health, GET /datasets without a key:", got, "(expected 200, 401)")
sys.exit(got != (200, 401))
PY
then
  journalctl -u adele-caddy.service -n 20 --no-pager -o cat </dev/null
  systemctl disable -q --now adele-caddy.service
  fail "HTTPS doesn't answer as expected: adele-caddy.service is stopped and disabled"
fi

step=8; echo "== 8. the root certificate, the backup of the authority"
install -o root -g root -m 0644 "$root" "$ETC/root.crt" || fail "copy of the root certificate"
openssl x509 -in "$ETC/root.crt" -noout -subject -enddate -fingerprint -sha256 </dev/null
b=/root/adele-caddy-ca-$(openssl x509 -in "$ETC/root.crt" -noout -fingerprint -sha256 </dev/null | cut -d= -f2 | tr -d : | cut -c1-12).tgz
if [ -f "$b" ]; then echo "backup there: $b"; else
  (umask 077; tar -C / -czf "$b" "${STATE#/}/pki" </dev/null) || fail "backup"
  ls -l "$b"
fi
command -v ufw >/dev/null && ufw status </dev/null | head -1
echo "== done. Next: root.crt into client/src/adele/adele-ca.pem (commit, push), port $PORT in the panel, deploy/add-key.sh"
}

# the output is kept in a file next to public ones: no name of the machine in it
main 2>&1 | sed -u -e "s/${HOST//./\\.}/<host>/g" -e "s/$(hostname)/<host>/g"
exit "${PIPESTATUS[0]}"
