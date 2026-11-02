#ifndef Y700_POWER_KEY_GESTURE_H
#define Y700_POWER_KEY_GESTURE_H

#include <stdbool.h>
#include <stdint.h>

#define HOLD_NS INT64_C(2000000000)

enum action { ACTION_NONE, ACTION_TOGGLE, ACTION_MENU };

struct gesture {
    bool down;
    bool fired;
    bool suppress;
    int64_t start_ns;
};

static inline void gesture_reset(struct gesture *g, bool held)
{
    *g = (struct gesture){ .suppress = held };
}

static inline enum action gesture_key(struct gesture *g, int value, int64_t now)
{
    if (value == 2)
        return ACTION_NONE;
    if (g->suppress) {
        if (value == 0)
            gesture_reset(g, false);
        return ACTION_NONE;
    }
    if (value == 1 && !g->down) {
        *g = (struct gesture){ .down = true, .start_ns = now };
    } else if (value == 0 && g->down) {
        enum action result = g->fired ? ACTION_NONE :
            now - g->start_ns >= HOLD_NS ? ACTION_MENU : ACTION_TOGGLE;
        gesture_reset(g, false);
        return result;
    }
    return ACTION_NONE;
}

static inline enum action gesture_timeout(struct gesture *g)
{
    if (!g->down || g->fired || g->suppress)
        return ACTION_NONE;
    g->fired = true;
    return ACTION_MENU;
}

#endif
