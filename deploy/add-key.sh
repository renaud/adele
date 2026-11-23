#!/usr/bin/env bash
# A new API key (D35): makes it on the server, adds it to [keys] of the config, restarts the query
# server and checks that the key works. The key is never printed. Run as root from the Mac:
#   ssh s 'sudo bash -s -- <name>' < deploy/add-key.sh
# <name>: letters, digits, _ and -; queries.jsonl shows it with each query. Then the key into the
# clipboard (not into a file):
#   ssh s "sudo grep '^<name> = ' /etc/adele/adele-server.toml" | cut -d'"' -f2 | tr -d '\n' | pbcopy
# Revoke a key: ssh s "sudo sed -i '/^<name> = /d' /etc/adele/adele-server.toml && sudo systemctl restart adele-server"
set -uo pipefail

NAME=${1:-}
CONF=/etc/adele/adele-server.toml
PY=/opt/adele/server/.venv/bin/python

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[[ $NAME =~ ^[A-Za-z0-9_-]+$ ]] || { echo "usage: bash -s -- <name> (letters, digits, _ and -)"; exit 1; }
fail() { echo "FAILED: $*"; exit 1; }

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
import sys, time, tomllib, urllib.request
path, name = sys.argv[1:]
key = tomllib.load(open(path, "rb"))["keys"][name]
req = urllib.request.Request("http://127.0.0.1:8000/datasets", headers={"Authorization": f"Bearer {key}"})
for i in range(30):
    try:
        n = len(urllib.request.urlopen(req, timeout=10).read().splitlines()) - 1
        print(f"GET /datasets with the key: {n} datasets")
        sys.exit(0)
    except OSError as e:
        err = e
        time.sleep(1)
sys.exit(f"{type(err).__name__}: {err}")
PY
ls -l "$CONF"
