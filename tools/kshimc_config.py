"""Validate the generated TB322FC diagnostic configuration."""
import re


def check_config(path):
    values = dict(re.findall(r"^#define CONFIG_(\w+)\s+([^\n]+)", path.read_text(), re.M))
    expected = {
        "QCOM_KEYS": "1", "QCOM_SPMI": "1", "QCOM_KEY_DEBOUNCE_SAMPLES": "2",
        "KSHIM_FRAMEBUFFER": "1", "KSHIM_LVGL": "1", "KSHIM_UI_ROTATION_CCW": "270",
        "KSHIM_LVGL_BUFFER_BYTES": "243712", "KSHIM_MENU_BASE_ANDROID": "1",
        "KSHIM_MENU_SESSION_SETTINGS": "1", "KSHIM_MENU_SINGLE_LINUX": "1",
        "KSHIM_DIAG_MARKER": "1", "KSHIM_DIAGNOSTIC_MENU_LIMIT_MS": "20000",
        "KSHIM_UI_SCRATCH_BASE": "0x0", "KSHIM_UI_SCRATCH_SIZE": "0x0",
    }
    disabled = [
        "KSHIM_BOOT_LAST", "KSHIM_CHARGER_MODE", "KSHIM_QCOM_REBOOT",
        "KSHIM_MENU_POWER_ACTIONS", "KSHIM_MENU_ADVANCED_ACTIONS", "KSHIM_SMP",
        "KSHIM_TOUCH", "KSHIM_UEFI_TEST_MENU", "KSHIM_QEMU_PLATFORM",
        "KSHIM_DEBUG_CONSOLE", "KSHIM_SPLASH_FALLBACK", "KSHIM_DIAG_PAINT",
    ]
    for name, value in expected.items():
        if values.get(name) != value:
            raise ValueError(f"Unexpected generated configuration: {name}")
    for name in disabled:
        if values.get(name, "0") != "0":
            raise ValueError(f"Forbidden diagnostic capability: {name}")
    return {"required": expected, "disabled": disabled}
