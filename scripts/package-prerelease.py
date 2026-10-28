#!/usr/bin/env python3
"""Build a reproducible-input source/simulator preview, never an App Store IPA."""
import argparse
import datetime
import hashlib
import json
import plistlib
import re
import os
import stat
from pathlib import Path
import subprocess
import tempfile
import zipfile

from verify_release_package import scan_package

ROOT = Path(__file__).resolve().parent.parent


def command(*args, capture=False):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def require_clean():
    if command('git', 'status', '--porcelain', capture=True).strip():
        raise SystemExit('Commit all source changes before packaging a preview.')


def require_revision(revision):
    require_clean()
    if command('git', 'rev-parse', 'HEAD', capture=True).strip() != revision:
        raise SystemExit('Source commit changed during packaging; rerun from the final commit.')


def collect_provenance(revision):
    """Bind the checked-out tree to its published head and hosted run, when present."""
    assert re.fullmatch(r'[0-9a-f]{40}', revision), 'Invalid source revision'
    tree = command('git', 'rev-parse', revision + '^{tree}', capture=True).strip()
    parents = command('git', 'show', '-s', '--format=%P', revision, capture=True).split()
    assert re.fullmatch(r'[0-9a-f]{40}', tree), 'Invalid source tree'
    result = {'checkout_commit': revision, 'source_tree': tree,
              'checkout_parents': parents, 'published_head': None,
              'published_head_tree': None, 'checkout_tree_matches_published_head': None, 'github': None}
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        expected = os.environ.get('EXPECTED_HEAD_SHA', '')
        assert re.fullmatch(r'[0-9a-f]{40}', expected), 'Hosted packaging requires EXPECTED_HEAD_SHA'
        assert os.environ.get('GITHUB_SHA') == revision, 'Checkout differs from GitHub run commit'
        event = os.environ.get('GITHUB_EVENT_NAME')
        assert event in ('pull_request', 'push'), 'Unsupported packaging event'
        expected_tree = command('git', 'rev-parse', expected + '^{tree}', capture=True).strip()
        assert re.fullmatch(r'[0-9a-f]{40}', expected_tree), 'Invalid published head tree'
        if event == 'push':
            assert revision == expected, 'Push checkout differs from published head'
            assert tree == expected_tree, 'Push checkout tree differs from published head'
        else:
            assert revision == expected or expected in parents, 'PR checkout does not contain published head'
        repository = os.environ.get('GITHUB_REPOSITORY', '')
        ref = os.environ.get('GITHUB_REF', '')
        server = os.environ.get('GITHUB_SERVER_URL', '')
        run_id = os.environ.get('GITHUB_RUN_ID', '')
        attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
        assert re.fullmatch(r'[^/\s]+/[^/\s]+', repository) and ref
        assert server.startswith('https://') and not server.endswith('/')
        assert run_id.isdecimal() and int(run_id) > 0
        assert attempt.isdecimal() and int(attempt) > 0
        result.update(published_head=expected, published_head_tree=expected_tree,
                      checkout_tree_matches_published_head=(tree == expected_tree),
                      github={'repository': repository, 'event': event, 'ref': ref,
                              'run_id': run_id, 'run_attempt': attempt,
                              'run_url': f'{server}/{repository}/actions/runs/{run_id}'})
    return result


def inspect_bundle_paths(app):
    """Require real bundle roots and executable files before and after extraction."""
    assert app.name == 'CleanSend.app' and app.is_dir() and not app.is_symlink(), 'Invalid app root'
    for bundle in (app, app / 'PlugIns/CleanSendShare.appex'):
        assert bundle.is_dir() and not bundle.is_symlink(), 'Invalid bundle root'
        assert bundle.stat().st_mode & stat.S_IXUSR, 'Bundle root is not traversable'
        info = plistlib.loads((bundle / 'Info.plist').read_bytes())
        name = info['CFBundleExecutable']
        assert isinstance(name, str) and name not in ('', '.', '..') and Path(name).name == name
        executable = bundle / name
        assert executable.is_file() and not executable.is_symlink(), 'Invalid bundle executable'
        assert executable.stat().st_mode & stat.S_IXUSR, 'Bundle executable lost its execute mode'


def build_simulator(derived, *, signed):
    signing = ['CODE_SIGNING_ALLOWED=YES', 'CODE_SIGN_IDENTITY=-', 'DEVELOPMENT_TEAM='] if signed else ['CODE_SIGNING_ALLOWED=NO']
    command('xcodebuild', '-project', 'CleanSend.xcodeproj', '-scheme', 'CleanSend',
            '-configuration', 'Release', '-sdk', 'iphonesimulator',
            '-destination', 'generic/platform=iOS Simulator', '-derivedDataPath', derived,
            'ENABLE_CODE_COVERAGE=NO', 'CLANG_COVERAGE_MAPPING=NO',
            'CLANG_COVERAGE_MAPPING_LINKER_ARGS=NO',
            *signing, 'build')
    return derived / 'Build/Products/Release-iphonesimulator/CleanSend.app'


def inspect_release_metadata(path, stage):
    report = scan_package(path)
    evidence = ROOT / '.qa' / f'release-scan-{stage}.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2) + '\n')
    if not report['ok']:
        raise SystemExit('Release package metadata check failed:\n' + json.dumps(report, indent=2))
    return report


def inspect_identity(app, version):
    inspect_bundle_paths(app)
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    extension = app / 'PlugIns/CleanSendShare.appex'
    extension_info = plistlib.loads((extension / 'Info.plist').read_bytes())
    for bundle, data, identifier in [(app, info, 'io.github.4alvit.cleansend'),
                                      (extension, extension_info, 'io.github.4alvit.cleansend.share')]:
        assert data['CFBundleIdentifier'] == identifier
        assert data['CFBundleDisplayName'] == 'RedactLeaf'
        assert data['CFBundleSupportedPlatforms'] == ['iPhoneSimulator']
        assert data['CFBundleShortVersionString'] == version
        assert data['CFBundleVersion'] == info['CFBundleVersion']
    assert (app / 'PrivacyInfo.xcprivacy').is_file()
    assert not list(app.rglob('*.storekit')), 'Test StoreKit configuration in production app'
    assert not list(app.rglob('*.xctest')), 'Test bundle in production app'
    assert not list(app.rglob('*.debug.dylib')), 'Debug executable in Release app'
    return info


def inspect_signature(bundle, entitlement_path):
    # Xcode's simulator link step embeds runtime entitlements in Mach-O sections.
    # A plain codesign over an unsigned build cannot create those sections.
    command('codesign', '--verify', '--strict', '--all-architectures', bundle)
    details = subprocess.run(['codesign', '--display', '--verbose=4', str(bundle)],
                             check=True, text=True, capture_output=True).stderr
    assert 'Signature=adhoc' in details and 'Authority=' not in details
    assert 'TeamIdentifier=not set' in details
    info = plistlib.loads((bundle / 'Info.plist').read_bytes())
    expected = plistlib.loads(entitlement_path.read_bytes())
    executable = bundle / info['CFBundleExecutable']
    architectures = command('lipo', '-archs', executable, capture=True).split()
    report = {'signing': 'Local ad-hoc; no certificate or developer team', 'architectures': {}}
    with tempfile.TemporaryDirectory(prefix='redactleaf-signature-') as directory:
        for arch in architectures:
            thin = executable
            if len(architectures) > 1:
                thin = Path(directory) / arch
                command('lipo', executable, '-thin', arch, '-output', thin)
            load_commands = command('otool', '-l', thin, capture=True)
            sections = {}
            for name in ['__entitlements', '__ents_der']:
                match = re.search(r'sectname ' + name + r'\s+segname __TEXT\s+addr \S+\s+size (0x[0-9a-fA-F]+)\s+offset (\d+)', load_commands)
                assert match, f'Missing simulator {name} for {arch}: {bundle.name}'
                size, offset = int(match[1], 16), int(match[2])
                raw = thin.read_bytes()[offset:offset + size]
                assert len(raw) == size and size > 0
                sections[name] = raw
            simulated = plistlib.loads(sections['__entitlements'].rstrip(b'\0'))
            der_xml = subprocess.run(['derq', 'query', '-i', '-', '--xml'],
                                     input=sections['__ents_der'], check=True,
                                     stdout=subprocess.PIPE).stdout
            assert plistlib.loads(der_xml) == simulated, 'Simulator XML/DER entitlements disagree'
            assert simulated['com.apple.security.application-groups'] == expected['com.apple.security.application-groups']
            assert simulated['application-identifier'].endswith('.' + info['CFBundleIdentifier'])
            assert not simulated.get('get-task-allow', False)
            signature_xml = command('codesign', '--display', '--architecture', arch, '--entitlements', '-', '--xml', bundle, capture=True)
            signature_entitlements = plistlib.loads(signature_xml.encode()) if signature_xml.strip() else {}
            assert not signature_entitlements.get('get-task-allow', False)
            report['architectures'][arch] = {
                'simulator_entitlements': simulated,
                'code_signature_entitlements': signature_entitlements,
                'simulator_der_matches_xml': True,
                'simulator_der_sha256': hashlib.sha256(sections['__ents_der']).hexdigest(),
            }
    return report


def payload_hashes(app):
    inspect_bundle_paths(app)
    result = {}
    for path in [app, *sorted(app.rglob('*'))]:
        name = str(path.relative_to(app))
        mode = path.lstat().st_mode
        assert not stat.S_ISLNK(mode), 'Symlink in Release payload'
        entry = {'mode': f'{stat.S_IMODE(mode):04o}'}
        if stat.S_ISDIR(mode):
            entry['directory'] = True
        else:
            assert stat.S_ISREG(mode), 'Unsupported Release payload file type'
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        result[name] = entry
    return result


def main():
    if not __debug__:
        raise SystemExit('Run without Python optimization: packaging assertions must remain enabled.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / '.qa/releases')
    parser.add_argument('--version', default='0.1.0', help='Expected app and extension marketing version')
    args = parser.parse_args()
    require_clean()
    revision = command('git', 'rev-parse', 'HEAD', capture=True).strip()
    provenance = collect_provenance(revision)
    # Build the committed project. Regeneration is an authoring step and can
    # change a local package's navigator name with the checkout directory.
    app = build_simulator(ROOT / '.qa/release-build', signed=False)
    require_revision(revision)
    info = inspect_identity(app, args.version)
    metadata_scans = {'unsigned_app': inspect_release_metadata(app, 'unsigned-app')}
    signed_app = build_simulator(ROOT / '.qa/release-adhoc-build', signed=True)
    require_revision(revision)
    signed_info = inspect_identity(signed_app, args.version)
    assert signed_info == info
    metadata_scans['adhoc_app'] = inspect_release_metadata(signed_app, 'adhoc-app')
    signatures = {
        'app': inspect_signature(signed_app, ROOT / 'App/CleanSend.entitlements'),
        'extension': inspect_signature(signed_app / 'PlugIns/CleanSendShare.appex', ROOT / 'ShareExtension/CleanSendShare.entitlements'),
    }
    version = info['CFBundleShortVersionString']
    destination = args.destination.resolve() / f'RedactLeaf-{version}-{revision[:12]}'
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / 'RedactLeaf-source.zip'
    binary = destination / 'RedactLeaf-unsigned-simulator.zip'
    signed_binary = destination / 'RedactLeaf-adhoc-simulator.zip'
    command('git', 'archive', '--format=zip', '--prefix=RedactLeaf-source/', '-o', source, revision)
    command('ditto', '-c', '-k', '--keepParent', app, binary)
    command('ditto', '-c', '-k', '--keepParent', signed_app, signed_binary)
    metadata_scans['unsigned_zip'] = inspect_release_metadata(binary, 'unsigned-zip')
    metadata_scans['adhoc_zip'] = inspect_release_metadata(signed_binary, 'adhoc-zip')
    for path in [source, binary, signed_binary]:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert all(not n.endswith(('.p8', '.p12', '.mobileprovision')) for n in archive.namelist())
    with tempfile.TemporaryDirectory(prefix='redactleaf-archive-') as directory:
        for archive, original in [(binary, app), (signed_binary, signed_app)]:
            extracted = Path(directory) / archive.stem
            command('ditto', '-x', '-k', archive, extracted)
            unpacked_app = extracted / 'CleanSend.app'
            inspect_identity(unpacked_app, version)
            assert payload_hashes(unpacked_app) == payload_hashes(original), 'ZIP changed the app payload'
            if archive == signed_binary:
                for bundle in [unpacked_app, unpacked_app / 'PlugIns/CleanSendShare.appex']:
                    command('codesign', '--verify', '--strict', '--all-architectures', bundle)
    metadata = {
        'product': 'RedactLeaf', 'version': version, 'build': info['CFBundleVersion'],
        'source_commit': revision, 'source_tree': provenance['source_tree'],
        'provenance': provenance,
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'xcode': command('xcodebuild', '-version', capture=True).strip(),
        'platform': 'iPhoneSimulator', 'configuration': 'Release',
        'host_architecture': os.uname().machine,
        'app_store_release': False, 'signing': 'Separate code-signing-disabled and local ad-hoc variants; iOS Simulator only',
        'artifacts': {
            binary.name: {'signing': 'Disabled', 'app_group': 'Unavailable'},
            signed_binary.name: {'signing': 'Local ad-hoc, no Apple certificate or team',
                                 'app_group': 'Simulator entitlements embedded by Xcode',
                                 'signatures': signatures},
        },
        'app_group_note': 'Use RedactLeaf-adhoc-simulator.zip for the shared App Group. Runtime extension smoke is recorded separately; packaging alone does not prove runtime behavior.',
        'tests_note': 'Packaging checks archives and identity; separate QA evidence records executed tests.'
    }
    manifest = destination / 'preview-build.json'
    manifest.write_text(json.dumps(metadata, indent=2) + '\n')
    payload_manifest = destination / 'payload-sha256.json'
    payload_manifest.write_text(json.dumps({binary.name: payload_hashes(app),
                                          signed_binary.name: payload_hashes(signed_app)}, indent=2) + '\n')
    scan_manifest = destination / 'release-binary-scan.json'
    scan_manifest.write_text(json.dumps(metadata_scans, indent=2) + '\n')
    readme = destination / 'PREVIEW-README.txt'
    readme.write_text(
        f'RedactLeaf {version} development preview\n'
        f'Source checkout commit: {revision}\n'
        f"Source tree: {provenance['source_tree']}\n"
        f"Published head: {provenance['published_head'] or 'Not bound to a hosted run'}\n"
        f"Published head tree: {provenance['published_head_tree'] or 'Not bound to a hosted run'}\n"
        f"Checkout tree matches published head: {provenance['checkout_tree_matches_published_head']}\n"
        'All archives use the source checkout commit above.\n\n'
        'These are two Release iOS Simulator variants, not an iPhone IPA,\n'
        'TestFlight build, App Store release, or proof of payment acceptance.\n'
        'RedactLeaf-adhoc-simulator.zip: local ad-hoc signature and App Group.\n'
        'RedactLeaf-unsigned-simulator.zip: code signing disabled at build;\n'
        'no App Group runtime entitlements. The linker can still emit a\n'
        'minimal ad-hoc signature for an architecture in this variant.\n'
        'Local ad-hoc signing uses no Apple certificate, developer team or\n'
        'provisioning profile. It is not Apple Ad Hoc device distribution.\n'
        'Read docs/RELEASE.md and docs/STOREKIT-TESTING.md in the source archive.\n\n'
        'To inspect the source, extract RedactLeaf-source.zip.\n'
        'To run the preview, use a Mac with Xcode and a compatible iOS Simulator:\n'
        '1. Extract RedactLeaf-adhoc-simulator.zip into a separate directory.\n'
        '2. Create or choose a simulator in Xcode and start it.\n'
        '3. Find its explicit device UUID with: xcrun simctl list devices\n'
        '4. Install: xcrun simctl install DEVICE_UUID /path/to/CleanSend.app\n'
        '5. Launch: xcrun simctl launch DEVICE_UUID io.github.4alvit.cleansend\n\n'
        'Use the labelled synthetic sample to inspect editing and export.\n'
        'For Share Extension, export a synthetic sample and select RedactLeaf\n'
        'in the share sheet (under More if needed), then Save and Done. Return\n'
        'to the workspace and Import or Discard the queued batch. No rebuild\n'
        'is needed for the ad-hoc ZIP. See docs/UI-SHARE-QA.md for limits.\n'
        'The unsigned variant is retained separately for basic launch review.\n'
        'Both variants have the same bundle ID: install only one at a time.\n\n'
        'This Release preview contains no local StoreKit configuration. A live\n'
        'Pro offer is not configured or verified; do not sign in to test it.\n\n'
        'Check file integrity in this directory: shasum -a 256 -c SHA256SUMS\n'
    )
    (destination / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
        for p in [source, binary, signed_binary, manifest, payload_manifest, scan_manifest, readme]))
    require_revision(revision)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        output = Path(os.environ['GITHUB_OUTPUT'])
        assert '\n' not in str(destination) and '\r' not in str(destination)
        with output.open('a') as stream:
            stream.write(f'package_directory={destination}\n')
    print(json.dumps({'status': 'packaged', 'directory': str(destination), **metadata}, indent=2))


if __name__ == '__main__':
    main()
