#!/usr/bin/env bash
# WP1, step 4 (docs/work-packages/WP1-server-on-steacher1.md): install adele on steacher1, as
# deploy/README.md says. Starts adele-server.service (on 127.0.0.1:8000 only). Enables no fetch
# timer and fetches nothing: that is step 5. Prints no secret (not the API key, not the token).
#
# Run from the repository root on the Mac, in this order:
#   1. the ENTSO-E token, from .env on the Mac, never printed (env.d must exist: root, 0700;
#      tee creates the file 0644 inside it, and this script sets 0600):
#      grep ^ENTSO_TOKEN= .env |
#        ssh s 'sudo tee /etc/adele/env.d/entsoe_day_ahead_prices >/dev/null'
#   2. this script:
#      ssh s 'sudo bash -s' < deploy/wp1-step4-install.sh 2>&1 | tee deploy/wp1-step4-result.txt
# Running it again changes nothing that is already right; it keeps an existing config file
# (and so the API key).
set -euo pipefail
# bash reads this script from stdin (bash -s): a program that reads stdin would swallow the rest
# of the script, so the external programs below get </dev/null.

REPO=https://github.com/renaud/adele.git
NEEDED_COMMIT=f1766c9          # the unit fixes of step 2
UV_VERSION=0.9.8               # the version on the Mac
GCLOUD_SRC=/home/ubuntu/.config/gcloud/application_default_credentials.json
DATASETS="entsoe_day_ahead_prices weathernext3"
BIN=/opt/adele/server/.venv/bin/adele-server
CONF=/etc/adele/adele-server.toml
export UV_PYTHON_INSTALL_DIR=/opt/uv-python   # not under /root: ProtectHome=yes hides it from the units

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ -f "$GCLOUD_SRC" ] || { echo "missing: $GCLOUD_SRC"; exit 1; }

echo "== 1. users"
id adele >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin adele
id adele-query >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent \
  --shell /usr/sbin/nologin -G adele adele-query
id adele; id adele-query

echo "== 2. folders"
install -d -o adele -g adele -m 2750 /var/lib/adele
install -d -o adele -g adele -m 2770 /var/log/adele
install -d -o root -g adele -m 0750 /etc/adele
install -d -o root -g root -m 0700 /etc/adele/env.d
ls -ld /var/lib/adele /var/log/adele /etc/adele /etc/adele/env.d

echo "== 3. uv $UV_VERSION in /usr/local/bin"
if /usr/local/bin/uv --version 2>/dev/null | grep -q "^uv $UV_VERSION "; then
  echo "already there"
else
  tmp=$(mktemp -d)
  f=uv-x86_64-unknown-linux-gnu.tar.gz
  base=https://github.com/astral-sh/uv/releases/download/$UV_VERSION
  curl -fsSL -o "$tmp/$f" "$base/$f"
  curl -fsSL -o "$tmp/$f.sha256" "$base/$f.sha256"
  (cd "$tmp" && sha256sum -c "$f.sha256")
  tar -xzf "$tmp/$f" -C "$tmp"
  install -o root -g root -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" \
    "$tmp/uv-x86_64-unknown-linux-gnu/uvx" /usr/local/bin/
  rm -rf "$tmp"
fi
/usr/local/bin/uv --version

echo "== 4. Python 3.13 in $UV_PYTHON_INSTALL_DIR"
/usr/local/bin/uv python install 3.13 </dev/null
/usr/local/bin/uv python find 3.13 </dev/null

echo "== 5. the code in /opt/adele"
if [ -d /opt/adele/.git ]; then
  git -C /opt/adele pull --ff-only </dev/null
else
  git clone "$REPO" /opt/adele </dev/null
fi
git -C /opt/adele log -1 --format='%h %ad %s' --date=short
git -C /opt/adele merge-base --is-ancestor "$NEEDED_COMMIT" HEAD \
  || { echo "commit $NEEDED_COMMIT is missing: push it first"; exit 1; }
(cd /opt/adele/server && /usr/local/bin/uv sync --no-dev --locked </dev/null)
ls -l /opt/adele/server/.venv/bin/python

echo "== 6. config (kept if it exists: it holds the API key)"
if [ -f "$CONF" ]; then
  echo "kept: $CONF"
else
  key=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
  umask 077
  cat > "$CONF" <<EOF
# adele on steacher1 (WP1). Written by deploy/wp1-step4-install.sh.
datasets_dirs = ["/opt/adele/datasets"]
data_dir = "/var/lib/adele"
log_dir = "/var/log/adele"
fetch_timeout_s = 1800

[keys]
renaud = "$key"
EOF
  unset key
  umask 022
  echo "written: $CONF"
fi
chown root:adele "$CONF"; chmod 0640 "$CONF"
ls -l "$CONF"

echo "== 7. secrets per dataset"
install -o root -g adele -m 0640 "$GCLOUD_SRC" /etc/adele/gcloud-adc.json
(umask 077; echo "GOOGLE_APPLICATION_CREDENTIALS=/etc/adele/gcloud-adc.json" > /etc/adele/env.d/weathernext3)
chown root:root /etc/adele/env.d/*; chmod 0600 /etc/adele/env.d/*
ls -l /etc/adele/gcloud-adc.json /etc/adele/env.d/
e=/etc/adele/env.d/entsoe_day_ahead_prices
if [ -f "$e" ] && grep -q '^ENTSO_TOKEN=.' "$e"; then
  echo "ENTSO_TOKEN: present in $e ($(wc -l < "$e") line)"
else
  echo "ENTSO_TOKEN: MISSING in $e (run command 1 of the header, then this script again)"
fi

echo "== 8. units"
install -o root -g root -m 0644 /opt/adele/deploy/adele-server.service \
  /opt/adele/deploy/adele-fetch@.service /opt/adele/deploy/adele-fetch@.timer /etc/systemd/system/
systemctl daemon-reload
v=$(mktemp -d)   # systemd-analyze verify needs instance names to resolve %i
for id in $DATASETS; do
  cp /etc/systemd/system/adele-fetch@.service "$v/adele-fetch@$id.service"
  cp /etc/systemd/system/adele-fetch@.timer "$v/adele-fetch@$id.timer"
done
rc=0; systemd-analyze verify /etc/systemd/system/adele-server.service "$v"/* || rc=$?
echo "systemd-analyze verify: rc=$rc (expected 0, no lines above)"
rm -rf "$v"

echo "== 9. validate, as the user adele"
(cd /tmp && sudo -u adele "$BIN" --config "$CONF" validate </dev/null)

echo "== 10. start adele-server.service"
systemctl enable adele-server.service
systemctl restart adele-server.service
ok=no
for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health; then ok=yes; echo; break; fi
  sleep 1
done
echo "health: $ok (expected yes)"
systemctl --no-pager --lines=0 status adele-server.service | head -5 || true

echo "== 11. what the query process sees of the credentials (InaccessiblePaths)"
pid=$(systemctl show -p MainPID --value adele-server.service)
echo "expected: mode 0 for both, size 0 for the file"
nsenter -t "$pid" -m stat -c '%n mode=%a size=%s' /etc/adele/env.d /etc/adele/gcloud-adc.json || true
echo "for comparison, outside the unit:"
stat -c '%n mode=%a size=%s' /etc/adele/env.d /etc/adele/gcloud-adc.json

echo "== 12. timers (expected: none enabled yet, step 5)"
systemctl list-timers --all --no-pager 'adele-fetch@*' || true
echo "== done"
