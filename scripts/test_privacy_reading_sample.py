"""Exercise the privacy reading geometry without starting a simulator."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PrivacyReadingSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="privacy-reading-tests-")
        cls.addClassCleanup(cls.scratch.cleanup)
        cls.runner = pathlib.Path(cls.scratch.name) / "reading-tests"
        result = subprocess.run(
            ["swiftc", str(ROOT / "Tests/UITests/PrivacyReadingSample.swift"),
             str(ROOT / "Tests/PrivacyReadingSupportTests/main.swift"),
             "-module-cache-path", str(pathlib.Path(cls.scratch.name) / "module-cache"),
             "-o", str(cls.runner)],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)

    def test_reading_observations(self):
        for scenario in ("ready-once", "offscreen", "missing", "live-unhittable",
                         "changed-after-scroll", "navigation-changed", "irrelevant-navigation",
                         "nonhittable-navigation", "center-required", "duplicate-target",
                         "duplicate-list", "duplicate-navigation", "missing-list", "empty-viewport",
                         "all-twenty-targets", "long-static-settle", "stability-frame",
                         "stability-label", "stability-list", "stability-navigation",
                         "stability-offscreen", "stability-missing", "stability-empty-label",
                         "invalid-frames", "irrelevant-empty-navigation", "invalid-navigation",
                         "horizontal-capture-boundary", "horizontal-wrap-tolerance", "stability-clock"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.runner), scenario], check=True,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.stdout.strip(), "PASS " + scenario)

    def test_paragraphs_keep_their_static_text_binding(self):
        source = (ROOT / "Tests/UITests/PrivacySupportUITests.swift").read_text()
        self.assertIn('let paragraph = app.staticTexts[identifier]', source)
        self.assertIn('revealInformation(paragraph, identifier: identifier, in: app)', source)
        self.assertIn('revealInformation(link, identifier: identifier, in: app, needsCenter: true)', source)
        observer = source.split('private func revealInformation(', 1)[1].split('private func assertTranslated', 1)[0]
        self.assertIn('targetIsHittable: { element.isHittable }', observer)
        self.assertNotIn('descendants(matching: .any)', observer)

    def test_capture_settling_uses_one_fresh_typed_snapshot(self):
        source = (ROOT / "Tests/UITests/PrivacySupportUITests.swift").read_text()
        observer = source.split('private func readingPosition(', 1)[1].split('private func assertTranslated', 1)[0]
        settle = source.split('private func waitForStableReading(', 1)[1].split('private func capture(', 1)[0]
        self.assertEqual(observer.count('try app.snapshot()'), 1)
        self.assertIn('node.elementType != expectedTargetType', observer)
        self.assertIn('throw PrivacyReadingSample.Invalid.unexpectedTargetType', observer)
        self.assertIn('expectedTargetType: .staticText', settle)
        self.assertIn('self.readingPosition(identifier: identifier, in: app', settle)
        self.assertNotIn('.isHittable', settle)
        self.assertNotIn('.snapshot()', settle)
        self.assertIn('XCTWaiter.wait(for: [expectation], timeout: 6)', settle)
        self.assertIn('if let failure', settle)
        self.assertIn('guard waitForStableReading(identifier: identifier, in: app) else { return read }', source)
        self.assertIn('guard waitForStableReading(identifier: paragraphIDs[0], in: app) else { return }', source)

    def test_ui_target_compiles_the_test_policy(self):
        project = (ROOT / "CleanSend.xcodeproj/project.pbxproj").read_text()
        self.assertIn("PrivacyReadingSample.swift in Sources", project)
        self.assertIn("PrivacyReadingSample.swift", project)


if __name__ == "__main__":
    unittest.main()
