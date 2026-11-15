#!/usr/bin/env bash
# adele: test the claims about systemd that the scheduling design rests on.
#
# STATUS: run in a container on the Mac (container-test/result-2026-11-15.txt) and on steacher1
# (result-steacher1.txt, 2026-11-15): 27 passed, 0 failed, both times. Read it before you run it.
# Each step prints what is expected if the claim holds ("EXPECTED") and what the server did
# ("GOT"), and PASS or FAIL where a program can tell.
#
# Run as root on the Linux server:   sudo bash adele-systemd-claims-test.sh 2>&1 | tee result.txt
# Duration: about 6 minutes (step 8 waits for three full minutes of the clock).
#
# WHAT NEEDS ROOT, AND WHAT THE SCRIPT TOUCHES
#   - mktemp -d /run/adelepoc.XXXXXX : the one folder that holds every file of the test.
#     /run is a memory file system: it is empty again after a reboot. (Not /tmp: PrivateTmp= hides it.)
#   - unit files in /run/systemd/system/ named adelepoc<PID>-* (runtime units: gone after a reboot),
#     and transient units of the same prefix created with systemd-run. Nothing is written to /etc.
#   - `systemctl daemon-reload`, twice (after writing the unit files, and after removing them).
#     Side effect on a server in use: systemd reads again ALL unit files, so an edit that an admin
#     made to another unit without reloading becomes active. Check `systemctl status` of your own
#     services first if you have edits pending.
#   - test commands run as the user `nobody` (User=nobody), never as root, except two lines that
#     test root on purpose (step 6: `id -u` and one `systemctl start` of a test unit).
#   - write attempts as `nobody` to /etc, /usr and /var/lib (file name adelepoc<PID>-probe). They must
#     fail. As `nobody` they fail even without any sandbox, so no file can appear there; the error
#     text tells which of the two refused ("Read-only file system" = the sandbox).
#   - step 5b (only with POLKIT=1): one rule file in /run/polkit-1/rules.d, removed at the end.
#     Skipped when that folder does not exist (older polkit reads rules from /etc only).
#   - cleanup at the end, on an error and on Ctrl-C: stops the test units, removes the unit files,
#     reloads systemd, removes the folder. To clean by hand after a kill -9 of the script:
#       systemctl stop 'adelepoc*'; rm -f /run/systemd/system/adelepoc*; rm -rf /run/adelepoc.*
#       rm -f /run/polkit-1/rules.d/adelepoc*; systemctl daemon-reload; systemctl reset-failed 'adelepoc*'
#
# The six settings under test are those of deploy/adele-fetch.service:
#   NoNewPrivileges, PrivateTmp, ProtectSystem=strict, ProtectHome, ReadOnlyPaths, ReadWritePaths.

set -u
[ "$(id -u)" = 0 ] || { echo "run as root (see the header for what root is used for)"; exit 1; }
command -v systemd-run >/dev/null || { echo "systemd-run not found"; exit 1; }
[ -d /run/systemd/system ] || { echo "systemd is not the init system here"; exit 1; }

P="adelepoc$$"                       # prefix of every unit of this run
W="$(mktemp -d /run/adelepoc.XXXXXX)" # the one folder of this run
U=/run/systemd/system
POLKIT_FILE=""
NOBODY_UID="$(id -u nobody)" || { echo "no user nobody"; exit 1; }
pass=0; fail=0

cleanup() {
    trap - EXIT INT TERM
    echo; echo "== cleanup"
    systemctl stop "${P}-*" 2>/dev/null
    rm -f "$U/${P}"-*
    [ -n "$POLKIT_FILE" ] && rm -f "$POLKIT_FILE"
    systemctl daemon-reload
    systemctl reset-failed "${P}-*" 2>/dev/null
    rm -rf "$W"
    echo "units left with the prefix: $(systemctl list-units --all --no-legend "${P}-*" 2>/dev/null | wc -l) (expected 0)"
    echo "passed $pass, failed $fail"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

step()   { echo; echo "== $*"; }
expect() { echo "EXPECTED: $*"; }
got()    { echo "GOT:      $*"; }
check()  { if [ "$1" = "$2" ]; then echo "PASS"; pass=$((pass+1)); else echo "FAIL (wanted '$2', got '$1')"; fail=$((fail+1)); fi; }
lines()  { if [ -f "$1" ]; then wc -l < "$1" | tr -d ' '; else echo 0; fi; }

chmod 755 "$W"
mkdir "$W/rw" "$W/ro"
chown nobody "$W/rw" "$W/ro"          # both writable by nobody: only the sandbox can make ro read-only
SIX=(-p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectSystem=strict -p ProtectHome=yes
     -p "ReadOnlyPaths=$W/ro" -p "ReadWritePaths=$W/rw")

echo "systemd: $(systemctl --version | head -1)"
echo "kernel:  $(uname -r)    folder: $W    unit prefix: $P"

# ---------------------------------------------------------------------------------------------
# helper scripts (run with /bin/sh <file>, so that no % or quote has to survive a unit file)
cat > "$W/probe.sh" <<EOF
# usage: probe.sh <label>     runs as nobody inside a unit; writes $W/rw/probe-<label>.txt
try() { if ( : > "\$1" ) 2>/dev/null; then echo "write \$1: written"; else echo "write \$1: \$( ( : > "\$1" ) 2>&1 | sed 's/.*: //')"; fi; }
{
    echo "uid=\$(id -u) session=\$(ps -o sid= -p \$\$ | tr -d ' ') pid=\$\$"
    grep NoNewPrivs /proc/self/status | tr '\t' ' '
    try /etc/${P}-probe
    try /usr/${P}-probe
    try /var/lib/${P}-probe
    try $W/ro/x
    try $W/rw/ok-\$1
    echo "mode of /home: \$(stat -c %a /home 2>&1)"
    echo "entries in /tmp at start: \$(ls -A /tmp | wc -l | tr -d ' ')"
    : > /tmp/${P}-inside && echo "write /tmp/${P}-inside: written"
} > $W/rw/probe-\$1.txt 2>&1
EOF
cat > "$W/once.sh" <<EOF
date +%s >> $W/once.log
sleep \${1:-20}
EOF
cat > "$W/inst.sh" <<EOF
echo "\$1 start uid=\$(id -u)" >> $W/rw/inst.log
sleep 15
echo "\$1 end" >> $W/rw/inst.log
EOF
cat > "$W/acc.sh" <<EOF
date +%S.%N | cut -c1-6 >> $W/acc-\$1.log
EOF
cat > "$W/env.sh" <<EOF
{
    if [ "\${ADELEPOC_SECRET:-}" = s3cret ]; then echo "variable seen: yes"; else echo "variable seen: no"; fi
    if cat $W/secret.env >/dev/null 2>&1; then echo "file readable: yes"; else echo "file readable: no"; fi
} > $W/rw/env.txt
EOF

# unit files (runtime: /run/systemd/system)
cat > "$U/${P}-once.service" <<EOF
[Unit]
Description=adele test: a oneshot unit that runs for 20 s
[Service]
Type=oneshot
ExecStart=/bin/sh $W/once.sh 20
EOF
cat > "$U/${P}-tick.service" <<EOF
[Unit]
Description=adele test: a oneshot unit that runs for 12 s, started by a timer every 5 s
[Service]
Type=oneshot
ExecStart=/bin/sh $W/once.sh 12
EOF
cat > "$U/${P}-tick.timer" <<EOF
[Unit]
Description=adele test: every 5 seconds
[Timer]
OnCalendar=*:*:0/5
AccuracySec=1s
EOF
cat > "$U/${P}-fetch@.service" <<EOF
[Unit]
Description=adele test: template unit, one instance per dataset (%i)
[Service]
Type=oneshot
User=nobody
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=$W/ro
ReadWritePaths=$W/rw
ExecStart=/bin/sh $W/inst.sh %i
EOF
cat > "$U/${P}-plus.service" <<EOF
[Unit]
Description=adele test: one line as nobody in the sandbox, one line with the + prefix
[Service]
Type=oneshot
User=nobody
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=$W/rw
ExecStart=/bin/sh -c 'echo "plain line: uid=\$\$(id -u)" > $W/rw/plus.txt'
ExecStart=+/bin/sh -c 'echo "plus line: uid=\$\$(id -u)" >> $W/rw/plus.txt; systemctl start --no-block ${P}-fetch@fromtick.service'
EOF
cat > "$U/${P}-sched.service" <<EOF
[Unit]
Description=adele test: a service that stays running, with a child in its own session
[Service]
Type=simple
User=nobody
ExecStart=/bin/sh -c 'setsid sleep 61234 & exec sleep 61235'
EOF
cat > "$U/${P}-mixed.service" <<EOF
[Unit]
Description=adele test: the same with KillMode=mixed and 8 s to stop
[Service]
Type=simple
User=nobody
KillMode=mixed
TimeoutStopSec=8
ExecStart=/bin/sh -c 'setsid sleep 61236 & exec sleep 61237'
EOF
systemctl daemon-reload

# ---------------------------------------------------------------------------------------------
step "1. The six settings hold for the process of the unit, for its child and for a grandchild in a new session (R1; candidates C and A2)"
echo "   Claim: every process that a unit starts inherits the limits. ingest.py starts fetch.py with"
echo "   start_new_session=True, so the grandchild below is started with setsid."
echo "   The unit is transient (systemd-run -p ...): this is also the test of candidate A2."
systemd-run --quiet --wait --collect --unit="${P}-six" --uid=nobody "${SIX[@]}" \
    /bin/sh -c "/bin/sh $W/probe.sh child; setsid -w /bin/sh $W/probe.sh grandchild"
echo "rc of systemd-run: $? (expected 0)"
for who in child grandchild; do
    f="$W/rw/probe-$who.txt"
    echo "--- $who"; cat "$f" 2>/dev/null || echo "(no output file: the unit could not write to ReadWritePaths)"
    expect "NoNewPrivs: 1"
    check "$(grep -c 'NoNewPrivs: 1' "$f" 2>/dev/null)" 1
    expect "three lines 'write /etc|/usr|/var/lib ...: Read-only file system' (ProtectSystem=strict; 'Permission denied' would mean: no sandbox)"
    check "$(grep -c -E '^write /(etc|usr|var/lib)/.*Read-only file system' "$f" 2>/dev/null)" 3
    expect "write $W/ro/x: Read-only file system (ReadOnlyPaths; the folder belongs to nobody)"
    check "$(grep -c "^write $W/ro/x: Read-only file system" "$f" 2>/dev/null)" 1
    expect "write $W/rw/ok-$who: written (ReadWritePaths)"
    check "$(grep -c "^write $W/rw/ok-$who: written" "$f" 2>/dev/null)" 1
    expect "mode of /home: 0 (ProtectHome=yes replaces /home by an empty folder without access)"
    check "$(grep -c '^mode of /home: 0$' "$f" 2>/dev/null)" 1
    expect "entries in /tmp at start: 0 for the child, 1 for the grandchild (the child's file): a /tmp of the unit, shared by its processes"
    got "$(grep '^entries in /tmp' "$f" 2>/dev/null)"
done
expect "the grandchild has another session than the child, and uid $NOBODY_UID"
got "$(head -1 "$W/rw/probe-child.txt" 2>/dev/null) | $(head -1 "$W/rw/probe-grandchild.txt" 2>/dev/null)"
expect "/tmp/${P}-inside does not exist on the host (PrivateTmp; systemd removed the unit's /tmp when it stopped)"
check "$([ -e "/tmp/${P}-inside" ] && echo exists || echo absent)" absent
check "$([ -e "$W/ro/x" ] && echo exists || echo absent)" absent

# ---------------------------------------------------------------------------------------------
step "2. A oneshot unit that is still running is not started a second time (claim behind L, B and D)"
systemctl start --no-block "${P}-once.service"; sleep 3
expect "state while it runs: activating (a oneshot unit is never 'active')"
got "$(systemctl is-active "${P}-once.service")"
systemctl start --no-block "${P}-once.service"; echo "rc of the second start: $? (expected 0: accepted, joined with the run in progress)"
sleep 2
expect "1 run so far"
check "$(lines "$W/once.log")" 1
t=$(date +%s); systemctl start "${P}-once.service"; t=$(( $(date +%s) - t ))
expect "a blocking start waits for the run in progress (about 15 s) and starts no new run: still 1"
got "waited $t s"
check "$(lines "$W/once.log")" 1
systemctl start --no-block "${P}-once.service"; sleep 2
expect "after the end, a start runs the unit again: 2 runs"
check "$(lines "$W/once.log")" 2
systemctl stop "${P}-once.service"; rm -f "$W/once.log"

step "3. A timer that elapses while its unit runs drops that tick (timer every 5 s, run of 12 s, watched for 36 s)"
systemctl start "${P}-tick.timer"; sleep 36; systemctl stop "${P}-tick.timer" "${P}-tick.service"
n=$(lines "$W/once.log")
expect "3 runs (at most 4), not 7; no two starts closer than 12 s; the journal of the timer has no line for a dropped tick"
got "$n runs, start times (s): $(tr '\n' ' ' < "$W/once.log" 2>/dev/null)"
check "$([ "$n" -ge 2 ] && [ "$n" -le 4 ] && echo ok || echo wrong)" ok
journalctl -u "${P}-tick.timer" -u "${P}-tick.service" --no-pager -o short-precise 2>/dev/null | tail -12
rm -f "$W/once.log"

# ---------------------------------------------------------------------------------------------
step "4. Template unit: one instance per dataset, side by side; a running instance is not started twice (B and D; R2, R3, R6)"
systemctl start --no-block "${P}-fetch@aaa.service" "${P}-fetch@bbb.service"; sleep 3
systemctl start --no-block "${P}-fetch@aaa.service"; sleep 2
expect "2 lines: 'aaa start uid=$NOBODY_UID' and 'bbb start uid=$NOBODY_UID' (both run at once; no second aaa)"
cat "$W/rw/inst.log" 2>/dev/null
check "$(grep -c start "$W/rw/inst.log" 2>/dev/null)" 2
expect "two units listed as activating"
systemctl list-units --no-legend --no-pager "${P}-fetch@*"
expect "the journal of one instance holds only its own lines (what a person reads per dataset)"
journalctl -u "${P}-fetch@aaa.service" --no-pager -o short-precise 2>/dev/null | tail -4

step "5. A user who is not root may not start a unit (D: what right does the tick need?)"
out="$(runuser -u nobody -- systemctl --no-ask-password start --no-block "${P}-fetch@denied.service" 2>&1)"; rc=$?
expect "refused, rc not 0, a message such as 'Interactive authentication required' or 'Access denied'; no line 'denied start' in inst.log"
got "rc=$rc $out"
check "$([ $rc -ne 0 ] && echo refused || echo allowed)" refused
check "$(grep -c '^denied start' "$W/rw/inst.log" 2>/dev/null)" 0

if [ "${POLKIT:-0}" = 1 ]; then
    step "5b. (POLKIT=1) a polkit rule that lets nobody start the instances of this template, and nothing else"
    if [ -d /run/polkit-1/rules.d ] && command -v pkaction >/dev/null; then
        POLKIT_FILE="/run/polkit-1/rules.d/${P}.rules"
        cat > "$POLKIT_FILE" <<EOF
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" && subject.user == "nobody" &&
        action.lookup("verb") == "start" && /^${P}-fetch@[a-z0-9_]+\\.service\$/.test(action.lookup("unit"))) {
        return polkit.Result.YES;
    }
});
EOF
        sleep 2
        echo "polkit: $(pkaction --version)"
        runuser -u nobody -- systemctl --no-ask-password start --no-block "${P}-fetch@viapolkit.service"; rc1=$?
        runuser -u nobody -- systemctl --no-ask-password start --no-block "${P}-once.service" 2>/dev/null; rc2=$?
        runuser -u nobody -- systemctl --no-ask-password stop "${P}-fetch@viapolkit.service" 2>/dev/null; rc3=$?
        sleep 2
        expect "start of an instance: rc 0 and a line 'viapolkit start'; start of another unit: refused; stop of the instance: refused"
        got "rc=$rc1 / rc=$rc2 / rc=$rc3; $(grep -c '^viapolkit start' "$W/rw/inst.log") line(s)"
        check "$([ $rc1 -eq 0 ] && [ $rc2 -ne 0 ] && [ $rc3 -ne 0 ] && echo ok || echo wrong)" ok
        rm -f "$POLKIT_FILE"; POLKIT_FILE=""
    else
        echo "skipped: /run/polkit-1/rules.d or pkaction is missing. polkit: $(pkaction --version 2>&1 | head -1)"
        echo "(polkit 0.105 and older read .pkla files, which cannot test the unit name: the rule would then cover every unit)"
    fi
fi

# ---------------------------------------------------------------------------------------------
step "6. In a unit of User=nobody, a line with the + prefix runs as root and may start an instance (D without polkit)"
systemctl start "${P}-plus.service"; echo "rc: $? (expected 0)"; sleep 2
expect "'plain line: uid=$NOBODY_UID' then 'plus line: uid=0', and a line 'fromtick start' in inst.log"
cat "$W/rw/plus.txt" 2>/dev/null
check "$(grep -c "plain line: uid=$NOBODY_UID" "$W/rw/plus.txt" 2>/dev/null)" 1
check "$(grep -c 'plus line: uid=0' "$W/rw/plus.txt" 2>/dev/null)" 1
check "$(grep -c '^fromtick start' "$W/rw/inst.log" 2>/dev/null)" 1

# ---------------------------------------------------------------------------------------------
step "7. A service that stays running (candidate C): what a restart, a crash and a stop do to a child in its own session"
systemctl start "${P}-sched.service"; sleep 1
child="$(pgrep -f 'sleep 61234' | head -1)"
got "main pid $(systemctl show -p MainPID --value "${P}-sched.service"), child pid ${child:-none} (in its own session)"
systemctl restart "${P}-sched.service"; sleep 1
expect "restart: the old child is gone (KillMode=control-group, the default: every process of the unit is stopped)"
check "$(kill -0 "${child:-1}" 2>/dev/null && echo alive || echo gone)" gone
child="$(pgrep -f 'sleep 61234' | head -1)"
mainpid="$(systemctl show -p MainPID --value "${P}-sched.service")"
# Never `kill 0` or `kill 1`: a MainPID of 0 means that the unit is not running.
if [ "${mainpid:-0}" -gt 1 ] 2>/dev/null; then kill -KILL "$mainpid"; else echo "no main pid (the unit is not running): crash test skipped"; fi
sleep 2
expect "crash of the main process (kill -9): the child is stopped too, the unit is 'failed'"
check "$(kill -0 "${child:-1}" 2>/dev/null && echo alive || echo gone)" gone
got "state: $(systemctl is-active "${P}-sched.service")"
systemctl start "${P}-mixed.service"; sleep 1
child="$(pgrep -f 'sleep 61236' | head -1)"
t=$(date +%s); systemctl stop "${P}-mixed.service"; t=$(( $(date +%s) - t ))
expect "KillMode=mixed: stop sends SIGTERM to the main process only, waits TimeoutStopSec (8 s) for the child, then kills it: about 8 s, child gone"
got "stop took $t s; child $(kill -0 "${child:-1}" 2>/dev/null && echo alive || echo gone)"
echo "   Meaning for C: a restart of the scheduler either stops every fetch in progress (default), or waits for"
echo "   the longest fetch while no new fetch starts (mixed with a long TimeoutStopSec)."

# ---------------------------------------------------------------------------------------------
step "8. A timer every minute: with AccuracySec=1s it fires in the first second; with the default (1 min) anywhere in the minute"
systemd-run --quiet --unit="${P}-acc1" --on-calendar='*:*:00' --timer-property=AccuracySec=1s /bin/sh "$W/acc.sh" 1s
systemd-run --quiet --unit="${P}-acc60" --on-calendar='*:*:00' /bin/sh "$W/acc.sh" default
echo "waiting for three full minutes ..."
sleep $(( 60 - $(date +%-S) + 125 ))
systemctl stop "${P}-acc1.timer" "${P}-acc60.timer" 2>/dev/null
expect "AccuracySec=1s: 3 lines, each between 00.00 and 01.00 (second.fraction at the start of the command)"
got "$(tr '\n' ' ' < "$W/acc-1s.log" 2>/dev/null)"
expect "default accuracy: 3 lines (2 if the first minute was missed) with the same second each time, anywhere between 00 and 59"
got "$(tr '\n' ' ' < "$W/acc-default.log" 2>/dev/null)"

# ---------------------------------------------------------------------------------------------
step "9. A file of secrets that only root can read reaches a unit of User=nobody (one file per dataset: B and D)"
printf 'ADELEPOC_SECRET=s3cret\n' > "$W/secret.env"; chmod 600 "$W/secret.env"
systemd-run --quiet --wait --collect --unit="${P}-env" --uid=nobody "${SIX[@]}" -p "EnvironmentFile=$W/secret.env" /bin/sh "$W/env.sh"
expect "variable seen: yes / file readable: no"
cat "$W/rw/env.txt" 2>/dev/null
check "$(grep -c 'variable seen: yes' "$W/rw/env.txt" 2>/dev/null)" 1
check "$(grep -c 'file readable: no' "$W/rw/env.txt" 2>/dev/null)" 1

step "10. A time limit of systemd on a oneshot unit, as a second layer under fetch_timeout_s"
t=$(date +%s)
systemd-run --quiet --wait --collect --unit="${P}-limit" -p Type=oneshot -p TimeoutStartSec=5 /bin/sleep 61238; rc=$?
t=$(( $(date +%s) - t ))
expect "back after about 5 s with rc not 0 (result 'timeout'); the sleep is gone"
got "rc=$rc after $t s; the sleep is still running: $(pgrep -f 'sleep 61238' >/dev/null && echo yes || echo no)"
check "$([ $rc -ne 0 ] && [ $t -lt 30 ] && echo ok || echo wrong)" ok

echo
echo "NOT TESTED by this script: Persistent=true after a reboot, a step of the clock, behaviour at shutdown."
