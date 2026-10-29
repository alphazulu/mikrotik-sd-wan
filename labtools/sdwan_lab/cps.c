#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop;
static void done(int signal_number) { (void)signal_number; stop = 1; }
static double seconds(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) exit(2);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static int exchange(int fd, void *data, size_t length, int sending) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t n = sending ? send(fd, (char *)data + offset, length - offset, MSG_NOSIGNAL)
                            : recv(fd, (char *)data + offset, length - offset, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        offset += (size_t)n;
    }
    return 0;
}
static int timed_socket(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct timeval timeout = {3, 0};
    if (fd < 0) return -1;
    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout))) {
        close(fd); return -1;
    }
    return fd;
}
#ifndef BENCH_RATE
#define BENCH_RATE 1250
#endif
#ifndef BENCH_WARMUP
#define BENCH_WARMUP 2
#endif
#ifndef BENCH_SECONDS
#define BENCH_SECONDS 10
#endif
#ifndef BENCH_CONCURRENCY
#define BENCH_CONCURRENCY 32
#endif
#define BENCH_COUNT ((BENCH_WARMUP + BENCH_SECONDS) * BENCH_RATE)
#define CLIENT_LIMIT BENCH_CONCURRENCY
struct slot { int fd, state; size_t sent, received; unsigned char out[32], in[32]; double created; };
struct counts { unsigned attempts, connected, success, failures, measured, active, peak; int last_errno; double start, maximum_late; };
static void finish_slot(struct slot *slot, struct counts *counts, int valid) {
    if (valid) {
        counts->success++;
        double stamp = seconds() - counts->start;
        if (stamp >= BENCH_WARMUP && stamp < BENCH_WARMUP + BENCH_SECONDS) counts->measured++;
    } else { counts->failures++; counts->last_errno = errno; }
    close(slot->fd); slot->fd = -1; counts->active--;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(atoi(argv[3]))};
    if (inet_pton(AF_INET, argv[2], &addr.sin_addr) != 1) return 2;
    if (!strcmp(argv[1], "server")) {
        struct sigaction action = {.sa_handler = done};
        sigemptyset(&action.sa_mask);
        sigaction(SIGINT, &action, NULL); sigaction(SIGTERM, &action, NULL);
        int listener = timed_socket(), one = 1;
        if (listener < 0 || setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
            bind(listener, (void *)&addr, sizeof(addr)) || listen(listener, 128)) return 2;
        puts("ready"); fflush(stdout);
        unsigned accepted = 0, completed = 0, errors = 0;
        while (!stop) {
            int fd = accept(listener, NULL, NULL);
            if (fd < 0) { if (errno == EINTR) continue; if (errno == EAGAIN || errno == EWOULDBLOCK) continue; return 2; }
            struct timeval timeout = {3, 0};
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            unsigned char blob[32]; accepted++;
            if (!exchange(fd, blob, sizeof(blob), 0) && !exchange(fd, blob, sizeof(blob), 1)) completed++;
            else errors++;
            close(fd);
        }
        close(listener);
        printf("{\"accepted\":%u,\"completed\":%u,\"errors\":%u,\"active\":0,\"peak_active\":1}\n", accepted, completed, errors);
        return 0;
    }
    if (strcmp(argv[1], "client")) return 2;
    struct counts counts = {.start = seconds()};
    struct slot slots[CLIENT_LIMIT];
    for (unsigned i = 0; i < CLIENT_LIMIT; i++) slots[i].fd = -1;
    while (counts.attempts < BENCH_COUNT || counts.active) {
        double now = seconds();
        for (unsigned i = 0; i < CLIENT_LIMIT; i++) {
            if (slots[i].fd >= 0 && now - slots[i].created >= 3) {
                errno = ETIMEDOUT; finish_slot(&slots[i], &counts, 0);
            }
        }
        while (counts.attempts < BENCH_COUNT && counts.active < CLIENT_LIMIT &&
               seconds() >= counts.start + counts.attempts / (double)BENCH_RATE) {
            double late = seconds() - (counts.start + counts.attempts / (double)BENCH_RATE);
            if (late > counts.maximum_late) counts.maximum_late = late;
            unsigned index = 0;
            while (index < CLIENT_LIMIT && slots[index].fd >= 0) index++;
            if (index == CLIENT_LIMIT) return 2;
            struct slot *slot = &slots[index];
            memset(slot, 0, sizeof(*slot));
            memcpy(slot->out, &counts.attempts, sizeof(counts.attempts));
            counts.attempts++; slot->created = seconds(); slot->fd = timed_socket();
            if (slot->fd < 0) { counts.failures++; counts.last_errno = errno; continue; }
            counts.active++;
            if (counts.active > counts.peak) counts.peak = counts.active;
            int flags = fcntl(slot->fd, F_GETFL);
            if (flags < 0 || fcntl(slot->fd, F_SETFL, flags | O_NONBLOCK)) {
                finish_slot(slot, &counts, 0); continue;
            }
            if (!connect(slot->fd, (void *)&addr, sizeof(addr))) {
                counts.connected++; slot->state = 1;
            } else if (errno != EINPROGRESS) finish_slot(slot, &counts, 0);
        }
        struct pollfd fds[CLIENT_LIMIT]; unsigned indices[CLIENT_LIMIT], n = 0;
        for (unsigned i = 0; i < CLIENT_LIMIT; i++) if (slots[i].fd >= 0) {
            indices[n] = i; fds[n].fd = slots[i].fd;
            fds[n].events = slots[i].state == 2 ? POLLIN : POLLOUT;
            fds[n].revents = 0; n++;
        }
        int timeout = 10;
        if (counts.attempts < BENCH_COUNT && counts.active < CLIENT_LIMIT) {
            double delay = counts.start + counts.attempts / (double)BENCH_RATE - seconds();
            timeout = delay <= 0 ? 0 : (int)(delay * 1000) + 1;
        }
        int ready = poll(fds, n, timeout);
        if (ready < 0) { if (errno == EINTR) continue; return 2; }
        for (unsigned i = 0; i < n; i++) {
            if (!fds[i].revents) continue;
            struct slot *slot = &slots[indices[i]];
            if (fds[i].revents & POLLNVAL) { errno = EBADF; finish_slot(slot, &counts, 0); continue; }
            if (slot->state == 0 || (fds[i].revents & POLLERR)) {
                int error = 0; socklen_t length = sizeof(error);
                if (getsockopt(slot->fd, SOL_SOCKET, SO_ERROR, &error, &length) || error) {
                    if (error) errno = error;
                    finish_slot(slot, &counts, 0); continue;
                }
                if (slot->state == 0) { counts.connected++; slot->state = 1; }
            }
            if (slot->state == 1) {
                while (slot->sent < sizeof(slot->out)) {
                    ssize_t bytes = send(slot->fd, slot->out + slot->sent, sizeof(slot->out) - slot->sent, MSG_NOSIGNAL);
                    if (bytes > 0) slot->sent += bytes;
                    else if (bytes < 0 && errno == EINTR) continue;
                    else if (bytes < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
                    else { finish_slot(slot, &counts, 0); break; }
                }
                if (slot->fd < 0) continue;
                if (slot->sent == sizeof(slot->out)) slot->state = 2;
            }
            if (slot->state == 2 && (fds[i].revents & (POLLIN | POLLHUP))) {
                while (slot->received < sizeof(slot->in)) {
                    ssize_t bytes = recv(slot->fd, slot->in + slot->received, sizeof(slot->in) - slot->received, 0);
                    if (bytes > 0) slot->received += bytes;
                    else if (bytes < 0 && errno == EINTR) continue;
                    else if (bytes < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
                    else { if (!bytes) errno = ECONNRESET; finish_slot(slot, &counts, 0); break; }
                }
                if (slot->fd >= 0 && slot->received == sizeof(slot->in)) {
                    int valid = !memcmp(slot->in, slot->out, sizeof(slot->in));
                    if (!valid) errno = EBADMSG;
                    finish_slot(slot, &counts, valid);
                }
            }
        }
    }
    struct rusage usage; getrusage(RUSAGE_SELF, &usage);
    printf("{\"offered_cps\":%u,\"attempts\":%u,\"connected\":%u,\"echo_success\":%u,\"error_count\":%u,\"errors\":[],\"last_errno\":%d,\"peak_active\":%u,\"concurrency_limit\":%u,\"maximum_schedule_lateness_seconds\":%.9f,\"measured_successes\":%u,\"successful_cps\":%.3f,\"duration_seconds\":%.6f,\"user_cpu_seconds\":%.6f,\"system_cpu_seconds\":%.6f,\"completion_times_seconds\":[]}\n",
           (unsigned)BENCH_RATE, counts.attempts, counts.connected, counts.success, counts.failures, counts.last_errno, counts.peak, (unsigned)BENCH_CONCURRENCY,
           counts.maximum_late, counts.measured, counts.measured / (double)BENCH_SECONDS, seconds() - counts.start,
           usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1e6, usage.ru_stime.tv_sec + usage.ru_stime.tv_usec / 1e6);
    return 0;
}
