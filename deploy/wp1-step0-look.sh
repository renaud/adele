#!/usr/bin/env bash
# WP1, step 0 (docs/work-packages/WP1-server.md): look at the server, change nothing.
# No sudo. Prints no secret: only the names of the files that mention ENTSO, and the listing
# (not the content) of the Google credentials file.
# Run from the repository root on the Mac:   ssh s 'bash -s' < deploy/wp1-step0-look.sh
echo "== id"; id
echo "== sudo without a password"; if sudo -n true 2>/dev/null; then echo yes; else echo no; fi
echo "== os"; . /etc/os-release; echo "$PRETTY_NAME"; uname -r
echo "== systemd"; systemctl --version | head -1
echo "== clock"; timedatectl 2>/dev/null | grep -E 'Time zone|synchronized|NTP'
echo "== resources"; nproc; free -h | head -2; df -h / /opt /var 2>/dev/null | sort -u
echo "== listening TCP"; ss -tln | awk 'NR>1{print $4}' | sort -u
echo "== web servers and containers"
ps -eo user,comm,args | grep -E 'caddy|nginx|apache|httpd|traefik|docker-proxy|containerd' | grep -v grep | cut -c1-150
echo "== running services"
systemctl list-units --type=service --state=running --no-legend | awk '{print $1}' \
  | grep -v -E '^(systemd-|dbus|getty|serial-getty|user@)'
echo "== tools"
for t in git uv python3 caddy docker gcloud; do
  printf '%s: ' "$t"
  if command -v "$t" >/dev/null; then "$t" --version 2>&1 | head -1; else echo missing; fi
done
echo "== google ADC file"; ls -l ~/.config/gcloud/application_default_credentials.json 2>&1
echo "== files that name ENTSO (names only)"
grep -rIl --exclude-dir={.cache,.git,node_modules,.venv} -e ENTSO ~ /opt /srv /etc/environment 2>/dev/null | head -20
echo "== adele traces"; ls -d /opt/adele /etc/adele /var/lib/adele 2>&1
getent passwd adele adele-query || echo "no adele users"
echo "== home"; ls ~
