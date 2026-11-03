"""Optimized-mode rejection and mandatory acceptance-evidence writes; no native calls."""
import ast
import builtins
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
import zipfile

SCRIPTS = Path(__file__).resolve().parent


def isolated_definition(path, name, optimize, **namespace):
    # Compile the actual helper body under each mode, independently of the
    # entrypoint's deliberate refusal to import under optimized Python.
    tree = ast.parse(path.read_text(), filename=str(path))
    node = next(item for item in tree.body if getattr(item, 'name', None) == name)
    code = compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec', optimize=optimize)
    exec(code, namespace)
    return namespace[name]


class AcceptanceAssertionTests(unittest.TestCase):
    def test_optimized_entrypoints_refuse_before_imports_or_external_operations(self):
        for relative in ('check-native-storekit.py', 'check-privacy-ipad.py', 'probe_export_verifier.py'):
            path = SCRIPTS / relative
            tree = ast.parse(path.read_text(), filename=str(path))
            # Future imports are compile directives; exclude their harmless
            # runtime import so every ordinary import can be forbidden.
            tree.body = [node for node in tree.body if not (
                isinstance(node, ast.ImportFrom) and node.module == '__future__')]
            for optimize in (1, 2):
                with self.subTest(script=relative, optimize=optimize):
                    forbidden = mock.Mock(side_effect=AssertionError('external operation before refusal'))
                    safe_builtins = dict(vars(builtins), __import__=forbidden, open=forbidden)
                    with self.assertRaisesRegex(SystemExit, 'Python assertions must be enabled'):
                        exec(compile(tree, str(path), 'exec', optimize=optimize), {'__builtins__': safe_builtins})
                    forbidden.assert_not_called()
                    with tempfile.TemporaryDirectory() as directory:
                        result = subprocess.run(
                            [sys.executable, '-I', '-' + 'O' * optimize, str(path)],
                            cwd=directory, capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(result.stderr.strip(), 'Python assertions must be enabled')
                        self.assertEqual(result.stdout, '')
                        self.assertEqual(list(Path(directory).iterdir()), [])

    def writers(self, optimize):
        common = dict(json=json, os=os, time=time, TOTAL=1200)
        native = isolated_definition(SCRIPTS / 'check-native-storekit.py', 'write_small', optimize, **common)
        installed = isolated_definition(SCRIPTS / 'release_smoke/run.py', 'save_installed_runner', optimize, **common)
        return (
            lambda path, value: native(path, value, time.monotonic()),
            lambda path, value: installed(path, value, lambda: None),
        )

    def test_receipts_write_exact_bytes_once_in_all_modes(self):
        value = {'accepted': False}
        expected = (json.dumps(value, indent=2) + '\n').encode()
        for optimize in (0, 1, 2):
            for index, write in enumerate(self.writers(optimize)):
                with self.subTest(optimize=optimize, writer=index), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'receipt.json'
                    write(path, value)
                    self.assertEqual(path.read_bytes(), expected)
                    with self.assertRaises(FileExistsError):
                        write(path, {'different': True})
                    self.assertEqual(path.read_bytes(), expected)

    def test_short_receipt_writes_fail_once_without_flush_or_retry_in_all_modes(self):
        for optimize in (0, 1, 2):
            for index, write in enumerate(self.writers(optimize)):
                with self.subTest(optimize=optimize, writer=index):
                    stream = mock.MagicMock()
                    stream.__enter__.return_value = stream
                    stream.write.side_effect = lambda value: len(value) - 1
                    path = mock.Mock()
                    path.open.return_value = stream
                    with self.assertRaisesRegex(OSError, 'short receipt write'):
                        write(path, {'accepted': False})
                    path.open.assert_called_once_with('xb')
                    self.assertEqual(stream.write.call_count, 1)
                    stream.flush.assert_not_called()
                    stream.__exit__.assert_called_once()

    def test_event_write_failure_never_advances_evidence_state(self):
        for optimize in (0, 1, 2):
            with self.subTest(optimize=optimize):
                observer_class = isolated_definition(SCRIPTS / 'release_smoke/evidence.py', 'Observer', optimize,
                                                     json=json, time=time, Path=Path)
                observer = observer_class(None, lambda: None)
                observer.started = time.monotonic()
                observer.snapshot = lambda *args, **kwargs: {'entries': []}
                short = mock.Mock()
                short.write.side_effect = lambda raw: len(raw) - 1
                with self.assertRaisesRegex(OSError, 'short event evidence write'):
                    observer.event('group', 'tmp', short)
                self.assertEqual(short.write.call_count, 1)
                short.flush.assert_not_called()
                self.assertEqual(observer.events, [])
                self.assertIsNone(observer.previous)
                self.assertEqual(observer.evidence_bytes, 0)
                stream = io.BytesIO()
                observer.event('group', 'tmp', stream)
                self.assertEqual(len(stream.getvalue()), observer.evidence_bytes)
                self.assertEqual(len(observer.events), 1)
                observer.event('group', 'tmp', stream)
                self.assertEqual(len(stream.getvalue()), observer.evidence_bytes)

    def test_payload_write_occurs_once_and_short_write_closes_descriptor(self):
        for optimize in (0, 1, 2):
            for short in (False, True):
                with self.subTest(optimize=optimize, short=short), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    archive_path = root / 'package.zip'
                    raw = b'synthetic compiled payload'
                    expected = {'.': {'mode': '0755', 'directory': True},
                                'binary': {'mode': '0644', 'sha256': hashlib.sha256(raw).hexdigest()}}
                    with zipfile.ZipFile(archive_path, 'w') as archive:
                        for name, mode, content in [('CleanSend.app/', stat.S_IFDIR | 0o755, b''),
                                                    ('CleanSend.app/binary', stat.S_IFREG | 0o644, raw)]:
                            entry = zipfile.ZipInfo(name)
                            entry.external_attr = mode << 16
                            archive.writestr(entry, content)
                    bundle = root / 'unpacked/CleanSend.app'
                    extract = isolated_definition(SCRIPTS / 'release_smoke/run.py', 'extract_exact', optimize,
                        os=os, stat=stat, zipfile=zipfile, hashlib=hashlib, ZIP=archive_path,
                        ZIP_SHA=hashlib.sha256(archive_path.read_bytes()).hexdigest(), BUNDLE=bundle,
                        CONTEXT={'adhoc_zip_bytes': archive_path.stat().st_size},
                        sha=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())

                    @contextmanager
                    def open_directory(path):
                        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            yield descriptor
                        finally:
                            os.close(descriptor)

                    budget = SimpleNamespace(safe=lambda name: None, directory=open_directory)
                    evidence = SimpleNamespace(payload_inventory=lambda *args: expected)
                    resources = SimpleNamespace(check=lambda: None)
                    original_write = os.write
                    descriptors = []

                    def write(descriptor, value):
                        descriptors.append(descriptor)
                        return original_write(descriptor, value[:-1] if short else value)

                    with mock.patch.object(os, 'write', side_effect=write):
                        if short:
                            with self.assertRaisesRegex(OSError, 'short payload write'):
                                extract(budget, evidence, resources, expected)
                        else:
                            extract(budget, evidence, resources, expected)
                    self.assertEqual(len(descriptors), 1)
                    with self.assertRaises(OSError):
                        os.fstat(descriptors[0])
                    self.assertEqual((bundle / 'binary').read_bytes(), raw[:-1] if short else raw)


if __name__ == '__main__':
    unittest.main()
