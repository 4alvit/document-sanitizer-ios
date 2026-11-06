"""Protect the required CI contexts without claiming native docs-only evidence."""
from pathlib import Path
import os
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = "needs.scope.outputs.run == 'false' && needs.scope.outputs.reason == 'documentation-only'"
FULL = "(needs.scope.outputs.run != 'false' || needs.scope.outputs.reason != 'documentation-only')"


class ScopeWorkflowTests(unittest.TestCase):
    def test_each_required_context_proves_scope_and_guards_native_work(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        for job in ['verify', 'privacy-ipad', 'native-storekit', 'package-smoke']:
            block = workflow.split('  ' + job + ':\n', 1)[1]
            block = re.split(r'(?m)^  [a-z][a-z0-9_-]*:\s*$', block, maxsplit=1)[0]
            self.assertRegex(block, r'(?m)^    needs: \[scope(?:, [a-z-]+)*\]$')
            self.assertIn("runs-on: ${{ " + DOCS + " && 'ubuntu-24.04' || 'macos-15' }}", block)
            steps = re.split(r'(?m)^      - ', block.split('    steps:\n', 1)[1])[1:]
            self.assertTrue(steps[0].startswith('name: Verify change scope\n'))
            for step in steps[1:]:
                self.assertRegex(step, r'(?m)^        if: .*' + re.escape(FULL) + '$')
            script = '\n'.join(line[10:] for line in steps[0].split('        run: |\n', 1)[1].splitlines())
            for result in ['success', 'failure', 'skipped', 'cancelled', '']:
                for run, reason in [('true', 'source-change'), ('false', 'documentation-only'), ('false', 'unknown'), ('', ''), ('FALSE', 'documentation-only')]:
                    env = {**os.environ, 'SCOPE_RESULT': result, 'SCOPE_RUN': run, 'SCOPE_REASON': reason}
                    with self.subTest(job=job, result=result, run=run, reason=reason):
                        status = subprocess.run(['bash', '-c', script], env=env, capture_output=True).returncode
                        self.assertEqual(status == 0, result == 'success' and (run == 'true' or (run == 'false' and reason == 'documentation-only')))
        self.assertIn("release_assets_ready: ${{ steps.release_upload.outcome == 'success' }}", workflow)
        self.assertEqual(workflow.count("needs.verify.outputs.release_assets_ready == 'true'"), 2)
        self.assertIn("needs['privacy-ipad'].result == 'success'", workflow)


if __name__ == '__main__':
    unittest.main()
