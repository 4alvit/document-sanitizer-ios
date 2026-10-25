"""Narrow metadata-gate tests. All fixtures are inert synthetic Mach-O bytes."""

import contextlib
import io
import json
from pathlib import Path
import plistlib
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import verify_release_package as scanner


def thin(*, cpu=0x01000007, payload=b"", section=b"__text", segment=b"__TEXT",
         symbol_type=None, symbol_name=b"fixture", symbol_sect=1, symbol_desc=0,
         symbol_value=0, symbol_index=0, platform=7, entry_in_stub=False):
    """Enough valid load commands for inspection, never executed or installed."""
    sizecmds = 152 + (80 if entry_in_stub else 0) + 24 + 24 + (24 if symbol_type is not None else 0)
    code_offset = 32 + sizecmds
    code = b"\xc3" + payload + (b"\xc3" if entry_in_stub else b"")
    symbol_offset = code_offset + len(code)
    symbol = (struct.pack("<IBBHQ", 1, 0x0F, 1, 0, 0) * symbol_index
              + struct.pack("<IBBHQ", 1, symbol_type, symbol_sect, symbol_desc, symbol_value)
              if symbol_type is not None else b"")
    strings = b"\0" + symbol_name + b"\0" if symbol_type is not None else b""
    length = symbol_offset + len(symbol) + len(strings)
    header = struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 4 if symbol else 3, sizecmds, 0, 0)
    seg = struct.pack("<II16sQQQQIIII", 0x19, 232 if entry_in_stub else 152, segment, 0x100000000, 4096,
                      0, length, 7, 5, 2 if entry_in_stub else 1, 0)
    sec = struct.pack("<16s16sQQIIIIIIII", section, segment, 0x100000000 + code_offset,
                      len(code) - (1 if entry_in_stub else 0), code_offset, 0, 0, 0, 0, 0, 0, 0)
    if entry_in_stub:
        sec += struct.pack("<16s16sQQIIIIIIII", b"__stubs", segment, 0x100000000 + symbol_offset - 1,
                           1, symbol_offset - 1, 0, 0, 0, 0x80000408, 0, 0, 0)
    version = struct.pack("<6I", 0x32, 24, platform, 0x110000, 0x110000, 0)
    main = struct.pack("<IIQQ", 0x80000028, 24, symbol_offset - 1 if entry_in_stub else code_offset, 0)
    symtab = struct.pack("<6I", 2, 24, symbol_offset, symbol_index + 1,
                         symbol_offset + len(symbol), len(strings)) if symbol else b""
    return header + seg + sec + version + main + symtab + code + symbol + strings


def fat(parts, *, endian=">", wide=False):
    row_size = 32 if wide else 20
    cursor = (8 + row_size * len(parts) + 7) & ~7
    rows, content = [], bytearray(cursor)
    for data in parts:
        cpu, subtype = struct.unpack_from("<II", data, 4)
        row = (cpu, subtype, cursor, len(data), 3)
        rows.append(struct.pack(endian + ("IIQQII" if wide else "IIIII"), *(row + (0,) if wide else row)))
        content.extend(data)
        content.extend(b"\0" * ((-len(content)) % 8))
        cursor = len(content)
    header = struct.pack(endian + "II", 0xCAFEBABF if wide else 0xCAFEBABE, len(parts)) + b"".join(rows)
    content[:len(header)] = header
    return bytes(content)


def bundle_files(main=None, extension=None):
    result = {}
    for root, executable, kind, binary in [
        ("", "CleanSend", "APPL", thin() if main is None else main),
        ("PlugIns/CleanSendShare.appex/", "CleanSendShare", "XPC!", thin() if extension is None else extension),
    ]:
        info = {"CFBundleExecutable": executable, "CFBundlePackageType": kind,
                "CFBundleIdentifier": "io.example." + executable,
                "CFBundleSupportedPlatforms": ["iPhoneSimulator"]}
        if kind == "XPC!":
            info["NSExtension"] = {"NSExtensionPointIdentifier": "com.apple.share-services"}
        result[root + "Info.plist"] = plistlib.dumps(info)
        result[root + executable] = binary
    return result


def all_codes(report):
    codes = []
    if isinstance(report, dict):
        if "code" in report:
            codes.append(report["code"])
        for value in report.values():
            codes.extend(all_codes(value))
    elif isinstance(report, list):
        for value in report:
            codes.extend(all_codes(value))
    return codes


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="redactleaf-metadata-tests-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def app(self, files=None):
        app = self.root / "CleanSend.app"
        for relative, data in (bundle_files() if files is None else files).items():
            path = app / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return app

    def archive(self, files=None, extras=()):
        path = self.root / "simulator.zip"
        with warnings.catch_warnings(), zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, data in (bundle_files() if files is None else files).items():
                archive.writestr("CleanSend.app/" + name, data)
            for name, data in extras:
                archive.writestr(name, data)
        return path

    def assertRejected(self, result, code):
        self.assertFalse(result["ok"], result)
        self.assertIn(code, all_codes(result), result)

    def test_clean_app_and_zip_preserve_runtime_paths(self):
        paths = (b"/System/Library/Frameworks/UIKit.framework/UIKit\0/usr/lib/libSystem.B.dylib\0"
                 b"@rpath/libswiftCore.dylib\0@executable_path/Frameworks\0"
                 b"/private/var/mobile/Containers/Data/Application\0/var/mobile/Library\0")
        files = bundle_files(thin(payload=paths, symbol_type=0x0F), thin(cpu=0x0100000C))
        for package in (self.app(files), self.archive(files)):
            with self.subTest(package=package.suffix):
                report = scanner.scan_package(package)
                self.assertTrue(report["ok"], report)
                self.assertEqual([x["role"] for x in report["binaries"]], ["app", "share_extension"])
                self.assertNotIn(str(self.root), json.dumps(report))

    def test_all_universal_encodings_and_every_slice(self):
        for endian in ("<", ">"):
            for wide in (False, True):
                data = fat([thin(), thin(cpu=0x0100000C)], endian=endian, wide=wide)
                report = scanner.inspect_binary(data)
                self.assertTrue(report["ok"], report)
                self.assertEqual([s["architecture"] for s in report["slices"]], ["x86_64", "arm64"])
        data = fat([thin(), thin(cpu=0x0100000C, payload=b"default.profraw")])
        report = scanner.inspect_binary(data)
        self.assertFalse(report["ok"])
        self.assertTrue(report["slices"][0]["ok"])
        self.assertRejected(report["slices"][1], "llvm_profile_or_coverage")

    def test_valid_linker_string_table_and_extension_entry_stub(self):
        data = bytearray(thin(symbol_type=0x0F, entry_in_stub=True))
        data[-len(b"\0fixture\0")] = 32
        result = scanner.inspect_binary(data)
        self.assertTrue(result["ok"], result)

    def test_both_bad_binaries_are_reported(self):
        report = scanner.scan_package(self.archive(bundle_files(
            thin(payload=b"/Users/FIXTURE_ONLY/project/source.swift"),
            thin(payload=b"__llvm_profile_runtime"))))
        self.assertEqual(len(report["binaries"]), 2)
        self.assertRejected(report["binaries"][0], "local_developer_path")
        self.assertRejected(report["binaries"][1], "llvm_profile_or_coverage")
        self.assertNotIn("FIXTURE_ONLY", json.dumps(report))

    def test_profile_markers_and_developer_roots(self):
        for marker in scanner.PROFILE_MARKERS:
            for encoding in ("ascii", "utf-16-le", "utf-16-be"):
                with self.subTest(marker=marker, encoding=encoding):
                    self.assertRejected(scanner.inspect_binary(thin(payload=marker.decode().encode(encoding))),
                                        "llvm_profile_or_coverage")
        for path in ["/Users/FIXTURE/repo/a.swift", "/home/FIXTURE/repo/a.swift", "/root/repo/a.swift",
                     r"C:\Users\FIXTURE\repo\a.swift", "/Applications/Xcode.app/Contents/Developer/SDKs",
                     "/Library/Developer/Xcode/DerivedData", "/private/var/folders/aa/FIXTURE",
                     "/tmp/FIXTURE/object.o", "/builds/FIXTURE/object.o", "/workspace/FIXTURE/object.o",
                     "/opt/homebrew/Cellar/tool/1/include.h"]:
            for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
                with self.subTest(path=path, encoding=encoding):
                    result = scanner.inspect_binary(thin(payload=path.encode(encoding)))
                    self.assertRejected(result, "local_developer_path")
                    self.assertNotIn("FIXTURE", json.dumps(result))

    def test_dwarf_and_stabs_are_structurally_detected(self):
        for data, code in [(thin(segment=b"__DWARF"), "embedded_dwarf_segment"),
                           (thin(section=b"__debug_info"), "embedded_dwarf_section"),
                           (thin(section=b"__zdebug_info"), "embedded_dwarf_section"),
                           (thin(symbol_type=0x64), "embedded_stabs"),
                           (thin(symbol_type=0x66), "embedded_stabs")]:
            self.assertRejected(scanner.inspect_binary(data), code)

    def test_exact_apple_strip_sentinel_is_reported_not_rejected(self):
        params = dict(symbol_type=0x3C, symbol_name=b"radr://5614542", symbol_sect=0,
                      symbol_desc=0, symbol_value=0x05614542)
        report = scanner.scan_package(self.archive(bundle_files(
            fat([thin(**params), thin(cpu=0x0100000C, **params)]), thin(**params))))
        self.assertTrue(report["ok"], report)
        for binary in report["binaries"]:
            for part in binary["slices"]:
                self.assertEqual(part["findings"], [])
                markers = part["allowed_toolchain_markers"]
                self.assertEqual(len(markers), 1)
                self.assertEqual(markers[0]["name"], "radr://5614542")
                self.assertEqual(markers[0]["symbol_index"], 0)
                self.assertEqual(markers[0]["n_type"], 0x3C)
                self.assertEqual(markers[0]["n_value"], 0x05614542)

    def test_apple_strip_sentinel_near_misses_are_rejected(self):
        params = dict(symbol_type=0x3C, symbol_name=b"radr://5614542", symbol_sect=0,
                      symbol_desc=0, symbol_value=0x05614542)
        for change in [dict(symbol_type=0x32), dict(symbol_type=0x3D), dict(symbol_type=0x64),
                       dict(symbol_sect=1), dict(symbol_desc=1), dict(symbol_value=0),
                       dict(symbol_name=b"radr://5614543"), dict(symbol_name=b"xradr://5614542"),
                       dict(symbol_name=b"radr://5614542suffix"), dict(symbol_index=1)]:
            with self.subTest(change=change):
                report = scanner.inspect_binary(thin(**(params | change)))
                self.assertRejected(report, "embedded_stabs")
                self.assertNotIn("allowed_toolchain_markers", report["slices"][0])

    def test_apple_strip_sentinel_does_not_hide_other_metadata(self):
        params = dict(symbol_type=0x3C, symbol_name=b"radr://5614542", symbol_sect=0,
                      symbol_desc=0, symbol_value=0x05614542)
        for change, code in [(dict(payload=b"/Users/FIXTURE/project.swift"), "local_developer_path"),
                             (dict(payload=b"__llvm_prf_data"), "llvm_profile_or_coverage"),
                             (dict(section=b"__debug_info"), "embedded_dwarf_section")]:
            with self.subTest(code=code):
                report = scanner.inspect_binary(thin(**(params | change)))
                self.assertRejected(report, code)
                self.assertEqual(len(report["slices"][0]["allowed_toolchain_markers"]), 1)

    def test_unknown_truncated_or_non_simulator_binary_cannot_pass(self):
        cases = [(b"", "unknown_or_truncated_mach_o"), (b"\x7fELF" + b"\0" * 100, "unknown_or_truncated_mach_o"),
                 (thin()[:36], "invalid_load_command_table"),
                 (thin(cpu=7), "unsupported_simulator_architecture"),
                 (thin(platform=2), "ios_simulator_build_version_required")]
        for data, code in cases:
            self.assertRejected(scanner.inspect_binary(data), code)
        invalid = bytearray(thin())
        struct.pack_into("<I", invalid, 12, 6)  # dylib, not an executable
        self.assertRejected(scanner.inspect_binary(invalid), "not_a_mach_o_executable")

    def test_every_truncation_is_rejected_without_parser_exception(self):
        for data in (thin(symbol_type=0x0F), fat([thin(), thin(cpu=0x0100000C)])):
            for length in range(len(data)):
                # A fat wrapper may legitimately have optional trailing alignment.
                if data[:4] in scanner.FAT_FORMATS and length >= len(data) - 7:
                    continue
                with self.subTest(length=length, total=len(data)):
                    self.assertFalse(scanner.inspect_binary(data[:length])["ok"])

    def test_invalid_load_commands_sections_and_symbols_fail_closed(self):
        cases = []
        bad = bytearray(thin()); struct.pack_into("<I", bad, 36, 0); cases.append((bad, "invalid_load_command_size"))
        bad = bytearray(thin()); struct.pack_into("<Q", bad, 80, len(bad) + 10); cases.append((bad, "invalid_segment_extent"))
        bad = bytearray(thin()); struct.pack_into("<I", bad, 152, len(bad) + 1); cases.append((bad, "invalid_section_extent"))
        bad = bytearray(thin()); struct.pack_into("<Q", bad, 216, 0); cases.append((bad, "invalid_or_missing_entrypoint"))
        bad = bytearray(thin(symbol_type=0x0F)); struct.pack_into("<I", bad, 240, len(bad) + 1); cases.append((bad, "invalid_symbol_table_extent"))
        for data, code in cases:
            self.assertRejected(scanner.inspect_binary(data), code)

    def test_invalid_fat_tables_do_not_hide_other_slices(self):
        self.assertRejected(scanner.inspect_binary(struct.pack(">II", 0xCAFEBABE, 0)), "invalid_fat_architecture_table")
        original = fat([thin(), thin(cpu=0x0100000C, payload=b"default.profraw")])
        bad = bytearray(original); struct.pack_into(">I", bad, 16, 0xFFFFFFFF)
        report = scanner.inspect_binary(bad)
        self.assertRejected(report, "invalid_fat_slice_extent")
        self.assertEqual(len(report["slices"]), 2)
        self.assertRejected(report["slices"][1], "llvm_profile_or_coverage")
        bad = bytearray(original); struct.pack_into(">I", bad, 28, 0x01000007)
        self.assertRejected(scanner.inspect_binary(bad), "fat_slice_header_disagreement")
        duplicate = fat([thin(), thin()])
        self.assertRejected(scanner.inspect_binary(duplicate), "duplicate_fat_architecture")
        bad = bytearray(original); struct.pack_into(">I", bad, 36, struct.unpack_from(">I", bad, 16)[0])
        self.assertRejected(scanner.inspect_binary(bad), "overlapping_fat_slices")

    def test_missing_invalid_bundle_and_missing_executable_still_report_both(self):
        for mode in ("missing_plist", "malformed_plist", "missing_executable", "unsafe_executable"):
            files = bundle_files(extension=thin(payload=b"__llvm_covmap"))
            if mode == "missing_plist":
                del files["Info.plist"]
            elif mode == "malformed_plist":
                files["Info.plist"] = b"<?xml version='1.0'?><plist><dict>"
            elif mode == "missing_executable":
                del files["CleanSend"]
            else:
                metadata = plistlib.loads(files["Info.plist"])
                metadata["CFBundleExecutable"] = "../outside"
                files["Info.plist"] = plistlib.dumps(metadata)
            with self.subTest(mode=mode):
                report = scanner.scan_package(self.archive(files))
                self.assertFalse(report["binaries"][0]["ok"])
                self.assertRejected(report["binaries"][1], "llvm_profile_or_coverage")

    def test_directory_symlinks_are_never_followed(self):
        outside = self.root / "outside"
        outside.write_bytes(thin())
        app = self.app()
        (app / "CleanSend").unlink()
        (app / "CleanSend").symlink_to(outside)
        report = scanner.scan_package(app)
        self.assertRejected(report, "symlink_not_allowed")
        self.assertNotIn("sha256", report["binaries"][0])
        self.assertTrue(report["binaries"][1]["ok"])
        alias = self.root / "Alias.app"; alias.symlink_to(app, target_is_directory=True)
        self.assertRejected(scanner.scan_package(alias), "symlink_input_not_allowed")

    def test_zip_symlink_unsafe_paths_and_aliases_are_rejected(self):
        for member in ("../outside", "/tmp/outside", "CleanSend.app/../outside",
                       "CleanSend.app\\outside", "C:/outside", "CleanSend.app/./outside"):
            with self.subTest(member=member):
                report = scanner.scan_package(self.archive(extras=[(member, b"nothing")]))
                self.assertRejected(report, "unsafe_zip_member")
                self.assertTrue(all(x["ok"] for x in report["binaries"]))
        link = zipfile.ZipInfo("CleanSend.app/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assertRejected(scanner.scan_package(self.archive(extras=[(link, b"../../outside")])), "symlink_not_allowed")
        for name in ("CleanSend.app/Info.plist", "CleanSend.app/INFO.PLIST"):
            self.assertRejected(scanner.scan_package(self.archive(extras=[(name, b"invalid")])),
                                "duplicate_or_aliased_zip_member")
        self.assertRejected(scanner.scan_package(self.archive(extras=[("CleanSend.app/PlugIns", b"file")])),
                            "zip_file_parent_collision")

    def test_valid_appledouble_entries_do_not_replace_executable(self):
        archive = self.archive(extras=[("CleanSend.app/._CleanSend", b"synthetic transport metadata")])
        self.assertTrue(scanner.scan_package(archive)["ok"])
        files = bundle_files(); del files["CleanSend"]
        report = scanner.scan_package(self.archive(files, extras=[("CleanSend.app/._CleanSend", thin())]))
        self.assertFalse(report["ok"])
        self.assertFalse(report["binaries"][0]["ok"])

    def test_corrupt_zip_resources_and_unknown_packages_fail_closed(self):
        path = self.archive(extras=[("CleanSend.app/resource.bin", b"CRC_FIXTURE_UNIQUE")])
        data = path.read_bytes().replace(b"CRC_FIXTURE_UNIQUE", b"CRC_FIXTURE_BROKEN")
        path.write_bytes(data)
        self.assertRejected(scanner.scan_package(path), "zip_member_unreadable_or_corrupt")
        path.write_bytes(b"not a ZIP")
        self.assertRejected(scanner.scan_package(path), "package_unreadable_or_corrupt")
        for path in (self.root / "missing.app", self.root):
            report = scanner.scan_package(path)
            self.assertFalse(report["ok"])
            self.assertEqual(len(report["binaries"]), 2)

    def test_size_limit_and_cli_json_exit_status(self):
        archive = self.archive()
        with mock.patch.object(scanner, "MAX_FILE_BYTES", 100):
            self.assertFalse(scanner.scan_package(archive)["ok"])
        output = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(scanner.main([str(archive), "--json", str(output)]), 0)
            self.assertTrue(json.loads(output.read_text())["ok"])
            self.assertEqual(scanner.main([str(self.root / "missing.zip"), "--json", str(output)]), 1)
            self.assertFalse(json.loads(output.read_text())["ok"])


if __name__ == "__main__":
    unittest.main()
