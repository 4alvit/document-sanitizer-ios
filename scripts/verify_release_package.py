#!/usr/bin/env python3
"""Reject release metadata in a RedactLeaf simulator .app or ZIP (stdlib only).

Public API: scan_package(path) -> JSON-serializable report with an ``ok`` bool.
The scanner never extracts archives, executes binaries, or changes their bytes.
It inspects both required executables, including every universal Mach-O slice.
Reports contain categories/counts/offsets, never matched developer path strings.

This is a metadata gate, not a replacement for code signing, identity verification,
or runtime tests. The accepted executable format is 64-bit x86_64/arm64 Mach-O
MH_EXECUTE with an iOS Simulator LC_BUILD_VERSION and LC_MAIN entry point.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import struct
import unicodedata
import zipfile
import zlib
from xml.parsers.expat import ExpatError


MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_SLICES = 32
MAX_SYMBOLS = 1000000
EXTENSION = "PlugIns/CleanSendShare.appex"
ROLES = (("app", "", "APPL"), ("share_extension", EXTENSION, "XPC!"))
ARCHITECTURES = {0x01000007: "x86_64", 0x0100000C: "arm64"}
FAT_FORMATS = {b"\xca\xfe\xba\xbe": (">", False),
               b"\xbe\xba\xfe\xca": ("<", False),
               b"\xca\xfe\xba\xbf": (">", True),
               b"\xbf\xba\xfe\xca": ("<", True)}
THIN_FORMATS = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}
PROFILE_MARKERS = (b"__llvm_prf", b"__llvm_cov", b"__llvm_profile", b"default.profraw", b"__LLVM_COV")
# Apple strip reserves symbol index zero to avoid an indirect-symbol index bug.
# This exact N_OPT entry is bookkeeping, not embedded source/debug information.
# https://github.com/apple-oss-distributions/cctools/blob/e0d56624eca2a76c2ace4c21850df9e666de4ca5/misc/strip.c#L4250
STRIP_SENTINEL = b"radr://5614542\0"
# Deliberately narrow roots; /System/Library, /usr/lib, @rpath, app containers,
# /private/var/mobile and /var/mobile remain valid runtime locations.
DEVELOPER_ROOTS = (
    ("user_home", rb"/(?:Users|home|root)/"),
    ("windows_user_home", rb"[A-Za-z]:[\\/]Users[\\/]"),
    ("xcode_installation", rb"/Applications/[^/\x00\r\n]{1,200}\.app/Contents/Developer/"),
    ("developer_tools", rb"/Library/Developer/"),
    ("build_workspace", rb"/(?:builds|workspace|workspaces|__w)/"),
    ("developer_temporary", rb"/(?:private/)?(?:tmp|var/folders)/"),
    ("package_manager_build", rb"/(?:opt/homebrew|usr/local)/(?:Cellar|Homebrew)/"),
)


class InspectionError(Exception):
    """Carries only a stable category, never a filesystem exception string."""


def finding(code, **detail):
    return {"code": code, **detail}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def valid_name(name):
    return isinstance(name, str) and bool(name) and name not in (".", "..") and not any(
        c in name for c in ("/", "\\", "\0", ":"))


def safe_member(name):
    if not name or name.startswith("/") or "\\" in name or "\0" in name or ":" in name:
        return False
    parts = name.rstrip("/").split("/")
    return all(part and part not in (".", "..") for part in parts)


def read_bounded(stream):
    data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise InspectionError("file_size_limit")
    return data


class DirectoryReader:
    """All opens are relative to pinned directory descriptors with NOFOLLOW."""

    def __init__(self, path, findings):
        self.findings = findings
        self.root = path.name
        self.names = set()
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.total = 0
        self.entries = 0
        try:
            self._index(self.fd, "")
        except BaseException:
            os.close(self.fd)
            raise

    def _index(self, fd, prefix):
        if prefix.count("/") > 64:
            raise InspectionError("directory_depth_limit")
        with os.scandir(fd) as entries:
            for entry in entries:
                self.entries += 1
                if self.entries > MAX_ENTRIES:
                    raise InspectionError("entry_count_limit")
                relative = prefix + entry.name
                mode = entry.stat(follow_symlinks=False).st_mode
                if not safe_member(relative):
                    self.findings.append(finding("unsafe_member_name"))
                elif stat.S_ISLNK(mode):
                    self.findings.append(finding("symlink_not_allowed"))
                elif stat.S_ISDIR(mode):
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        self._index(child, relative + "/")
                    finally:
                        os.close(child)
                elif stat.S_ISREG(mode):
                    size = entry.stat(follow_symlinks=False).st_size
                    self.total += size
                    if size > MAX_FILE_BYTES or self.total > MAX_TOTAL_BYTES:
                        raise InspectionError("package_size_limit")
                    self.names.add(relative)
                else:
                    self.findings.append(finding("special_file_not_allowed"))

    def read(self, relative):
        if relative not in self.names or not safe_member(relative):
            raise InspectionError("required_file_missing_or_unsafe")
        current = os.dup(self.fd)
        try:
            parts = relative.split("/")
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                os.close(current)
                current = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise InspectionError("required_file_not_regular")
                return read_bounded(stream)
        except OSError:
            raise InspectionError("required_file_unreadable_or_unsafe") from None
        finally:
            os.close(current)

    def close(self):
        os.close(self.fd)


class ZipReader:
    """Reject ambiguous/unsafe entries; read bytes directly, never extract."""

    def __init__(self, path, findings):
        self.findings = findings
        self.stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb")
        self.archive = None
        try:
            if os.fstat(self.stream.fileno()).st_size > MAX_TOTAL_BYTES:
                raise InspectionError("archive_size_limit")
            self.archive = zipfile.ZipFile(self.stream)
            self._index()
        except BaseException:
            self.close()
            raise

    def _index(self):
        entries = self.archive.infolist()
        if len(entries) > MAX_ENTRIES or sum(x.file_size for x in entries) > MAX_TOTAL_BYTES:
            raise InspectionError("archive_resource_limit")
        self.members = {}
        aliases = {}
        blocked = set()
        roots = set()
        for entry in entries:
            name = entry.orig_filename
            if not safe_member(name) or entry.filename != name:
                self.findings.append(finding("unsafe_zip_member"))
                continue
            key = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
            if key in aliases:
                self.findings.append(finding("duplicate_or_aliased_zip_member"))
                blocked.add(aliases[key])
                blocked.add(name)
            aliases[key] = name
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if stat.S_ISLNK(mode):
                self.findings.append(finding("symlink_not_allowed"))
                blocked.add(name)
            elif kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                self.findings.append(finding("special_file_not_allowed"))
                blocked.add(name)
            elif (kind == stat.S_IFDIR) != entry.is_dir() and kind != 0:
                self.findings.append(finding("zip_entry_type_mismatch"))
                blocked.add(name)
            if entry.flag_bits & 1 or entry.file_size > MAX_FILE_BYTES:
                self.findings.append(finding("encrypted_or_oversized_zip_member"))
                blocked.add(name)
            roots.add(name.split("/")[0])
            self.members[name] = entry
        for name in self.members:
            for i in range(1, len(name.rstrip("/").split("/"))):
                parent = "/".join(name.split("/")[:i])
                if parent in self.members:
                    self.findings.append(finding("zip_file_parent_collision"))
                    blocked.add(name)
        apps = sorted(x for x in roots if x.endswith(".app"))
        if len(apps) != 1:
            raise InspectionError("one_top_level_app_required")
        self.root = apps[0]
        if roots != {self.root}:
            self.findings.append(finding("unexpected_zip_root"))
        self.members = {k: v for k, v in self.members.items() if k not in blocked and not v.is_dir()}
        self.names = {name[len(self.root) + 1:] for name in self.members if name.startswith(self.root + "/")}
        # Check every readable entry's decompression/CRC under the package limits.
        for name in list(self.members):
            try:
                self._read(name)
            except InspectionError as error:
                self.findings.append(finding(str(error)))
                self.members.pop(name)

    def _read(self, name):
        try:
            with self.archive.open(self.members[name]) as stream:
                return read_bounded(stream)
        except (KeyError, OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile, EOFError, zlib.error):
            raise InspectionError("zip_member_unreadable_or_corrupt") from None

    def read(self, relative):
        if not safe_member(relative):
            raise InspectionError("required_file_missing_or_unsafe")
        return self._read(self.root + "/" + relative)

    def close(self):
        if self.archive is not None:
            self.archive.close()
        self.stream.close()


def metadata_findings(data):
    """Counts include overlapping encodings; byte offsets are buffer-relative."""
    result = []
    for marker in PROFILE_MARKERS:
        for encoding in ("ascii", "utf-16-le", "utf-16-be"):
            count = data.count(marker.decode().encode(encoding))
            if count:
                result.append(finding("llvm_profile_or_coverage", marker=marker.decode(), encoding=encoding, count=count))
    for category, pattern in DEVELOPER_ROOTS:
        count, offsets = 0, []
        for match in re.finditer(pattern, data):
            count += 1
            if len(offsets) < 8:
                offsets.append(match.start())
        if count:
            result.append(finding("local_developer_path", category=category,
                                  count=count, offsets=offsets))
    # UTF-16 strings can carry the same leaked paths. Decode aligned and unaligned
    # text for both byte orders; report no content from the decoded strings.
    for encoding in ("utf-16-le", "utf-16-be"):
        for alignment in (0, 1):
            if not any(marker in data for marker in (b"\0/", b"/\0", b"\0\\", b"\\\0")):
                break
            text = data[alignment:].decode(encoding, errors="replace")
            for category, pattern in DEVELOPER_ROOTS:
                count = sum(1 for _ in re.finditer(pattern.decode(), text))
                if count:
                    result.append(finding("local_developer_path", category=category, encoding=encoding,
                                          alignment=alignment, count=count))
    return result


def within(offset, size, total):
    return 0 <= offset <= total and 0 <= size <= total - offset


def inspect_slice(data, offset, expected_cpu=None, expected_subtype=None):
    result = {"offset": offset, "size": len(data), "findings": metadata_findings(data)}
    problems = result["findings"]
    endian = THIN_FORMATS.get(data[:4])
    if endian is None or len(data) < 32:
        problems.append(finding("unknown_or_truncated_mach_o"))
        result["ok"] = False
        return result
    _, cpu, subtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from(endian + "8I", data)
    result.update(architecture=ARCHITECTURES.get(cpu, "unsupported"), cpu_type=cpu,
                  cpu_subtype=subtype, file_type=filetype)
    if cpu not in ARCHITECTURES or endian != "<":
        problems.append(finding("unsupported_simulator_architecture"))
    if expected_cpu is not None and (cpu != expected_cpu or subtype != expected_subtype):
        problems.append(finding("fat_slice_header_disagreement"))
    if filetype != 2:
        problems.append(finding("not_a_mach_o_executable"))
    if reserved or not ncmds or ncmds > sizeofcmds // 8 or not within(32, sizeofcmds, len(data)):
        problems.append(finding("invalid_load_command_table"))
        result["ok"] = False
        return result
    pos, end = 32, 32 + sizeofcmds
    platforms, code_ranges, entrypoints, symtabs = [], [], [], []
    text_section = False
    try:
        for _ in range(ncmds):
            if not within(pos, 8, end):
                raise InspectionError("truncated_load_command")
            cmd, size = struct.unpack_from(endian + "II", data, pos)
            if size < 8 or size % 8 or not within(pos, size, end):
                raise InspectionError("invalid_load_command_size")
            if cmd == 0x19:  # LC_SEGMENT_64
                if size < 72:
                    raise InspectionError("truncated_segment")
                segname = data[pos + 8:pos + 24].split(b"\0")[0]
                fileoff, filesize = struct.unpack_from(endian + "QQ", data, pos + 40)
                initprot, nsects = struct.unpack_from(endian + "II", data, pos + 60)
                if size != 72 + 80 * nsects or not within(fileoff, filesize, len(data)):
                    raise InspectionError("invalid_segment_extent")
                if segname == b"__DWARF":
                    problems.append(finding("embedded_dwarf_segment"))
                for i in range(nsects):
                    section = pos + 72 + i * 80
                    name = data[section:section + 16].split(b"\0")[0]
                    section_segment = data[section + 16:section + 32].split(b"\0")[0]
                    section_size = struct.unpack_from(endian + "Q", data, section + 40)[0]
                    section_offset = struct.unpack_from(endian + "I", data, section + 48)[0]
                    section_flags = struct.unpack_from(endian + "I", data, section + 64)[0]
                    if section_segment != segname:
                        raise InspectionError("section_segment_disagreement")
                    if name.startswith((b"__debug_", b"__zdebug_")):
                        problems.append(finding("embedded_dwarf_section"))
                    if section_flags & 0xFF not in (1, 0xC, 0x12) and section_size:
                        if not within(section_offset, section_size, len(data)) or not (
                                fileoff <= section_offset and section_offset + section_size <= fileoff + filesize):
                            raise InspectionError("invalid_section_extent")
                    if (segname == b"__TEXT" and name == b"__text" and section_size and
                            initprot & 4 and section_flags & 0xFF == 0):
                        text_section = True
                        code_ranges.append((section_offset, section_size))
                    # App-extension LC_MAIN may point to the dyld entry stub.
                    if (segname == b"__TEXT" and section_size and initprot & 4 and
                            section_flags & 0xFF == 8 and section_flags & 0x80000400):
                        code_ranges.append((section_offset, section_size))
            elif cmd == 0x32:  # LC_BUILD_VERSION
                if size < 24:
                    raise InspectionError("truncated_build_version")
                platform, _, _, ntools = struct.unpack_from(endian + "4I", data, pos + 8)
                if size != 24 + 8 * ntools:
                    raise InspectionError("invalid_build_version")
                platforms.append(platform)
            elif cmd == 0x80000028:  # LC_MAIN
                if size != 24:
                    raise InspectionError("invalid_entrypoint_command")
                entrypoints.append(struct.unpack_from(endian + "Q", data, pos + 8)[0])
            elif cmd == 2:  # LC_SYMTAB / nlist_64
                if size != 24:
                    raise InspectionError("invalid_symbol_table_command")
                symtabs.append(struct.unpack_from(endian + "4I", data, pos + 8))
            pos += size
        if pos != end:
            raise InspectionError("load_command_size_disagreement")
        if len(symtabs) > 1:
            raise InspectionError("duplicate_symbol_table")
        for symoff, nsyms, stroff, strsize in symtabs:
            if nsyms > MAX_SYMBOLS or not within(symoff, nsyms * 16, len(data)) or not within(stroff, strsize, len(data)):
                raise InspectionError("invalid_symbol_table_extent")
            # String index zero means "no name"; ld may store a space there.
            if nsyms and (not strsize or data[stroff + strsize - 1] != 0):
                raise InspectionError("invalid_symbol_string_table")
            stabs = []
            for i in range(nsyms):
                entry = symoff + 16 * i
                strx, kind, sect, desc, value = struct.unpack_from(endian + "IBBHQ", data, entry)
                if strx and strx >= strsize:
                    raise InspectionError("invalid_symbol_string")
                if kind & 0xE0:  # N_STAB includes N_SO and N_OSO.
                    if (i == 0 and (kind, sect, desc, value) == (0x3C, 0, 0, 0x05614542)
                            and strx and strx + len(STRIP_SENTINEL) <= strsize
                            and data[stroff + strx:stroff + strx + len(STRIP_SENTINEL)] == STRIP_SENTINEL):
                        result.setdefault("allowed_toolchain_markers", []).append({
                            "code": "apple_strip_indirect_symbol_sentinel", "name": "radr://5614542",
                            "symbol_index": i, "symbol_offset": entry, "n_type": kind,
                            "n_sect": sect, "n_desc": desc, "n_value": value,
                        })
                    else:
                        stabs.append(entry)
            if stabs:
                problems.append(finding("embedded_stabs", count=len(stabs), offsets=stabs[:8]))
    except InspectionError as error:
        problems.append(finding(str(error)))
    if platforms != [7]:
        problems.append(finding("ios_simulator_build_version_required"))
    if not text_section:
        problems.append(finding("executable_text_section_required"))
    if len(entrypoints) != 1 or not any(start <= entrypoints[0] < start + size
                                      for start, size in code_ranges):
        problems.append(finding("invalid_or_missing_entrypoint"))
    result["ok"] = not problems
    return result


def inspect_binary(data):
    data = bytes(data)
    report = {"sha256": sha256(data), "size": len(data), "findings": metadata_findings(data), "slices": []}
    fat = FAT_FORMATS.get(data[:4])
    if fat is None:
        report["format"] = "mach-o" if data[:4] in THIN_FORMATS else "unknown"
        report["slices"].append(inspect_slice(data, 0))
    else:
        report["format"] = "universal-mach-o"
        endian, wide = fat
        row_size = 32 if wide else 20
        if len(data) < 8:
            report["findings"].append(finding("truncated_fat_header"))
        else:
            count = struct.unpack_from(endian + "I", data, 4)[0]
            if not 1 <= count <= MAX_SLICES or not within(8, count * row_size, len(data)):
                report["findings"].append(finding("invalid_fat_architecture_table"))
            else:
                extents, architectures = [], set()
                for i in range(count):
                    values = struct.unpack_from(endian + ("IIQQII" if wide else "IIIII"), data, 8 + row_size * i)
                    cpu, subtype, offset, size, align = values[:5]
                    bad = (not size or offset < 8 + count * row_size or align > 31 or
                           offset % (1 << min(align, 31)) or not within(offset, size, len(data)) or
                           (wide and values[5] != 0))
                    if bad:
                        report["slices"].append({"offset": offset, "size": size, "ok": False,
                                                  "findings": [finding("invalid_fat_slice_extent")]})
                        continue
                    if any(offset < end and start < offset + size for start, end in extents):
                        report["findings"].append(finding("overlapping_fat_slices"))
                    if (cpu, subtype) in architectures:
                        report["findings"].append(finding("duplicate_fat_architecture"))
                    architectures.add((cpu, subtype))
                    extents.append((offset, offset + size))
                    report["slices"].append(inspect_slice(data[offset:offset + size], offset, cpu, subtype))
    report["ok"] = not report["findings"] and bool(report["slices"]) and all(x["ok"] for x in report["slices"])
    return report


def inspect_bundle(reader, role, relative, package_type):
    bundle = reader.root + ("/" + relative if relative else "")
    report = {"role": role, "bundle": bundle, "ok": False, "findings": [], "slices": []}
    prefix = relative + "/" if relative else ""
    try:
        raw = reader.read(prefix + "Info.plist")
        if len(raw) > 1024 * 1024:
            raise InspectionError("bundle_info_size_limit")
        try:
            info = plistlib.loads(raw)
        except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError, RecursionError, ExpatError):
            raise InspectionError("invalid_bundle_info_plist") from None
        if not isinstance(info, dict) or not valid_name(info.get("CFBundleExecutable")):
            raise InspectionError("invalid_bundle_executable_name")
        if (info.get("CFBundlePackageType") != package_type or
                info.get("CFBundleSupportedPlatforms") != ["iPhoneSimulator"] or
                not isinstance(info.get("CFBundleIdentifier"), str) or not info["CFBundleIdentifier"]):
            raise InspectionError("invalid_simulator_bundle_metadata")
        if role == "share_extension" and (not isinstance(info.get("NSExtension"), dict) or
                info["NSExtension"].get("NSExtensionPointIdentifier") != "com.apple.share-services"):
            raise InspectionError("share_extension_point_required")
        executable = prefix + info["CFBundleExecutable"]
        report["executable"] = reader.root + "/" + executable
        report.update(inspect_binary(reader.read(executable)))
    except InspectionError as error:
        report["findings"].append(finding(str(error)))
    return report


def scan_package(path):
    """Return all package/app/extension findings; malformed input never passes."""
    path = Path(path)
    report = {"schema_version": 1, "input": path.name, "ok": False, "findings": [], "binaries": []}
    reader = None
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise InspectionError("symlink_input_not_allowed")
        if stat.S_ISDIR(mode) and path.name.endswith(".app"):
            report["container"] = "app"
            reader = DirectoryReader(path, report["findings"])
        elif stat.S_ISREG(mode) and path.suffix.lower() == ".zip":
            report["container"] = "zip"
            reader = ZipReader(path, report["findings"])
        else:
            raise InspectionError("unsupported_package_format")
        for role, relative, package_type in ROLES:
            report["binaries"].append(inspect_bundle(reader, role, relative, package_type))
    except InspectionError as error:
        report["findings"].append(finding(str(error)))
    except (OSError, ValueError, zipfile.BadZipFile, EOFError):
        report["findings"].append(finding("package_unreadable_or_corrupt"))
    finally:
        if reader is not None:
            reader.close()
    present = {x["role"] for x in report["binaries"]}
    for role, relative, _ in ROLES:
        if role not in present:
            report["binaries"].append({"role": role, "bundle": relative or ".", "ok": False,
                                       "findings": [finding("package_unavailable_for_inspection")], "slices": []})
    report["ok"] = not report["findings"] and all(x["ok"] for x in report["binaries"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--json", type=Path, dest="output", help="Also write the full JSON report to this path")
    args = parser.parse_args(argv)
    report = scan_package(args.package)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    print(serialized, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
