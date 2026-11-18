# The systemd claims, tested in a container (2026-11-15)

`../adele-systemd-claims-test.sh` ran once inside a Docker container on the Mac: 27 checks
passed, 0 failed (`result-2026-11-15.txt`). It tests the claims about systemd that the choice of
the fetch scheduling rests on. It did not run on the server yet.

## What ran

- Image: `trampgeek/jobeinabox` (Ubuntu 24.04, systemd 255, x86-64), the only local image that
  contains systemd. No pull, no network.
- The Mac is arm64, so the image runs under Rosetta. systemd 255 then fails to start any service:
  it starts its helper through `/proc/self/fd/N`, which Rosetta can't resolve. `spawnfix.c` is a
  shim of 20 lines, loaded into process 1 only, that replaces that path by the real one. It is
  not needed on a real server.
- Not available in this container: the journal (journald does not start), polkit (not
  installed). The steps that read the journal print "No entries".

## How to run it again

Never with `--privileged`: on 2026-11-14 a privileged container let systemd change the kernel of
Docker's VM (its `sysctl` values and the table of binary formats), and x86-64 containers failed
until Docker Desktop was restarted. The commands below give one added capability, leave
`/proc/sys` read-only, and disable every unit that writes to the kernel before the first start
(`prepare-image.sh`).

```
docker run --name adele-poc-prep --network none --platform linux/amd64 -v "$PWD":/poc:ro \
  --entrypoint /bin/sh trampgeek/jobeinabox /poc/prepare-image.sh
docker commit adele-poc-prep adele-poc-systemd:1 && docker rm adele-poc-prep
# spawnfix.so: compile spawnfix.c inside the image (gcc -shared -fPIC -o spawnfix.so spawnfix.c -ldl)
docker run -d --name adele-poc-sd --platform linux/amd64 --network none --cap-add SYS_ADMIN \
  --cgroupns private --tmpfs /run --tmpfs /run/lock --tmpfs /tmp -e container=docker \
  -v "$PWD":/poc --entrypoint /bin/sh adele-poc-systemd:1 -c \
  'mount -o remount,rw /sys/fs/cgroup; cp /poc/spawnfix.so /usr/local/lib/; LD_PRELOAD=/usr/local/lib/spawnfix.so exec /lib/systemd/systemd'
docker exec adele-poc-sd bash /poc/adele-systemd-claims-test.sh
docker rm -f adele-poc-sd && docker rmi adele-poc-systemd:1
```

Before and after, check that Docker's VM is unchanged:
`docker run --rm --platform linux/amd64 --entrypoint /bin/true trampgeek/jobeinabox` must exit
with 0.

## What it showed

| claim | result |
|---|---|
| the six sandbox settings hold for a unit, its child, and a grandchild in a new session | yes |
| a oneshot unit that is still running is not started a second time | yes (state "activating"; a second start joins the run) |
| a timer that elapses while its unit runs drops that tick | yes (3 runs in 36 s for a timer of 5 s and a run of 12 s) |
| two instances of a template unit run side by side | yes |
| a user who is not root can't start a unit | yes ("Access denied") |
| a line with the `+` prefix runs as root in a unit of another user | yes |
| a restart or a crash of a service stops its children, also in their own session | yes |
| `KillMode=mixed` waits for the children | no: the stop took 0 s and the child was gone |
| a timer every minute with `AccuracySec=1s` | fired 0.5 s after the minute, three times |
| a file of secrets that only root reads reaches the unit, and the unit can't read the file | yes |
| `TimeoutStartSec` stops a run that hangs | yes (after 5 s) |

Not tested: the journal per dataset, a polkit rule, `Persistent=true` after a reboot, a step of
the clock, the behaviour at shutdown.
