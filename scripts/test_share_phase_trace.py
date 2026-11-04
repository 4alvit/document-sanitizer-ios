"""Real Foundation-only trace tests; no simulator, app launch or network."""
import pathlib
import json
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SharePhaseTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="share-phase-trace-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.folder = pathlib.Path(cls.scratch.name)
        source = ROOT / "App/SharePhaseTrace.swift"
        main = ROOT / "Tests/ShareTraceSupportTests/main.swift"
        cls.runners = {}
        for mode, flags in (("trace", ["-D", "CLEANSEND_SHARE_TRACE"]), ("release", ["-O"])):
            runner = cls.folder / mode
            result = subprocess.run(
                ["swiftc", *flags, str(source), str(main), "-o", str(runner)],
                capture_output=True, text=True, check=False, timeout=60,
            )
            if result.returncode:
                raise RuntimeError(result.stderr)
            cls.runners[mode] = runner

    def test_diagnostic_boundaries(self):
        for scenario in ("opt-in", "phase-order", "main-delay", "time-bound", "event-bound",
                         "completion", "disappearance", "invalid-clock", "file", "existing",
                         "symlink", "invalid-event", "concurrent", "file-cap"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(dir=self.folder) as folder:
                result = subprocess.run([str(self.runners["trace"]), scenario, folder],
                                        capture_output=True, text=True, check=True, timeout=10)
                self.assertEqual(result.stdout.strip(), "PASS " + scenario)

    def test_ordinary_optimized_build_compiles_trace_out(self):
        result = subprocess.run([str(self.runners["release"])], check=True, capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.stdout.strip(), "TRACE_COMPILED_OUT")
        names = subprocess.check_output(["nm", str(self.runners["release"])], text=True, timeout=10)
        self.assertNotIn("ShareTrace", names)
        self.assertNotIn(b"cleansend-share-phase-trace-v1.jsonl", self.runners["release"].read_bytes())

    def test_normal_configuration_has_no_diagnostic_opt_in(self):
        self.assertNotIn("CLEANSEND_SHARE_TRACE", (ROOT / "project.yml").read_text())
        self.assertNotIn("CLEANSEND_SHARE_TRACE", (ROOT / "CleanSend.xcodeproj/project.pbxproj").read_text())
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            if path.name == "share-phase-diagnostic.yml":
                # The exception remains isolated by semantics, not filename alone.
                workflow = json.loads(path.read_text())
                self.assertEqual(workflow["on"], {"push": {"branches": ["diagnostics/sanitizer14-share-phase-timing"]}})
                self.assertEqual(workflow["permissions"], {"contents": "read"})
                self.assertEqual(set(workflow["jobs"]), {"diagnostic"})
                self.assertEqual(workflow["jobs"]["diagnostic"]["if"],
                                 "github.event.created && !github.event.deleted && github.run_attempt == 1")
                continue
            self.assertNotIn("CLEANSEND_SHARE_TRACE", path.read_text(), str(path))
        self.assertIn("SharePhaseTrace.swift in Sources", (ROOT / "CleanSend.xcodeproj/project.pbxproj").read_text())


if __name__ == "__main__":
    unittest.main()
