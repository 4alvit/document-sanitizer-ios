"""Inert trace/parser tests. No application, simulator, subprocess, or network."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent / 'release_smoke'

def load(name):
    spec = importlib.util.spec_from_file_location('share_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

E, B, R = load('evidence'), load('window'), load('run')
TRACE = '11111111-1111-4111-8111-111111111111'
OPERATION = '22222222-2222-4222-8222-222222222222'

def event(**changes):
    row = dict(trace=TRACE, operation=OPERATION, sequence=1, phase='filesReady', uptime=10.0, time=20.0)
    row.update(changes)
    return row

def encoded(*rows):
    return b''.join(json.dumps(row).encode() + b'\n' for row in rows)

class ShareTimingTests(unittest.TestCase):
    def test_selected_case_and_exact_single_trace(self):
        marker = ('REDACT_SHARE_TRACE trace=' + TRACE + '\n').encode()
        self.assertIsNone(R.selected_share_trace(marker))
        self.assertEqual(R.selected_share_trace(R.CASE_STARTED + b'\n' + marker + R.WORKSPACE_READY), TRACE)
        self.assertIsNone(R.selected_share_trace(R.CASE_STARTED + b'\n' + marker * 2))
        self.assertIsNone(R.selected_share_trace(R.CASE_STARTED + b'\nREDACT_SHARE_TRACE trace=../outside\n'))

    def test_complete_and_partial_prefix(self):
        raw = encoded(event(), event(sequence=2, phase='mainActorResumed', uptime=11.0))
        self.assertEqual(len(E.parse_share_timing(raw, TRACE)['rows']), 2)
        partial = E.parse_share_timing(raw + b'{"trace":', TRACE)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(len(partial['rows']), 2)

    def test_rejects_identity_private_fields_and_unknown_events(self):
        for row in (event(trace=OPERATION), event(filename='private'), event(phase='unknown'),
                    event(operation='../outside'), event(packet='not-a-uuid'), event(sequence=True)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                E.parse_share_timing(encoded(row), TRACE)
        with self.assertRaises(ValueError):
            E.parse_share_timing(encoded(event()).replace(b'"sequence": 1', b'"sequence": 1, "sequence": 1'), TRACE)

    def test_monotonic_and_sequence_requirements(self):
        for row in (event(sequence=3), event(sequence=2, uptime=9),
                    event(sequence=2, operation=TRACE), event(sequence=2, uptime=float('nan'))):
            with self.subTest(row=row), self.assertRaises(ValueError):
                E.parse_share_timing(encoded(event(), row), TRACE)

    def test_bounds(self):
        with self.assertRaises(ValueError): E.parse_share_timing(b' ' * (16 * 1024 + 1), TRACE)
        with self.assertRaises(ValueError): E.parse_share_timing(encoded(*(event(sequence=n) for n in range(1, 34))), TRACE)

    def test_exact_regular_file_read_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp).resolve()
            self.assertEqual(E.read_share_timing(data, TRACE, B, lambda: None)['status'], 'missing')
            directory = data / 'Library/Caches/ShareTiming'
            directory.mkdir(parents=True)
            (directory / (TRACE + '.jsonl')).write_bytes(encoded(event()))
            (directory / 'unrelated').write_bytes(b'not read')
            result = E.read_share_timing(data, TRACE, B, lambda: None)
            self.assertEqual(result['rows'], [event()])
            self.assertEqual((directory / 'unrelated').read_bytes(), b'not read')

    def test_symlink_trace_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp).resolve()
            directory = data / 'Library/Caches/ShareTiming'
            directory.mkdir(parents=True)
            outside = data / 'outside'
            outside.write_bytes(encoded(event()))
            (directory / (TRACE + '.jsonl')).symlink_to(outside)
            self.assertEqual(E.read_share_timing(data, TRACE, B, lambda: None)['status'], 'unavailable')

    def test_original_deadline_is_not_swallowed_or_reset(self):
        def expired(): raise TimeoutError('existing deadline')
        with self.assertRaises(TimeoutError): E.read_share_timing(Path('/unused'), TRACE, B, expired)

if __name__ == '__main__':
    unittest.main()
