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
             str(ROOT / "Tests/PrivacyReadingSupportTests/main.swift"), "-o", str(cls.runner)],
            check=False, capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)

    def test_reading_observations(self):
        for scenario in ("ready-once", "offscreen", "missing", "live-unhittable",
                         "changed-after-scroll", "navigation-changed", "irrelevant-navigation",
                         "nonhittable-navigation", "center-required", "duplicate-target",
                         "duplicate-list", "duplicate-navigation", "missing-list", "empty-viewport",
                         "all-twenty-targets"):
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

    def test_ui_target_compiles_the_test_policy(self):
        project = (ROOT / "CleanSend.xcodeproj/project.pbxproj").read_text()
        self.assertIn("PrivacyReadingSample.swift in Sources", project)
        self.assertIn("PrivacyReadingSample.swift", project)


if __name__ == "__main__":
    unittest.main()
