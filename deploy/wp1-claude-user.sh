#!/usr/bin/env bash
# WP1 (docs/work-packages/WP1-server.md): a user `claude` on the server for Claude
# Code. It logs in with its own SSH key, has no sudo and is not in the group docker (which
# amounts to root). It is in systemd-journal, so it can read the journal of every unit.
#
# Run from the repository root on the Mac, after copying the public key to the server:
#   scp ~/.ssh/<claude's key>.pub s:claude.pub     (the key's name: SERVER.md)
#   ssh s 'sudo bash -s' < deploy/wp1-claude-user.sh
# Running it again changes nothing that is already right.
set -euo pipefail
PUB=$(getent passwd "${SUDO_USER:?run it with sudo}" | cut -d: -f6)/claude.pub   # the admin's home
case "$(head -c 12 "$PUB")" in
  "ssh-ed25519 ") ;;
  *) echo "$PUB does not hold an ed25519 public key"; exit 1 ;;
esac

id claude >/dev/null 2>&1 || useradd --create-home --shell /bin/bash \
  --comment "Claude Code, checks for adele (no sudo)" claude
usermod -aG systemd-journal claude
install -d -o claude -g claude -m 700 /home/claude/.ssh
install -o claude -g claude -m 600 "$PUB" /home/claude/.ssh/authorized_keys
rm -f "$PUB"

echo "== user";   id claude
echo "== sudo";   sudo -l -U claude | tail -1
echo "== sshd settings that could refuse the login"
sshd -T 2>/dev/null | grep -E '^(usepam|pubkeyauthentication|allowusers|allowgroups|denyusers|denygroups) ' \
  || echo "(none set besides the defaults)"
