#!/usr/bin/env bash
# A new API key (D35): makes it on the server, adds it to [keys] of the config, restarts the query
# server and checks that the key works. The key is never printed. Run as root from the Mac:
#   ssh s 'sudo bash -s -- <name>' < deploy/add-key.sh
# <name>: letters, digits, _ and -; queries.jsonl shows it with each query. Then the key into the
# clipboard (not into a file):
#   ssh s "sudo grep '^<name> = ' /etc/adele/adele-server.toml" | cut -d'"' -f2 | tr -d '\n' | pbcopy
# With a second argument, a user of the server also gets the key as a header file that only that user
# can read (~/.adele-auth), for: curl -H @$HOME/.adele-auth http://127.0.0.1:8000/health
#   ssh s 'sudo bash -s -- claude claude' < deploy/add-key.sh
# Revoke a key: ssh s "sudo sed -i '/^<name> = /d' /etc/adele/adele-server.toml && sudo systemctl restart adele-server"
set -uo pipefail

NAME=${1:-}
FOR=${2:-}
CONF=/etc/adele/adele-server.toml
PY=/opt/adele/server/.venv/bin/python

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[[ $NAME =~ ^[A-Za-z0-9_-]+$ ]] || { echo "usage: bash -s -- <name> (letters, digits, _ and -)"; exit 1; }
fail() { echo "FAILED: $*"; exit 1; }
home=
if [ -n "$FOR" ]; then
  [[ $FOR =~ ^[a-z_][a-z0-9_-]*$ ]] && home=$(getent passwd "$FOR" </dev/null | cut -d: -f6)
  [ -n "$home" ] && [ -d "$home" ] || fail "no user $FOR with a home folder"
fi
# the check at the end needs a server that asks for a key before it names the datasets (D36)
"$PY" - <<'PY' || fail "run deploy/access.sh first (the version of D36 or later); the config is unchanged"
import json, sys, urllib.request
try:
    up = json.load(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10))
except OSError as e:
    sys.exit(f"GET /health: {type(e).__name__}: {e}")
if "datasets" in up:
    sys.exit("GET /health names the datasets without a key")
PY

"$PY" - "$CONF" "$NAME" <<'PY' || fail "the config is unchanged"
import os, secrets, sys, tomllib
path, name = sys.argv[1:]
text = open(path).read()
before = tomllib.loads(text)
if name in before.get("keys", {}):
    sys.exit(f"a key named {name} exists")
lines = text.splitlines(keepends=True)
at = [i for i, line in enumerate(lines) if line.split("#")[0].strip() == "[keys]"]
if len(at) != 1:
    sys.exit("the config has no line [keys], or several")
if not lines[at[0]].endswith("\n"):
    lines[at[0]] += "\n"
lines.insert(at[0] + 1, f'{name} = "{secrets.token_urlsafe(24)}"\n')
new = "".join(lines)
after = tomllib.loads(new)
if len(after["keys"].pop(name)) != 32 or after != before:
    sys.exit("the new config would differ by more than the key")
st = os.stat(path)
tmp = path + ".new"
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    fh.write(new)
os.chown(tmp, st.st_uid, st.st_gid)
os.chmod(tmp, st.st_mode & 0o7777)
os.replace(tmp, path)
print(f"added: {name} ({len(after['keys']) + 1} keys)")
PY
systemctl restart adele-server.service || fail "restart adele-server.service"
"$PY" - "$CONF" "$NAME" <<'PY' || fail "the key is in the config, but the server doesn't accept it"
import json, sys, time, tomllib, urllib.request
path, name = sys.argv[1:]
key = tomllib.load(open(path, "rb"))["keys"][name]
# /health, not /datasets: the first list after a restart can take longer than a minute
req = urllib.request.Request("http://127.0.0.1:8000/health", headers={"Authorization": f"Bearer {key}"})
for i in range(30):
    try:
        n = len(json.load(urllib.request.urlopen(req, timeout=10))["datasets"])
        print(f"GET /health with the key: {n} datasets")
        sys.exit(0)
    except (OSError, KeyError) as e:
        err = e
        time.sleep(1)
sys.exit(f"{type(err).__name__}: {err}")
PY
if [ -n "$FOR" ]; then
  # written by the user itself, so root follows no link in a folder of somebody else
  "$PY" -c 'import sys, tomllib; print("Authorization: Bearer " + tomllib.load(open(sys.argv[1], "rb"))["keys"][sys.argv[2]])' \
    "$CONF" "$NAME" </dev/null | runuser -u "$FOR" -- sh -c 'umask 077; cat > "$1" && chmod 600 "$1"' sh "$home/.adele-auth" \
    || fail "the key works, but $home/.adele-auth was not written"
  ls -l "$home/.adele-auth"
fi
ls -l "$CONF"
