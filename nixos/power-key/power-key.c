#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/signalfd.h>
#include <sys/timerfd.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "gesture.h"

static void die(const char *what)
{
    perror(what);
    exit(EXIT_FAILURE);
}

static bool bit(const unsigned char *bits, unsigned int key)
{
    return (bits[key / 8] & (1u << (key % 8))) != 0;
}

static bool power_held(int fd)
{
    unsigned char keys[(KEY_CNT + 7) / 8] = {0};
    if (ioctl(fd, EVIOCGKEY(sizeof(keys)), keys) < 0)
        die("EVIOCGKEY");
    return bit(keys, KEY_POWER);
}

static void arm(int timer, const struct gesture *g)
{
    struct itimerspec spec = {0};
    if (g->down && !g->fired) {
        int64_t deadline = g->start_ns + HOLD_NS;
        spec.it_value.tv_sec = deadline / INT64_C(1000000000);
        spec.it_value.tv_nsec = deadline % INT64_C(1000000000);
    }
    if (timerfd_settime(timer, TFD_TIMER_ABSTIME, &spec, NULL) < 0)
        die("timerfd_settime");
}

static void dispatch(enum action action, const char *command, pid_t *child)
{
    if (action == ACTION_NONE)
        return;
    const char *name = action == ACTION_TOGGLE ? "toggle" : "menu";
    if (*child > 0) {
        fprintf(stderr, "Ignoring %s while previous bounded action is running\n", name);
        return;
    }
    pid_t pid = fork();
    if (pid < 0) {
        perror("fork action");
        return;
    }
    if (pid == 0) {
        sigset_t empty;
        sigemptyset(&empty);
        sigprocmask(SIG_SETMASK, &empty, NULL);
        prctl(PR_SET_PDEATHSIG, SIGTERM);
        execl(command, command, name, (char *)NULL);
        _exit(127);
    }
    *child = pid;
    fprintf(stderr, "Power key action: %s\n", name);
}

int main(int argc, char **argv)
{
    if (argc != 3 || argv[2][0] != '/') {
        fprintf(stderr, "Usage: %s INPUT_DEVICE ABSOLUTE_ACTION_COMMAND\n", argv[0]);
        return EXIT_FAILURE;
    }
    int input = open(argv[1], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (input < 0)
        die("open input");
    char name[256] = {0};
    unsigned char keys[(KEY_CNT + 7) / 8] = {0};
    if (ioctl(input, EVIOCGNAME(sizeof(name) - 1), name) < 0 ||
        ioctl(input, EVIOCGBIT(EV_KEY, sizeof(keys)), keys) < 0)
        die("input identity");
    if (strcmp(name, "pmic_pwrkey") || !bit(keys, KEY_POWER)) {
        fprintf(stderr, "Refusing an input device other than pmic_pwrkey\n");
        return EXIT_FAILURE;
    }
    for (unsigned int key = 0; key < KEY_CNT; key++) {
        if (key != KEY_POWER && bit(keys, key)) {
            fprintf(stderr, "Refusing a device with additional keys\n");
            return EXIT_FAILURE;
        }
    }
    int clock_id = CLOCK_MONOTONIC;
    if (ioctl(input, EVIOCSCLOCKID, &clock_id) < 0)
        die("EVIOCSCLOCKID");
    sigset_t signals;
    sigemptyset(&signals);
    sigaddset(&signals, SIGTERM);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGCHLD);
    if (sigprocmask(SIG_BLOCK, &signals, NULL) < 0)
        die("sigprocmask");
    int signal_fd = signalfd(-1, &signals, SFD_CLOEXEC | SFD_NONBLOCK);
    int timer = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC | TFD_NONBLOCK);
    if (signal_fd < 0 || timer < 0)
        die("event descriptors");
    if (ioctl(input, EVIOCGRAB, 1) < 0)
        die("EVIOCGRAB");
    struct gesture g;
    gesture_reset(&g, power_held(input));
    fprintf(stderr, "Exclusively handling pmic_pwrkey; hold=2000ms\n");
    bool dropped = false;
    bool stop = false;
    pid_t child = 0;
    struct pollfd fds[] = {
        { .fd = input, .events = POLLIN },
        { .fd = timer, .events = POLLIN },
        { .fd = signal_fd, .events = POLLIN },
    };
    while (!stop) {
        if (poll(fds, 3, -1) < 0) {
            if (errno == EINTR)
                continue;
            die("poll");
        }
        if (fds[0].revents & (POLLHUP | POLLERR | POLLNVAL)) {
            fprintf(stderr, "Input device disconnected\n");
            break;
        }
        if (fds[2].revents & POLLIN) {
            struct signalfd_siginfo sig;
            while (read(signal_fd, &sig, sizeof(sig)) == sizeof(sig)) {
                if (sig.ssi_signo == SIGTERM || sig.ssi_signo == SIGINT) {
                    stop = true;
                } else if (sig.ssi_signo == SIGCHLD) {
                    int status;
                    pid_t pid;
                    while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
                        if (pid == child) {
                            child = 0;
                            if (!WIFEXITED(status) || WEXITSTATUS(status))
                                fprintf(stderr, "Power key action failed: status=%d\n", status);
                        }
                    }
                }
            }
        }
        if (stop)
            break;
        /* Drain key releases before examining an expired hold timer. */
        if (fds[0].revents & POLLIN) {
            struct input_event events[32];
            ssize_t size;
            while ((size = read(input, events, sizeof(events))) > 0) {
                if (size % sizeof(events[0])) {
                    fprintf(stderr, "Incomplete input event\n");
                    return EXIT_FAILURE;
                }
                for (size_t i = 0; i < (size_t)size / sizeof(events[0]); i++) {
                    struct input_event *e = &events[i];
                    if (e->type == EV_SYN && e->code == SYN_DROPPED) {
                        dropped = true;
                        gesture_reset(&g, true);
                        arm(timer, &g);
                    } else if (dropped) {
                        if (e->type == EV_SYN && e->code == SYN_REPORT) {
                            dropped = false;
                            gesture_reset(&g, power_held(input));
                        }
                    } else if (e->type == EV_KEY && e->code == KEY_POWER) {
                        int64_t ns = (int64_t)e->time.tv_sec * INT64_C(1000000000) +
                            (int64_t)e->time.tv_usec * 1000;
                        dispatch(gesture_key(&g, e->value, ns), argv[2], &child);
                        arm(timer, &g);
                    }
                }
            }
            if (size < 0 && errno != EAGAIN && errno != EINTR)
                die("read input");
        }
        if (fds[1].revents & POLLIN) {
            uint64_t expirations;
            if (read(timer, &expirations, sizeof(expirations)) == sizeof(expirations))
                dispatch(gesture_timeout(&g), argv[2], &child);
        }
    }
    ioctl(input, EVIOCGRAB, 0);
    close(input);
    close(timer);
    close(signal_fd);
    return EXIT_SUCCESS;
}
