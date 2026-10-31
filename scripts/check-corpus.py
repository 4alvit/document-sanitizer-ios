#!/usr/bin/env python3
"""Independent Poppler/Pillow geometry checks against the native export CLI.

All inputs are generated here from synthetic data. No output proves that OCR
finds every private field; the checks verify explicit masks and containers.
"""
import argparse
import datetime
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from PIL import ExifTags, Image, ImageChops, ImageDraw, ImageOps, ImageStat
from pypdf import PdfReader
import pypdf
import PIL
from verify_export import verify_export

ROOT = Path(__file__).resolve().parent.parent
MASK = (.12, .18, .37, .29)


def run(*command):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True, text=True)


def mean_difference(left, right):
    if left.size != right.size:
        raise AssertionError(f'geometry mismatch: {left.size} != {right.size}')
    return sum(ImageStat.Stat(ImageChops.difference(left.convert('RGB'), right.convert('RGB'))).mean) / 3


def reference(source, directory):
    if source.suffix == '.pdf':
        prefix = directory / source.stem
        run('pdftoppm', '-cropbox', '-r', '144', '-png', source, prefix)
        return [Image.open(path).convert('RGB') for path in sorted(directory.glob(source.stem + '-*.png'))]
    with Image.open(source) as image:
        upright = ImageOps.exif_transpose(image).convert('RGBA')
        white = Image.new('RGBA', upright.size, 'white')
        return [Image.alpha_composite(white, upright).convert('RGB')]


def container_checks(path, expected_pages):
    # Separate fail-closed structural verifier, itself tested with independent
    # hostile and positive fixtures by probe_export_verifier.py.
    verify_export(path)
    if path.suffix.lower() == '.pdf':
        reader = PdfReader(path)
        assert len(reader.pages) == expected_pages
        assert not reader.attachments
        root = reader.trailer['/Root']
        assert '/AcroForm' not in root and '/OpenAction' not in root and '/AA' not in root
        for page in reader.pages:
            assert not page.extract_text().strip(), 'text survived raster export'
            assert not page.get('/Annots'), 'annotations survived export'
            assert len(page.images) >= 1, 'page contains no raster image'
        assert 'SYNTHETIC_PERSON_42' not in str(reader.metadata)
        assert 'PRIVATE_SYNTHETIC_TITLE' not in str(reader.metadata)
    else:
        with Image.open(path) as image:
            # ImageIO may generate color-space/dimension EXIF even from a new
            # metadata-free bitmap. Permit only those exact technical values.
            exif = image.getexif()
            assert set(exif) <= {34665}, f'unexpected EXIF root tags: {set(exif)}'
            generated = exif.get_ifd(ExifTags.IFD.Exif) if exif else {}
            expected = {40961: 1, 40962: image.width, 40963: image.height}
            assert all(key in expected and value == expected[key] for key, value in generated.items()), f'unexpected EXIF: {generated}'
            assert 'A' not in image.getbands(), 'alpha channel survived'
            for key in ['Author', 'Comment', 'XML:com.adobe.xmp', 'xmp']:
                assert key not in image.info, f'metadata survived: {key}'


def check(args, evidence_context):
    directory = args.work.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    fixtures = directory / 'fixtures'
    refs = directory / 'reference'
    refs.mkdir(exist_ok=True)
    run(sys.executable, ROOT / 'scripts/generate-fixtures.py', fixtures)
    cli = args.cli.resolve() if args.cli else Path(run('swift', 'build', '--show-bin-path').stdout.strip()) / 'sanitizer-cli'
    evidence_context['cli_sha256'] = hashlib.sha256(cli.read_bytes()).hexdigest()
    evidence = []
    for source in sorted(fixtures.iterdir()):
        if source.name == 'not-a-pdf.pdf':
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        original_reference = reference(source, refs)
        baseline = None
        for label, rectangle in [('unmasked', None), ('masked', MASK)]:
            out = directory / source.stem / label
            for fmt in ['png', 'pdf', 'jpeg']:
                command = [cli, '--input', source, '--output', out / fmt, '--format', fmt]
                if rectangle:
                    command += ['--rect', ','.join(map(str, rectangle))]
                result = json.loads(run(*command).stdout)
                paths = list(map(Path, result['files']))
                for path in paths:
                    container_checks(path, len(original_reference))
                if fmt == 'png':
                    actual = [Image.open(path).convert('RGB') for path in paths]
                    if rectangle is None:
                        baseline = actual
                        for exported, expected in zip(actual, original_reference, strict=True):
                            delta = mean_difference(exported, expected)
                            assert delta < 7, f'{source.name}: independent renderer delta {delta:.2f}'
                    else:
                        for exported, base in zip(actual, baseline, strict=True):
                            expected = base.copy()
                            w, h = expected.size
                            x, y, rw, rh = rectangle
                            box = (math.floor(x*w), math.floor(y*h), math.ceil((x+rw)*w)-1, math.ceil((y+rh)*h)-1)
                            ImageDraw.Draw(expected).rectangle(box, fill='black')
                            delta = mean_difference(exported, expected)
                            assert delta < 1.5, f'{source.name}: mask geometry delta {delta:.2f}'
                            inner = exported.crop((box[0]+2, box[1]+2, box[2]-2, box[3]-2))
                            assert max(ImageStat.Stat(inner).mean) < 1, 'mask is not opaque black'
                    evidence.append({'fixture': source.name, 'variant': label, 'pages': len(actual), 'checks': 'Poppler source geometry, explicit mask, clean containers'})
                elif fmt == 'pdf':
                    # The embedded raster must match the reviewed PNG exactly;
                    # the separate renderer is allowed minor resampling at edges.
                    pdf_reader = PdfReader(paths[0])
                    # A second renderer observes what the receiver actually sees.
                    for index, expected in enumerate(actual, 1):
                        embedded = pdf_reader.pages[index-1].images
                        assert len(embedded) == 1
                        assert mean_difference(embedded[0].image, expected) == 0, 'PDF embedded raster differs from preview'
                        target = out / f'rendered-{index}'
                        run('pdftoppm', '-f', index, '-l', index, '-singlefile', '-scale-to-x', expected.width, '-scale-to-y', expected.height, '-png', paths[0], target)
                        with Image.open(target.with_suffix('.png')) as rendered:
                            delta = mean_difference(rendered, expected)
                            assert delta < 5, f'{source.name}: PDF/preview mismatch {delta:.2f}'
                elif fmt == 'jpeg':
                    for path, expected in zip(paths, actual, strict=True):
                        with Image.open(path) as rendered:
                            delta = mean_difference(rendered, expected)
                            assert delta < 5, f'{source.name}: JPEG/preview mismatch {delta:.2f}'
                            if rectangle:
                                x, y, rw, rh = rectangle
                                # Exclude only the lossy boundary; the hidden
                                # interior must still be visually opaque black.
                                inner = rendered.crop((math.floor(x*rendered.width)+3, math.floor(y*rendered.height)+3,
                                                       math.ceil((x+rw)*rendered.width)-3, math.ceil((y+rh)*rendered.height)-3))
                                assert max(ImageStat.Stat(inner.convert('RGB')).mean) < 3, 'JPEG mask interior is not black'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, 'source was modified'
    invalid_out = directory / 'invalid'
    failed = subprocess.run([str(cli), '--input', str(fixtures / 'not-a-pdf.pdf'), '--output', str(invalid_out)], capture_output=True)
    assert failed.returncode != 0, 'invalid PDF accepted'
    assert not invalid_out.exists() or not any(invalid_out.rglob('*')), 'invalid input left published output'
    report = {**evidence_context, 'status': 'passed', 'independent_tools': ['Poppler pdftoppm', 'pypdf', 'Pillow'], 'cases': evidence, 'limits': 'Synthetic corpus only; not an OCR-completeness or security certification.'}
    write_report(directory, report)
    print(json.dumps({'status': 'passed', 'cases': len(evidence), 'report': str(directory / 'report.json')}))


def write_report(directory, report):
    temporary = directory / 'report.json.tmp'
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(directory / 'report.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cli', type=Path, help='Defaults to the active Swift build directory')
    parser.add_argument('--work', type=Path, default=ROOT / '.qa/corpus')
    args = parser.parse_args()
    directory = args.work.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    context = {'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'python': sys.version.split()[0], 'pypdf': pypdf.__version__, 'Pillow': PIL.__version__}
    # Publish running before any external command: a failure must never leave a
    # stale passing report from another revision behind.
    write_report(directory, {**context, 'status': 'running'})
    try:
        try:
            context['commit'] = run('git', '-C', ROOT, 'rev-parse', 'HEAD').stdout.strip()
            context['worktree_dirty'] = bool(run('git', '-C', ROOT, 'status', '--porcelain').stdout.strip())
        except subprocess.CalledProcessError:
            context['commit'] = 'unavailable (source archive)'
            context['worktree_dirty'] = None
        context['Poppler'] = run('pdftoppm', '-v').stderr.splitlines()[0]
        check(args, context)
    except BaseException as error:
        write_report(directory, {**context, 'status': 'failed', 'error': f'{type(error).__name__}: {error}'})
        raise

