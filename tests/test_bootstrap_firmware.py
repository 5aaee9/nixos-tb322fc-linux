"""Reject incomplete or substituted coprocessor firmware before packaging."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "bootstrap_initrd", Path(__file__).resolve().parents[1] / "tools/build-bootstrap-initrd.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapFirmware(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.firmware = self.root / "firmware"
        (self.firmware / "qcom/sm8750").mkdir(parents=True)
        self.manifest = self.root / "manifest.json"
        self.entries = []
        for name in ("adsp.mdt", "adsp.b00", "adsp.b01", "adsp_dtb.mdt", "adsp_dtb.b00"):
            path = "qcom/sm8750/" + name
            data = name.encode()
            (self.firmware / path).write_bytes(data)
            self.entries.append({
                "path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            })
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps({"files": self.entries}))

    def test_both_firmware_families_are_included(self):
        self.assertEqual(
            set(bootstrap.adsp_firmware(self.firmware, self.manifest)),
            {entry["path"] for entry in self.entries},
        )

    def test_missing_segment_refuses_packaging(self):
        (self.firmware / "qcom/sm8750/adsp.b01").unlink()
        with self.assertRaises(ValueError):
            bootstrap.adsp_firmware(self.firmware, self.manifest)

    def test_substituted_segment_refuses_packaging(self):
        (self.firmware / "qcom/sm8750/adsp.b01").write_bytes(b"firmware")
        with self.assertRaises(ValueError):
            bootstrap.adsp_firmware(self.firmware, self.manifest)

    def test_manifest_without_dtb_firmware_refuses_packaging(self):
        self.entries = [e for e in self.entries if "adsp_dtb" not in e["path"]]
        self.save()
        with self.assertRaises(ValueError):
            bootstrap.adsp_firmware(self.firmware, self.manifest)


if __name__ == "__main__":
    unittest.main()
