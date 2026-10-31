"""Synthetic summary contracts; never creates a simulator or native process."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('privacy_summary_driver', Path(__file__).with_name('check-privacy-ipad.py'))
m = importlib.util.module_from_spec(SPEC)
with patch('subprocess.Popen', side_effect=AssertionError('native spawn forbidden')):
    SPEC.loader.exec_module(m)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.native = patch('subprocess.Popen', side_effect=AssertionError('native spawn forbidden'))
        self.native.start()
        self.addCleanup(self.native.stop)

    def metadata(self):
        return {'failures': ["TimeoutExpired(['/Users/secret/document.pdf'], 20)",
                             "Cleanup: AssertionError('private person@example.test')"],
                'commands': [{'args': ['xcrun', 'simctl', 'launch', 'PRIVATE_UUID', 'private.bundle'],
                              'command_error': "TimeoutExpired('private data', 20)",
                              'command_error_operation': 'wait', 'timeout_seconds': 20,
                              'returncode': -15, 'owned_group_absent': True}],
                'cleanup': {'shutdown': 0, 'delete': 0, 'secret': 'not printed'},
                'device_removed': True, 'source_paths': ['/Users/secret']}

    def test_expected_status_only_projection(self):
        value = m.privacy_failure_summary({'worker_returncode': 1, 'error': "AssertionError('Worker failed')"}, self.metadata(), 'available')
        self.assertEqual(value['failure_kinds'], ['AssertionError', 'TimeoutExpired'])
        self.assertEqual(value['first_command_issue'], {'index': 0, 'command': 'simctl.launch',
            'error_kind': 'TimeoutExpired', 'returncode': -15, 'operation': 'wait',
            'timeout_seconds': 20, 'owned_group_absent': True})
        self.assertTrue(value['owned_device_removed'])
        self.assertEqual(value['result'], 'failed')

    def test_no_private_values_in_output(self):
        value = m.privacy_failure_summary({'worker_returncode': 1, 'error': "RuntimeError('secret')"}, self.metadata(), 'available')
        encoded = json.dumps(value)
        for secret in ['PRIVATE_UUID', 'private.bundle', '/Users/', 'document.pdf', 'person@', 'private data', 'not printed', 'secret']:
            self.assertNotIn(secret, encoded)

    def test_unknown_or_malformed_fields_fail_closed(self):
        raw = {'commands': [None, {'args': ['secret-command'], 'returncode': 2,
                'command_error': {'private': 1}, 'command_error_operation': ['secret'],
                'timeout_seconds': float('nan'), 'owned_group_absent': 'true'}],
                'failures': [None, {}, 'private.exception(credentials)'],
                'device_removed': 'true', 'cleanup': {'shutdown': True, 'delete': 99999}}
        value = m.privacy_failure_summary({}, raw, 'available')
        self.assertEqual(value['first_command_issue']['command'], 'unknown')
        self.assertEqual(value['failure_kinds'], ['unknown'])
        self.assertIsNone(value['owned_device_removed'])
        self.assertEqual(value['cleanup_returncodes'], {'shutdown': None, 'delete': None})
        self.assertNotIn('timeout_seconds', value['first_command_issue'])

    def test_count_and_output_bounds(self):
        raw = {'failures': ['RuntimeError(secret)'] * 1000,
               'commands': [None] * 1000}
        value = m.privacy_failure_summary({}, raw, 'available')
        self.assertEqual(value['failure_count'], 512)
        self.assertTrue(value['failures_truncated'])
        self.assertTrue(value['commands_truncated'])
        self.assertLess(len(json.dumps(value)), m.SUMMARY_OUTPUT_LIMIT)

    def test_nonfatal_command_observation_does_not_relabel_cause_or_pass(self):
        raw = self.metadata()
        raw['commands'].append({'args': ['xcrun', 'simctl', 'ui', 'PRIVATE_UUID'], 'returncode': 0})
        raw['failures'] = ['AssertionError(later unrelated failure)']
        value = m.privacy_failure_summary({}, raw, 'available')
        self.assertEqual(value['first_command_issue']['command'], 'simctl.launch')
        self.assertEqual(value['result'], 'failed')
        self.assertNotIn('root_cause', value)

    def test_missing_metadata_keeps_supervisor_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            value, status = m.read_summary_metadata(Path(folder)/'missing', lambda: None)
        self.assertIsNone(value)
        self.assertEqual(status, 'missing')
        self.assertEqual(m.privacy_failure_summary({'worker_returncode': -9}, value, status)['worker_returncode'], -9)

    def test_malformed_json_does_not_echo_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'metadata.json'
            path.write_text('secret invalid json')
            value, status = m.read_summary_metadata(path, lambda: None)
        self.assertIsNone(value)
        self.assertEqual(status, 'unavailable')

    def test_non_object_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'metadata.json'; path.write_text('[]')
            self.assertEqual(m.read_summary_metadata(path, lambda: None), (None, 'invalid_json'))

    def test_symlink_and_oversized_metadata_not_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); target=root/'large'; target.write_bytes(b'x'*(m.SUMMARY_INPUT_LIMIT+1))
            link=root/'link'; link.symlink_to(target)
            self.assertEqual(m.read_summary_metadata(target, lambda: None), (None, 'invalid_file'))
            self.assertEqual(m.read_summary_metadata(link, lambda: None), (None, 'unavailable'))

    def test_deadline_failure_is_bounded_status(self):
        def expired(): raise TimeoutError('secret')
        with patch.object(m.os, 'open') as opened:
            self.assertEqual(m.read_summary_metadata(Path('not-read'), expired), (None, 'deadline_exhausted'))
        opened.assert_not_called()

    def test_emit_one_json_line_and_never_raw_fields(self):
        with patch.object(m, 'read_summary_metadata', return_value=(self.metadata(), 'available')), contextlib.redirect_stdout(io.StringIO()) as output:
            m.emit_failure_summary({'worker_returncode': 1}, Path('unused'), lambda: None)
        lines=output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('PRIVACY_FAILURE_SUMMARY '))
        self.assertEqual(json.loads(lines[0].split(' ', 1)[1])['result'], 'failed')
        self.assertNotIn('private', lines[0])

    def test_output_failure_does_not_change_caller_result(self):
        with patch.object(m, 'read_summary_metadata', side_effect=OSError('secret')):
            self.assertIsNone(m.emit_failure_summary({}, Path('unused'), lambda: None))

    def test_supervisor_calls_summary_only_on_failure_without_replacing_exit(self):
        # Source-level integration contract: no execution of the hosted supervisor.
        import ast
        tree=ast.parse(Path(m.__file__).read_text())
        supervisor=next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name=='supervise')
        statement=supervisor.body[-2]
        self.assertIsInstance(statement, ast.If)
        self.assertEqual(ast.unparse(statement.test), "record['result'] != 'passed_pending_independent_review'")
        self.assertEqual(statement.body[0].value.func.id, 'emit_failure_summary')
        self.assertIsInstance(supervisor.body[-1], ast.Return)
        self.assertEqual(ast.unparse(supervisor.body[-1].value), "0 if record['result'] == 'passed_pending_independent_review' else 1")


if __name__ == '__main__':
    unittest.main()
