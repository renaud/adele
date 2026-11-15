#!/bin/sh
# Runs once inside a plain (not privileged) container of the local image, before systemd ever starts in it.
# It disables every unit that writes to the kernel or to devices, and the units that the test does not need.
set -e
mask() { for u in "$@"; do ln -sfn /dev/null "/etc/systemd/system/$u"; done; }
# the two that changed Docker's VM on 2026-11-14, and their triggers
mask systemd-binfmt.service proc-sys-fs-binfmt_misc.automount proc-sys-fs-binfmt_misc.mount systemd-sysctl.service procps.service
# kernel modules, devices, clock, security profiles, disks, swap, consoles
mask systemd-modules-load.service kmod-static-nodes.service systemd-udevd.service systemd-udevd-control.socket \
     systemd-udevd-kernel.socket systemd-udev-trigger.service systemd-udev-settle.service systemd-timesyncd.service \
     apparmor.service fstrim.timer fstrim.service swap.target systemd-remount-fs.service systemd-random-seed.service \
     systemd-vconsole-setup.service systemd-pstore.service systemd-repart.service systemd-firstboot.service \
     systemd-pcrmachine.service systemd-pcrphase.service systemd-pcrphase-sysinit.service systemd-pcrextend.socket \
     systemd-tpm2-setup.service systemd-tpm2-setup-early.service systemd-sysext.socket systemd-sysext.service \
     sys-kernel-config.mount sys-kernel-debug.mount sys-kernel-tracing.mount sys-fs-fuse-connections.mount \
     dev-hugepages.mount dev-mqueue.mount systemd-tmpfiles-setup-dev.service systemd-tmpfiles-setup-dev-early.service \
     systemd-hibernate-resume.service systemd-battery-check.service systemd-bsod.service
# not needed by the test
mask getty@.service getty-static.service console-getty.service serial-getty@.service container-getty@.service \
     systemd-logind.service apache2.service apache-htcacheclean.service e2scrub_reap.service e2scrub_all.timer \
     apt-daily.timer apt-daily-upgrade.timer dpkg-db-backup.timer motd-news.timer phpsessionclean.timer \
     systemd-ask-password-console.path systemd-ask-password-wall.path systemd-machine-id-commit.service \
     systemd-update-utmp.service systemd-update-utmp-runlevel.service ldconfig.service \
     systemd-journal-catalog-update.service systemd-update-done.service systemd-user-sessions.service \
     systemd-tmpfiles-clean.timer x11-common.service
rm -f /etc/systemd/system/*.wants/apache2.service /etc/systemd/system/timers.target.wants/* /etc/systemd/system/multi-user.target.wants/*
# generators that look at disks and old init scripts
for g in systemd-gpt-auto-generator systemd-fstab-generator systemd-cryptsetup-generator systemd-hibernate-resume-generator \
         systemd-veritysetup-generator systemd-integritysetup-generator systemd-sysv-generator systemd-rc-local-generator; do
    rm -f "/usr/lib/systemd/system-generators/$g" "/lib/systemd/system-generators/$g"
done
rm -f /etc/init.d/*
# no sysctl or binfmt or module configuration left, in case a unit is unmasked by mistake
rm -rf /etc/sysctl.d/* /usr/lib/sysctl.d/* /lib/sysctl.d/* /etc/binfmt.d/* /usr/lib/binfmt.d/* /lib/binfmt.d/* /etc/modules-load.d/* /usr/lib/modules-load.d/* 2>/dev/null || true
: > /etc/sysctl.conf
systemctl --root=/ set-default multi-user.target >/dev/null 2>&1 || true
echo "masked: $(find /etc/systemd/system -maxdepth 1 -lname /dev/null | wc -l) units"
echo "sysctl files left: $(ls /etc/sysctl.d /usr/lib/sysctl.d 2>/dev/null | wc -l); binfmt files left: $(ls /etc/binfmt.d /usr/lib/binfmt.d 2>/dev/null | wc -l)"
