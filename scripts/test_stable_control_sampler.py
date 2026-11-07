"""Exercise the real test-only Swift policy without launching a simulator."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class StableControlSamplerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="stable-control-tests-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.runner = pathlib.Path(cls.scratch.name) / "sampler-tests"
        result = subprocess.run(
            ["swiftc", str(ROOT / "Tests/UITests/StableControlSampler.swift"),
             str(ROOT / "Tests/UIControlSupportTests/main.swift"), "-o", str(cls.runner)],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)

    def test_sampling_boundaries(self):
        for scenario in ("slow-snapshots", "moved", "disabled", "unhittable", "missing",
                         "late-snapshot", "late-hittability", "expired-start", "backwards-clock",
                         "native-cost-delayed-predicate", "driver-native-costs", "driver-fast",
                         "driver-early-yield", "driver-moving", "driver-disabled", "driver-unhittable",
                         "driver-missing", "driver-invalid-geometry", "driver-nonfinite-geometry", "driver-recovers", "driver-late-snapshot",
                         "driver-late-hittability", "driver-late-pause", "driver-frozen-clock",
                         "driver-backwards-clock", "driver-nonfinite-clock"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.runner), scenario], check=True,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.stdout.strip(), "PASS " + scenario)

    def test_committed_ui_target_contains_sampler(self):
        project = (ROOT / "CleanSend.xcodeproj/project.pbxproj").read_text()
        self.assertIn("StableControlSampler.swift in Sources", project)
        self.assertIn("StableControlSampler.swift", project)


if __name__ == "__main__":
    unittest.main()
