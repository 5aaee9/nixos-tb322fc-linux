#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void pause_forever(void) { for (;;) pause(); }

int main(int argc, char **argv) {
    if (argc < 2) return 90;
    if (!strcmp(argv[1], "probe")) {
        struct rlimit address, core, cpu;
        if (getrlimit(RLIMIT_AS, &address) || getrlimit(RLIMIT_CORE, &core) ||
            getrlimit(RLIMIT_CPU, &cpu)) return 91;
        printf("PROBE as=%llu core=%llu cpu=%llu\n",
               (unsigned long long)address.rlim_cur, (unsigned long long)core.rlim_cur,
               (unsigned long long)cpu.rlim_cur);
        if (address.rlim_cur != 512ULL * 1024 * 1024 || core.rlim_cur) return 92;
        errno = 0;
        void *map = mmap(NULL, 1024ULL * 1024 * 1024, PROT_NONE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (map != MAP_FAILED || errno != ENOMEM) return 93;
        puts("PROBE limit_enforced=1");
        return 0;
    }
    if (!strcmp(argv[1], "exit")) return argc == 3 ? atoi(argv[2]) : 90;
    if (!strcmp(argv[1], "abort")) abort();
    if (!strcmp(argv[1], "cpu")) { for (;;) __asm__ volatile("" ::: "memory"); }
    if (!strcmp(argv[1], "hang")) {
        signal(SIGTERM, SIG_IGN);
        pause_forever();
    }
    if (!strcmp(argv[1], "descendant")) {
        int ready[2];
        if (pipe2(ready, O_CLOEXEC)) return 94;
        pid_t child = fork();
        if (child < 0) return 94;
        if (!child) {
            close(ready[0]);
            if (setsid() < 0) return 95;
            signal(SIGTERM, SIG_IGN);
            if (write(ready[1], "R", 1) != 1) return 95;
            close(ready[1]);
            pause_forever();
        }
        close(ready[1]);
        char byte;
        ssize_t received;
        do { received = read(ready[0], &byte, 1); }
        while (received < 0 && errno == EINTR);
        close(ready[0]);
        if (received != 1 || byte != 'R') return 95;
        printf("DESCENDANT pid=%ld\n", (long)child);
        return 0;
    }
    if (!strcmp(argv[1], "floodout") || !strcmp(argv[1], "flooderr")) {
        int fd = !strcmp(argv[1], "floodout") ? 1 : 2;
        char data[4096];
        memset(data, 'X', sizeof(data));
        for (;;) {
            if (write(fd, data, sizeof(data)) < 0 && errno != EINTR) return 96;
        }
    }
    if (!strcmp(argv[1], "reserve-parent")) {
        if (argc < 4) return 90;
        struct rlimit before, after;
        if (getrlimit(RLIMIT_AS, &before)) return 97;
        size_t size = 12ULL * 1024 * 1024 * 1024;
        void *map = mmap(NULL, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (map == MAP_FAILED) return 98;
        pid_t child = fork();
        if (child < 0) return 99;
        if (!child) { execv(argv[2], &argv[2]); _exit(100); }
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) ||
            WEXITSTATUS(status)) return 101;
        if (getrlimit(RLIMIT_AS, &after) || before.rlim_cur != after.rlim_cur ||
            before.rlim_max != after.rlim_max) return 102;
        munmap(map, size);
        puts("PARENT reservation_bytes=12884901888 limits_unchanged=1");
        return 0;
    }
    return 90;
}
