#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define BLOCK 4096ULL
#define MAX_RANGES 16384
#define MAX_BYTES (8ULL << 30)
#define CHUNK 65536
#define PROBE_BYTES 65536
struct range { uint64_t block; uint64_t count; };

static int write_all(const void *data, size_t size) {
    const unsigned char *cursor = data;
    while (size) {
        ssize_t n = write(STDOUT_FILENO, cursor, size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        cursor += n;
        size -= (size_t)n;
    }
    return 0;
}

struct encoder { unsigned char carry[2]; size_t used; };
static const char alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/* No whitespace is emitted: Windows text-mode newline conversion cannot
 * change this wire format. Carry spans reads and non-contiguous ranges. */
static int encode(struct encoder *state, const unsigned char *data, size_t size) {
    unsigned char input[CHUNK + 2];
    char output[((CHUNK + 2) / 3) * 4];
    if (size > CHUNK) return -1;
    memcpy(input, state->carry, state->used);
    memcpy(input + state->used, data, size);
    size += state->used;
    size_t full = size - size % 3, out = 0;
    for (size_t i = 0; i < full; i += 3) {
        unsigned n = (unsigned)input[i] << 16 |
                     (unsigned)input[i + 1] << 8 | input[i + 2];
        output[out++] = alphabet[n >> 18];
        output[out++] = alphabet[(n >> 12) & 63];
        output[out++] = alphabet[(n >> 6) & 63];
        output[out++] = alphabet[n & 63];
    }
    state->used = size - full;
    memcpy(state->carry, input + full, state->used);
    return write_all(output, out);
}

static int encode_end(struct encoder *state) {
    if (!state->used) return 0;
    unsigned n = (unsigned)state->carry[0] << 16;
    if (state->used == 2) n |= (unsigned)state->carry[1] << 8;
    char output[4] = {alphabet[n >> 18], alphabet[(n >> 12) & 63],
                      state->used == 2 ? alphabet[(n >> 6) & 63] : '=', '='};
    return write_all(output, sizeof(output));
}

static void start_record(bool base64, size_t ranges, uint64_t bytes) {
    if (base64)
        fprintf(stderr, "Y700_RANGE_READER_V2 event=start ranges=%zu bytes=%llu encoding=base64 encoded_bytes=%llu\n",
                ranges, (unsigned long long)bytes,
                (unsigned long long)((bytes + 2) / 3 * 4));
    else
        fprintf(stderr, "Y700_RANGE_READER_V1 event=start ranges=%zu bytes=%llu\n",
                ranges, (unsigned long long)bytes);
}

static void done_record(bool base64, uint64_t bytes) {
    if (base64)
        fprintf(stderr, "Y700_RANGE_READER_V2 event=done bytes=%llu encoding=base64 encoded_bytes=%llu\n",
                (unsigned long long)bytes,
                (unsigned long long)((bytes + 2) / 3 * 4));
    else
        fprintf(stderr, "Y700_RANGE_READER_V1 event=done bytes=%llu\n",
                (unsigned long long)bytes);
}

static int integer(const char *s, uint64_t *result, const char **end) {
    if (*s < '0' || *s > '9') return -1;
    char *tail;
    errno = 0;
    unsigned long long n = strtoull(s, &tail, 10);
    if (errno) return -1;
    *result = n;
    *end = tail;
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--probe-base64")) {
        unsigned char data[PROBE_BYTES];
        for (size_t i = 0; i < sizeof(data); i++) data[i] = (unsigned char)i;
        struct encoder state = {0};
        start_record(true, 0, sizeof(data));
        if (encode(&state, data, sizeof(data)) || encode_end(&state)) return 7;
        done_record(true, sizeof(data));
        return 0;
    }
    bool base64 = argc == 6 && !strcmp(argv[1], "--base64");
    if (base64) { argc--; argv++; }
    uint64_t source_bytes;
    const char *end;
    if (argc != 5 || (strcmp(argv[1], "--block") && strcmp(argv[1], "--file")) ||
        integer(argv[3], &source_bytes, &end) || *end || !source_bytes ||
        source_bytes % BLOCK || source_bytes > (512ULL << 30)) return 2;
    int plan_fd = open(argv[4], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat st;
    if (plan_fd < 0 || fstat(plan_fd, &st) || !S_ISREG(st.st_mode) ||
        st.st_size <= 0 || st.st_size > (1 << 20)) return 3;
    FILE *plan = fdopen(plan_fd, "r");
    if (!plan) return 3;
    struct range ranges[MAX_RANGES];
    size_t used = 0;
    uint64_t total = 0, previous_end = 0;
    char line[96];
    while (fgets(line, sizeof(line), plan)) {
        uint64_t block, count;
        if (used == MAX_RANGES || integer(line, &block, &end) || *end != ' ' ||
            integer(end + 1, &count, &end) || strcmp(end, "\n") ||
            count == 0 || count > 256 || block >= source_bytes / BLOCK ||
            count > source_bytes / BLOCK - block ||
            (!used && block != 0) || block < previous_end ||
            count * BLOCK > MAX_BYTES - total) return 4;
        ranges[used++] = (struct range){block, count};
        previous_end = block + count;
        total += count * BLOCK;
    }
    if (ferror(plan) || fclose(plan) || !used) return 4;
    int source = open(argv[2], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    uint64_t actual = 0;
    if (source < 0 || fstat(source, &st)) return 5;
    if (!strcmp(argv[1], "--block")) {
        if (!S_ISBLK(st.st_mode) || ioctl(source, BLKGETSIZE64, &actual)) return 5;
    } else {
        if (!S_ISREG(st.st_mode) || st.st_size < 0) return 5;
        actual = (uint64_t)st.st_size;
    }
    if (actual != source_bytes) return 5;
    start_record(base64, used, total);
    struct encoder state = {0};
    unsigned char buffer[CHUNK];
    for (size_t i = 0; i < used; i++) {
        uint64_t offset = ranges[i].block * BLOCK, remaining = ranges[i].count * BLOCK;
        while (remaining) {
            size_t wanted = remaining < sizeof(buffer) ? (size_t)remaining : sizeof(buffer);
            ssize_t n;
            do { n = pread(source, buffer, wanted, (off_t)offset); }
            while (n < 0 && errno == EINTR);
            if (n <= 0) return 6;
            if (base64 ? encode(&state, buffer, (size_t)n) :
                         write_all(buffer, (size_t)n)) return 7;
            remaining -= (uint64_t)n;
            offset += (uint64_t)n;
        }
    }
    if (close(source)) return 8;
    if (base64 && encode_end(&state)) return 7;
    done_record(base64, total);
    return 0;
}
