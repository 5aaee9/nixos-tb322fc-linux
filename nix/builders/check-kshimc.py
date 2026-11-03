from pathlib import Path
import re
import sys

project = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project / "tools"))
from kshimc_config import check_config
root = Path(sys.argv[1])
check_config(root / "generated/include/config.h")
cache = dict(re.findall(r"^(\w+):[^=]+=(.*)$", (root / "CMakeCache.txt").read_text(), re.M))
for key in ("KSHIM_STANDALONE", "KSHIM_DIAGNOSTIC_BASE_ONLY", "KSHIM_DIAGNOSTIC_DT_ONLY",
            "KSHIM_DIAGNOSTIC_RESOURCES_ONLY", "KSHIM_RAMOOPS_RECOVERY_ONLY"):
    if cache.get(key) != "OFF":
        raise ValueError("Unexpected runtime CMake switch: " + key)
if cache.get("KSHIM_UEFI_PAYLOAD") != "":
    raise ValueError("Unexpected embedded UEFI payload")
