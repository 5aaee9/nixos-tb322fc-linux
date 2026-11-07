#define _GNU_SOURCE
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Only a static child is limited. No shell, dynamic loader or crash reporter
 * is exec'd by this supervisor. stdout belongs exclusively to the child. */
static volatile sig_atomic_t interrupted;
static int saved_stderr_flags = -1;

static void on_signal(int sig) { interrupted = sig; }

static int event(const char *format, ...) {
    char line[384];
    va_list args;
    va_start(args, format);
    int n = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (n < 0 || (size_t)n >= sizeof(line)) return -1;
    ssize_t written;
    do { written = write(STDERR_FILENO, line, (size_t)n); }
    while (written < 0 && errno == EINTR);
    return written == n ? 0 : -1;
}

static int finish(int code) {
    if (saved_stderr_flags >= 0)
        (void)fcntl(STDERR_FILENO, F_SETFL, saved_stderr_flags);
    return code;
}

static int64_t milliseconds(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return -1;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static int number(const char *s, unsigned long minimum, unsigned long maximum,
                  unsigned long *out) {
    char *end;
    errno = 0;
    if (!s[0] || s[0] < '0' || s[0] > '9') return -1;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || *end || n < minimum || n > maximum) return -1;
    *out = n;
    return 0;
}

static int static_elf(const char *path) {
    if (path[0] != '/') { errno = EINVAL; return -1; }
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    struct stat st;
    Elf64_Ehdr header;
#if defined(__aarch64__)
    const int machine = EM_AARCH64;
#elif defined(__x86_64__)
    const int machine = EM_X86_64;
#else
#error Unsupported diagnostic architecture
#endif
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) ||
        (st.st_mode & (S_ISUID | S_ISGID)) || st.st_size < 64 ||
        st.st_size > 64 * 1024 * 1024 ||
        pread(fd, &header, sizeof(header), 0) != sizeof(header) ||
        memcmp(header.e_ident, ELFMAG, SELFMAG) ||
        header.e_ident[EI_CLASS] != ELFCLASS64 ||
        header.e_ident[EI_DATA] != ELFDATA2LSB ||
        header.e_machine != machine ||
        (header.e_type != ET_EXEC && header.e_type != ET_DYN) ||
        header.e_phentsize != sizeof(Elf64_Phdr) ||
        !header.e_phnum || header.e_phnum > 128 ||
        header.e_phoff > (uint64_t)st.st_size ||
        (uint64_t)header.e_phnum * sizeof(Elf64_Phdr) >
            (uint64_t)st.st_size - header.e_phoff)
        goto invalid;
    bool load = false;
    for (unsigned i = 0; i < header.e_phnum; i++) {
        Elf64_Phdr ph;
        if (pread(fd, &ph, sizeof(ph), header.e_phoff + i * sizeof(ph)) != sizeof(ph) ||
            ph.p_type == PT_INTERP || ph.p_type == PT_DYNAMIC)
            goto invalid;
        if (ph.p_type == PT_LOAD) load = true;
    }
    if (load) return fd;
invalid:
    close(fd);
    errno = ENOEXEC;
    return -1;
}

struct child_message { int stage; int error; };

static void child_message(int fd, int stage, int error) {
    struct child_message message = {stage, error};
    if (write(fd, &message, sizeof(message)) != sizeof(message)) _exit(126);
}

static void set_limit(int fd, int kind, rlim_t soft, rlim_t hard) {
    struct rlimit value = {soft, hard};
    if (setrlimit(kind, &value)) {
        child_message(fd, -1, errno);
        _exit(126);
    }
}

/* Zombies remain children until waitpid: the ownership check prevents PID
 * reuse from turning cleanup into a signal to an unrelated process. */
struct cleanup_result { const char *operation; int error; bool fatal; };

static struct cleanup_result kill_adopted(void) {
    char path[96], data[8192];
    snprintf(path, sizeof(path), "/proc/self/task/%ld/children", (long)getpid());
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0)
        return (struct cleanup_result){"children_open", errno, false};
    ssize_t n = read(fd, data, sizeof(data) - 1);
    int read_error = errno;
    close(fd);
    if (n < 0)
        return (struct cleanup_result){"children_read", read_error, false};
    if (n == sizeof(data) - 1)
        return (struct cleanup_result){"children_read", EOVERFLOW, false};
    data[n] = 0;
    char *cursor = data;
    while (*cursor) {
        while (*cursor == ' ' || *cursor == '\n') cursor++;
        if (!*cursor) break;
        char *end;
        errno = 0;
        long pid = strtol(cursor, &end, 10);
        if (errno || end == cursor || pid <= 1 || pid > INT_MAX ||
            (*end && *end != ' ' && *end != '\n'))
            return (struct cleanup_result){"children_parse", EINVAL, false};
        cursor = end;
        siginfo_t info = {0};
        if (waitid(P_PID, (id_t)pid, &info, WEXITED | WNOHANG | WNOWAIT)) {
            if (errno == ECHILD) continue;
            return (struct cleanup_result){"children_waitid", errno, true};
        }
        if (!info.si_pid && kill((pid_t)pid, SIGKILL) && errno != ESRCH)
            return (struct cleanup_result){"children_kill", errno, true};
    }
    return (struct cleanup_result){0};
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--probe")) {
        struct rlimit address, core;
        if (getrlimit(RLIMIT_AS, &address) || getrlimit(RLIMIT_CORE, &core) ||
            address.rlim_cur != 512ULL * 1024 * 1024 || core.rlim_cur) return 93;
        errno = 0;
        void *map = mmap(NULL, 1024ULL * 1024 * 1024, PROT_NONE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (map != MAP_FAILED || errno != ENOMEM) return 94;
        puts("Y700_RUNNER_PROBE_V1 as_bytes=536870912 core_bytes=0 limit_enforced=1");
        return 0;
    }
    unsigned long wall, grace, reap, memory, cpu;
    if (argc < 8 || strcmp(argv[6], "--") ||
        number(argv[1], 50, 900000, &wall) ||
        number(argv[2], 0, 5000, &grace) ||
        number(argv[3], 100, 5000, &reap) ||
        number(argv[4], 16, 1024, &memory) ||
        number(argv[5], 1, 900, &cpu)) {
        fprintf(stderr, "usage: readonly-runner WALL_MS GRACE_MS REAP_MS AS_MIB CPU_S -- /static/helper [args]\n");
        return 125;
    }
    saved_stderr_flags = fcntl(STDERR_FILENO, F_GETFL);
    if (saved_stderr_flags < 0 ||
        fcntl(STDERR_FILENO, F_SETFL, saved_stderr_flags | O_NONBLOCK))
        return 125;
    struct sigaction action = {.sa_handler = on_signal};
    sigemptyset(&action.sa_mask);
    for (int i = 0; i < 3; i++) {
        int signals[] = {SIGTERM, SIGINT, SIGHUP};
        if (sigaction(signals[i], &action, NULL)) return finish(125);
    }
    signal(SIGPIPE, SIG_IGN);
    struct sigaction normal = {.sa_handler = SIG_DFL};
    sigemptyset(&normal.sa_mask);
    if (sigaction(SIGCHLD, &normal, NULL) || prctl(PR_SET_CHILD_SUBREAPER, 1))
        return finish(125);
    struct rlimit parent_as;
    if (getrlimit(RLIMIT_AS, &parent_as)) return finish(125);
    if (event("Y700_RUNNER_V1 event=start as_mib=%lu cpu_s=%lu wall_ms=%lu parent_as=%llu\n",
              memory, cpu, wall, (unsigned long long)parent_as.rlim_cur))
        return finish(125);
    int executable = static_elf(argv[7]);
    if (executable < 0) {
        event("Y700_RUNNER_V1 event=reject errno=%d\n", errno);
        return finish(125);
    }
    int channel[2];
    if (pipe2(channel, O_CLOEXEC | O_NONBLOCK)) {
        close(executable);
        return finish(125);
    }
    int64_t started = milliseconds();
    if (started < 0) return finish(125);
    pid_t owner = getpid();
    pid_t child = fork();
    if (child < 0) return finish(125);
    if (!child) {
        close(channel[0]);
        for (int sig = 1; sig < NSIG; sig++) {
            if (sig != SIGKILL && sig != SIGSTOP) sigaction(sig, &normal, NULL);
        }
        sigset_t empty;
        sigemptyset(&empty);
        sigprocmask(SIG_SETMASK, &empty, NULL);
        if (setpgid(0, 0) || prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != owner) {
            child_message(channel[1], -1, errno ? errno : ECHILD);
            _exit(126);
        }
        set_limit(channel[1], RLIMIT_CORE, 0, 0);
        set_limit(channel[1], RLIMIT_AS, (rlim_t)memory << 20, (rlim_t)memory << 20);
        set_limit(channel[1], RLIMIT_CPU, cpu, cpu + 1);
        int input = open("/dev/null", O_RDONLY | O_CLOEXEC);
        if (input < 0 || dup2(input, STDIN_FILENO) < 0) {
            child_message(channel[1], -1, errno);
            _exit(126);
        }
        if (input != STDIN_FILENO) close(input);
        child_message(channel[1], 1, 0);
        char *environment[] = {"LC_ALL=C", "PATH=/nonexistent", NULL};
        fexecve(executable, &argv[7], environment);
        child_message(channel[1], -2, errno);
        _exit(127);
    }
    close(executable);
    close(channel[1]);
    /* Parent and child both try before any group signal; keep the leader
     * unreaped until that group's final KILL has been issued. */
    int grouping = setpgid(child, child);
    bool group_valid = grouping == 0 || getpgid(child) == child;
    bool transport_bad = event("Y700_RUNNER_V1 event=child pid=%ld\n", (long)child) != 0;
    bool setup = false, exec_ok = false, exec_failed = false, channel_eof = false;
    bool stopping = false, killed = false, leader_seen = false, leader_reaped = false;
    bool clean = false, cleanup_error = false, descendants = false;
    struct cleanup_result last_inspection_error = {0};
    int outcome = 0, child_status = 0;
    int64_t terminate_at = 0, reap_until = 0;
    while (true) {
        int64_t now = milliseconds();
        if (now < 0) { outcome = 125; now = started + (int64_t)wall; }
        if (!channel_eof) {
            struct child_message message;
            ssize_t n;
            while ((n = read(channel[0], &message, sizeof(message))) == sizeof(message)) {
                if (message.stage == 1) {
                    setup = true;
                    if (event("Y700_RUNNER_V1 event=limits_ready\n")) transport_bad = true;
                } else {
                    exec_failed = true;
                    outcome = message.stage == -2 ? 127 : 126;
                    if (event("Y700_RUNNER_V1 event=child_error stage=%d errno=%d\n",
                              message.stage, message.error)) transport_bad = true;
                }
            }
            if (!n) {
                channel_eof = true;
                if (setup && !exec_failed) {
                    exec_ok = true;
                    if (event("Y700_RUNNER_V1 event=exec_pipe_closed\n")) transport_bad = true;
                }
            } else if (n > 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) {
                cleanup_error = true;
            }
        }
        if (!leader_seen) {
            siginfo_t info = {0};
            if (waitid(P_PID, (id_t)child, &info, WEXITED | WNOHANG | WNOWAIT)) {
                cleanup_error = true;
            } else if (info.si_pid) {
                leader_seen = true;
            }
        }
        if (leader_seen && !channel_eof && !cleanup_error) continue;
        struct pollfd disconnected = {.fd = STDERR_FILENO, .events = 0};
        if (poll(&disconnected, 1, 0) > 0 &&
            (disconnected.revents & (POLLHUP | POLLERR | POLLNVAL)))
            transport_bad = true;
        if (!stopping && (leader_seen || interrupted || now - started >= (int64_t)wall ||
                          transport_bad || cleanup_error)) {
            stopping = true;
            if (interrupted) outcome = 128 + interrupted;
            else if (transport_bad || cleanup_error) outcome = 125;
            else if (!leader_seen) outcome = 124;
            terminate_at = now + (leader_seen ? 0 : (int64_t)grace);
            if (!leader_seen) {
                if (group_valid) kill(-child, SIGTERM);
                else kill(child, SIGTERM);
                if (event("Y700_RUNNER_V1 event=term reason=%d\n", outcome))
                    transport_bad = true;
            }
        }
        if (stopping && !killed && now >= terminate_at) {
            if (group_valid) kill(-child, SIGKILL);
            else kill(child, SIGKILL);
            killed = true;
            reap_until = now + (int64_t)reap;
        }
        if (killed) {
            bool children_remain = false;
            while (true) {
                int status;
                pid_t exited = waitpid(-1, &status, WNOHANG);
                if (exited > 0) {
                    if (exited == child) {
                        leader_reaped = true;
                        child_status = status;
                    } else {
                        descendants = true;
                    }
                } else {
                    if (exited < 0 && errno == ECHILD) clean = leader_reaped;
                    else if (exited < 0 && errno != EINTR) cleanup_error = true;
                    else if (!exited) children_remain = true;
                    break;
                }
            }
            if (clean) break;
            if (now >= reap_until) {
                if (event("Y700_RUNNER_V1 event=reap_deadline leader_reaped=%d\n",
                          leader_reaped)) transport_bad = true;
                break;
            }
            /* The children proc file is optional in Android kernels. Its
             * absence is not a cleanup failure if waitpid later reaches ECHILD. */
            if (children_remain) {
                struct cleanup_result inspection = kill_adopted();
                if (inspection.error) {
                    if (inspection.fatal) cleanup_error = true;
                    if (!last_inspection_error.operation ||
                        strcmp(inspection.operation, last_inspection_error.operation) ||
                        inspection.error != last_inspection_error.error) {
                        if (event("Y700_RUNNER_V1 event=cleanup_error operation=%s errno=%d fatal=%d\n",
                                  inspection.operation, inspection.error, inspection.fatal))
                            transport_bad = true;
                        last_inspection_error = inspection;
                    }
                }
            }
        }
        struct pollfd pause = {.fd = channel_eof ? -1 : channel[0], .events = POLLIN};
        (void)poll(&pause, 1, 10);
    }
    close(channel[0]);
    if (!outcome) {
        if (!exec_ok || exec_failed || descendants) outcome = 125;
        else if (WIFEXITED(child_status)) outcome = WEXITSTATUS(child_status);
        else if (WIFSIGNALED(child_status)) outcome = 128 + WTERMSIG(child_status);
        else outcome = 125;
    }
    if (!clean || cleanup_error || transport_bad) outcome = 125;
    if (event("Y700_RUNNER_V1 event=done result=%d clean=%d child_status=%d descendants=%d\n",
              outcome, clean && !cleanup_error, child_status, descendants))
        outcome = 125;
    return finish(outcome);
}
