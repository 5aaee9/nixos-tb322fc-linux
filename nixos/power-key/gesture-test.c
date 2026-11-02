#include <assert.h>
#include <stdio.h>
#include "gesture.h"

int main(void)
{
    struct gesture g = {0};
    assert(gesture_key(&g, 0, 0) == ACTION_NONE);
    assert(gesture_key(&g, 1, 0) == ACTION_NONE);
    assert(gesture_key(&g, 2, 100) == ACTION_NONE);
    assert(gesture_key(&g, 1, 200) == ACTION_NONE);
    assert(g.start_ns == 0);
    assert(gesture_key(&g, 0, HOLD_NS - 1) == ACTION_TOGGLE);
    assert(gesture_timeout(&g) == ACTION_NONE);

    gesture_key(&g, 1, 100);
    assert(gesture_key(&g, 0, 100 + HOLD_NS) == ACTION_MENU);
    assert(gesture_timeout(&g) == ACTION_NONE);
    gesture_key(&g, 1, 100);
    assert(gesture_timeout(&g) == ACTION_MENU);
    assert(gesture_timeout(&g) == ACTION_NONE);
    assert(gesture_key(&g, 0, HOLD_NS + 100) == ACTION_NONE);
    gesture_key(&g, 1, 2 * HOLD_NS);
    assert(gesture_key(&g, 0, 2 * HOLD_NS + 100) == ACTION_TOGGLE);

    gesture_reset(&g, true);
    assert(gesture_key(&g, 1, 0) == ACTION_NONE);
    assert(gesture_timeout(&g) == ACTION_NONE);
    assert(gesture_key(&g, 0, HOLD_NS) == ACTION_NONE);
    gesture_key(&g, 1, 3 * HOLD_NS);
    assert(gesture_key(&g, 0, 3 * HOLD_NS + 100) == ACTION_TOGGLE);

    gesture_key(&g, 1, 0);
    gesture_reset(&g, false);
    assert(gesture_timeout(&g) == ACTION_NONE);
    assert(gesture_key(&g, 0, HOLD_NS) == ACTION_NONE);
    puts("gesture boundaries, repeats, held startup and lost-event reset pass");
}
