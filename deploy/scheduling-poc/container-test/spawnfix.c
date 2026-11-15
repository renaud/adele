/* Only for the test container on a Mac (x86-64 image under Rosetta). systemd 255 closes the file
 * descriptor that Rosetta keeps open, then starts its helper systemd-executor through
 * /proc/self/fd/N, which Rosetta can no longer resolve (exit 255). This shim replaces that path by
 * the real path of the same file. It changes nothing else in systemd. Not needed on a real server. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <spawn.h>
#include <string.h>
#include <unistd.h>

int posix_spawn(pid_t *pid, const char *path, const posix_spawn_file_actions_t *fa,
                const posix_spawnattr_t *attr, char *const argv[], char *const envp[]) {
    static int (*real)(pid_t *, const char *, const posix_spawn_file_actions_t *,
                       const posix_spawnattr_t *, char *const[], char *const[]);
    char buf[PATH_MAX];
    if (!real)
        real = dlsym(RTLD_NEXT, "posix_spawn");
    if (path && strncmp(path, "/proc/self/fd/", 14) == 0) {
        ssize_t n = readlink(path, buf, sizeof buf - 1);
        if (n > 0) {
            buf[n] = 0;
            path = buf;
        }
    }
    return real(pid, path, fa, attr, argv, envp);
}
