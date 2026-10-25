#!/usr/bin/env python3
"""Validate authored en/ru resources and explicit lookup coverage without a simulator."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ENTRY = re.compile(r'^("(?:\\.|[^"\\])*")\s*=\s*("(?:\\.|[^"\\])*");$', re.MULTILINE)
LOOKUP = re.compile(r'\b(?:CoreL10n|L10n)\.(text|format|count)\(("(?:\\.|[^"\\])*")')
TOKEN = re.compile(r'%(?:[1-9][0-9]*\$)?@')


def entries(path):
    data = {}
    for match in ENTRY.finditer(path.read_text()):
        key, value = map(json.loads, match.groups())
        assert key not in data, f'Duplicate key {key}: {path}'
        assert value, f'Empty translation {key}: {path}'
        data[key] = value
    assert data, f'No entries: {path}'
    return data


def check():
    report = {}
    for scope in ['App', 'ShareExtension', 'Sources/SanitizerCore']:
        root = ROOT / scope
        resources = root / 'Resources'
        catalogs = {lang: entries(resources / (lang + '.lproj') / 'Localizable.strings') for lang in ['en', 'ru']}
        assert catalogs['en'].keys() == catalogs['ru'].keys(), f'Missing en/ru keys: {scope}'
        for key in catalogs['en']:
            assert len(TOKEN.findall(catalogs['en'][key])) == len(TOKEN.findall(catalogs['ru'][key])), f'Placeholder mismatch: {key}'
        references = set()
        counts = set()
        for path in root.rglob('*.swift'):
            for match in LOOKUP.finditer(path.read_text()):
                kind, key = match[1], json.loads(match[2])
                if kind == 'count':
                    counts.add(key)
                    for category in ['one', 'few', 'many', 'other']:
                        references.add(key + '.' + category)
                else:
                    references.add(key)
        if scope == 'App':
            # Raw source keys intentionally remain stable for accessibility IDs.
            references.update(['Left', 'Top', 'Width', 'Height'])
            source = (root / 'ContentView.swift').read_text()
            for m in re.finditer(r'feature\("[123]", ("(?:\\.|[^"\\])*"), ("(?:\\.|[^"\\])*")\)', source):
                references.update(map(json.loads, m.groups()))
        missing = references - catalogs['en'].keys()
        assert not missing, f'Missing resources in {scope}: {sorted(missing)}'
        for key in counts:
            for catalog in catalogs.values():
                for category in ['one', 'few', 'many', 'other']:
                    assert len(TOKEN.findall(catalog[key + '.' + category])) == 1, f'Count must have one formatted number: {key}'
        report[scope] = {'keys_per_language': len(catalogs['en']), 'looked_up_keys': len(references), 'plural_families': sorted(counts), 'missing': []}
    print(json.dumps({'status': 'pass', 'languages': ['en', 'ru'], 'scopes': report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    check()
