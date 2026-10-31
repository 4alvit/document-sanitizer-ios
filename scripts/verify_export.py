#!/usr/bin/env python3
"""Fail-closed container verifier for RedactLeaf's narrow raster output profile.

Usage: python3 scripts/verify_export.py FILE [FILE ...]
JSON is written to stdout; any rejected input produces exit status 1.
Requires the pinned pypdf and Pillow versions in requirements-qa.txt.

This is an independent QA parser, not an OCR/privacy-completeness guarantee.
PDFs must paint one opaque raster over each complete page. Unknown output
features are rejected, including unreferenced xref objects and incremental PDFs.

Allowed generated metadata: RedactLeaf creator, Quartz producer, valid full PDF
dates, random PDF document IDs; exact known sRGB ICC profile; ImageIO's canonical
ExifIFD containing only ColorSpace=1 and matching pixel dimensions; PNG sRGB=0;
JPEG JFIF 1.1 with no thumbnail and density 1 or 72; ImageIO's exact empty IPTC
record plus MD5(empty) APP13 record. No arbitrary IPTC/ICC/EXIF/XMP is allowed.
New OS encoder variants must be inspected before extending these allowlists.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import sys
import warnings
import zlib

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject, ByteStringObject, ContentStream, DictionaryObject,
    IndirectObject, NameObject, StreamObject, TextStringObject,
)

MAX_FILE = 256 * 1024 * 1024
MAX_PIXELS = 6_000_000
MAX_TOTAL_PIXELS = 24_000_000
MAX_OBJECTS = 10_000
SRGB_SHA256 = "2b3aa1645779a9e634744faf9b01e9102b0c9b88fd6deced7934df86b949af7e"
EMPTY_IPTC = (b"Photoshop 3.0\0" + b"8BIM\x04\x04\0\0\0\0\0\0" +
              b"8BIM\x04\x25\0\0\0\0\0\x10" + bytes.fromhex("d41d8cd98f00b204e9800998ecf8427e"))
LIMITS = [
    "Validates a narrow generated container profile, not whether all private pixels were covered.",
    "Does not replace independent rendering, mask-coordinate tests, or human preview.",
    "Rejects unsupported encoder variants; does not certify arbitrary PDF parser equivalence or resource exhaustion safety.",
    "Scans all indexed PDF objects; not a forensic proof about steganography or arbitrary unindexed bytes.",
]


class VerificationError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise VerificationError(reason)


def resolved(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def keys_only(value, allowed: set[str], description: str) -> None:
    require(isinstance(value, DictionaryObject), f"{description} is not a dictionary")
    require(set(value) <= allowed, f"Unsupported {description} keys: {sorted(set(value) - allowed)}")


def dimensions(width, height) -> tuple[int, int]:
    require(isinstance(width, int) and isinstance(height, int), "Non-integer raster dimensions")
    require(0 < width <= 2400 and 0 < height <= 2400 and width * height <= MAX_PIXELS,
            "Raster dimensions exceed the output profile")
    return width, height


def known_icc(data: bytes) -> None:
    require(len(data) == 3144 and hashlib.sha256(data).hexdigest() == SRGB_SHA256,
            "Unknown ICC profile; inspect it before changing the allowlist")


def technical_exif(data: bytes, size: tuple[int, int]) -> None:
    """Recognize only the complete two-IFD encoding emitted by ImageIO/Pillow.

    Checking all bytes, offsets, counts and padding also rejects appended hidden
    payloads that a high-level EXIF tag enumeration would otherwise overlook.
    """
    if data.startswith(b"Exif\0\0"):
        data = data[6:]
    require(len(data) == 68 and data[:2] in (b"MM", b"II"), "Noncanonical technical EXIF")
    order = ">" if data[:2] == b"MM" else "<"
    u16 = lambda n: struct.unpack_from(order + "H", data, n)[0]
    u32 = lambda n: struct.unpack_from(order + "I", data, n)[0]
    require(u16(2) == 42 and u32(4) == 8 and u16(8) == 1, "Unexpected EXIF root")
    require((u16(10), u16(12), u32(14), u32(18), u32(22)) == (34665, 4, 1, 26, 0),
            "EXIF root must contain only the generated ExifIFD pointer")
    require(u16(26) == 3 and u32(64) == 0, "Unexpected EXIF fields or next IFD")
    found = {}
    for offset in (28, 40, 52):
        tag, kind, count = u16(offset), u16(offset + 2), u32(offset + 4)
        require(kind in (3, 4) and count == 1 and tag not in found, "Unexpected EXIF field encoding")
        if kind == 3:
            require(data[offset + 10:offset + 12] == b"\0\0", "EXIF padding contains data")
            found[tag] = u16(offset + 8)
        else:
            found[tag] = u32(offset + 8)
    require(found == {40961: 1, 40962: size[0], 40963: size[1]},
            "EXIF must contain only sRGB and matching output dimensions")


def verify_png(data: bytes, size: tuple[int, int]) -> None:
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG signature")
    offset, seen, image_chunks = 8, set(), 0
    while offset < len(data):
        require(offset + 12 <= len(data), "Truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        require(end <= len(data), "Truncated PNG chunk payload")
        payload = data[offset + 8:end - 4]
        expected_crc = struct.unpack_from(">I", data, end - 4)[0]
        require(zlib.crc32(kind + payload) & 0xffffffff == expected_crc, "PNG CRC mismatch")
        require(kind in (b"IHDR", b"IDAT", b"IEND", b"sRGB", b"eXIf"),
                f"Unsupported PNG chunk {kind!r}")
        require(seen or kind == b"IHDR", "PNG header must be first")
        if kind != b"IDAT":
            require(kind not in seen, "Duplicate PNG structural/metadata chunk")
        if kind == b"IHDR":
            require(length == 13, "Invalid PNG header")
            w, h, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            require((w, h) == size and depth == 8 and color in (0, 2) and
                    compression == filtering == 0 and interlace in (0, 1), "Unsupported/transparent PNG raster")
        elif kind == b"sRGB":
            require(payload == b"\0", "Unexpected PNG rendering intent")
        elif kind == b"eXIf":
            technical_exif(payload, size)
        elif kind == b"IDAT":
            image_chunks += 1
        elif kind == b"IEND":
            require(length == 0 and end == len(data) and image_chunks > 0, "Invalid PNG end or trailing data")
        seen.add(kind)
        offset = end
    require(b"IEND" in seen and b"IHDR" in seen, "Incomplete PNG")


def verify_jpeg(data: bytes, size: tuple[int, int]) -> None:
    require(data[:2] == b"\xff\xd8", "Invalid JPEG signature")
    offset, scans, frames, seen = 2, 0, 0, set()
    icc = {}
    icc_count = 0
    while offset < len(data):
        require(data[offset] == 255, "Invalid JPEG marker boundary")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        require(offset < len(data), "Truncated JPEG marker")
        marker = data[offset]
        offset += 1
        if marker == 0xd9:
            require(offset == len(data) and frames == 1 and scans > 0, "Invalid JPEG end or trailing data")
            if icc:
                require(set(icc) == set(range(1, icc_count + 1)), "Incomplete ICC segments")
                known_icc(b"".join(icc[n] for n in range(1, icc_count + 1)))
            return
        require(offset + 2 <= len(data), "Truncated JPEG segment")
        length = struct.unpack_from(">H", data, offset)[0]
        require(length >= 2 and offset + length <= len(data), "Invalid JPEG segment length")
        payload = data[offset + 2:offset + length]
        offset += length
        if marker == 0xe0:
            require(marker not in seen and len(payload) == 14 and payload[:8] == b"JFIF\0\x01\x01\0" and
                    payload[8:12] in (b"\0\x01\0\x01", b"\0H\0H") and payload[12:] == b"\0\0",
                    "Unsupported JFIF fields or thumbnail")
        elif marker == 0xe1:
            require(marker not in seen and payload.startswith(b"Exif\0\0"), "Unexpected JPEG APP1/XMP")
            technical_exif(payload, size)
        elif marker == 0xe2:
            require(payload.startswith(b"ICC_PROFILE\0") and len(payload) >= 14, "Unexpected JPEG APP2")
            number, count = payload[12:14]
            require(1 <= number <= count <= 16 and number not in icc and icc_count in (0, count),
                    "Invalid ICC segment numbering")
            icc_count = count
            icc[number] = payload[14:]
        elif marker == 0xed:
            require(marker not in seen and payload == EMPTY_IPTC, "Nonempty or unknown JPEG IPTC/Photoshop metadata")
        else:
            require(marker in (0xc0, 0xc2, 0xc4, 0xdb, 0xdd, 0xda),
                    f"Unsupported JPEG marker 0x{marker:02x} (comments/unknown APP segments forbidden)")
        seen.add(marker)
        if marker in (0xc0, 0xc2):
            frames += 1
        if marker == 0xda:
            scans += 1
            # Entropy bytes use FF00 escaping and optional restart markers.
            # Resume segment validation at the next actual marker, even after SOS.
            while offset < len(data):
                next_ff = data.find(b"\xff", offset)
                require(next_ff >= 0 and next_ff + 1 < len(data), "Truncated JPEG entropy stream")
                following = data[next_ff + 1]
                if following == 0 or 0xd0 <= following <= 0xd7:
                    offset = next_ff + 2
                elif following == 255:
                    offset = next_ff + 1
                else:
                    offset = next_ff
                    break
    raise VerificationError("JPEG has no end marker")


def verify_image(data: bytes) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as candidate:
            require(candidate.format in ("PNG", "JPEG"), "Only PNG and JPEG output is supported")
            size = dimensions(*candidate.size)
            require(getattr(candidate, "n_frames", 1) == 1, "Animated/multiframe output")
            image_format = candidate.format
            candidate.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # Header/tag parsing alone does not establish decodability.
            require(image.mode in ("RGB", "L") and "transparency" not in image.info, "Raster is not opaque")
            if image_format == "PNG":
                verify_png(data, size)
            else:
                verify_jpeg(data, size)
    return {"format": image_format.lower(), "width": size[0], "height": size[1], "opaque": True}


def valid_pdf_date(value: str) -> bool:
    match = re.fullmatch(r"D:(\d{14})(Z(?:00'00')?|[+-]\d{2}'\d{2}')", value)
    if not match:
        return False
    try:
        dt.datetime.strptime(match[1], "%Y%m%d%H%M%S")
    except ValueError:
        return False
    return match[2].startswith("Z") or (int(match[2][1:3]) < 24 and int(match[2][4:6]) < 60)


def pdf_metadata(info) -> None:
    keys_only(info, {"/Creator", "/Producer", "/CreationDate", "/ModDate"}, "PDF information")
    for key, value in info.items():
        value = resolved(value)
        require(isinstance(value, TextStringObject), "Unexpected metadata value type")
        if key == "/Creator":
            require(value == "RedactLeaf", "Unknown PDF creator")
        elif key == "/Producer":
            require(value == "Quartz PDFContext" or re.fullmatch(
                r"(?:macOS|iOS|iPadOS) Version \d+(?:\.\d+){0,2} \(Build [A-Za-z0-9.]{1,32}\) Quartz PDFContext", value),
                "Unknown PDF producer")
        else:
            require(valid_pdf_date(value), "Invalid generated PDF date")


def matrix_product(left, right):
    a, b, c, d, e, f = left
    u, v, w, x, y, z = right
    return (a*u + c*v, b*u + d*v, a*w + c*x, b*w + d*x, a*y + c*z + e, b*y + d*z + f)


def verify_pdf(data: bytes) -> dict:
    require(re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", data) is not None, "Invalid PDF header")
    require(data.rstrip().endswith(b"%%EOF"), "Truncated PDF or trailing data")
    reader = PdfReader(io.BytesIO(data), strict=True)
    require(not reader.is_encrypted, "Encrypted output")
    keys_only(reader.trailer, {"/Size", "/Root", "/Info", "/ID"}, "PDF trailer (incremental files forbidden)")
    require(0 < len(reader.pages) <= 30, "PDF must contain 1–30 pages")
    if "/ID" in reader.trailer:
        identifier = reader.trailer["/ID"]
        require(isinstance(identifier, ArrayObject) and len(identifier) == 2 and
                all(len(v.original_bytes if isinstance(v, TextStringObject) else bytes(v)) == 16 for v in identifier),
                "Invalid generated PDF identifier")
    info = resolved(reader.trailer.get("/Info"))
    if info is not None:
        pdf_metadata(info)
    allowed_strings = {id(resolved(value)) for value in info.values()} if info is not None else set()
    allowed_strings.update(id(value) for value in reader.trailer.get("/ID", []))
    root = reader.trailer["/Root"]
    keys_only(root, {"/Type", "/Pages"}, "catalog")
    require(root.get("/Type") == "/Catalog", "Invalid PDF catalog")

    # Enumerate references from the trailer, then compare every xref entry.
    # Catalog-only checks would miss unreachable attachments or original streams.
    indexed = {(number, generation) for generation, objects in reader.xref.items()
               if generation != 65535 for number, offset in objects.items() if offset > 0}
    indexed.update((number, 0) for number in reader.xref_objStm)
    require(len(indexed) <= MAX_OBJECTS, "Too many indexed PDF objects")
    reachable, visited, graph, pending = set(), set(), [], [reader.trailer]
    while pending:
        value = pending.pop()
        if isinstance(value, IndirectObject):
            key = (value.idnum, value.generation)
            if key in reachable:
                continue
            reachable.add(key)
            value = value.get_object()
        if isinstance(value, (TextStringObject, ByteStringObject)):
            require(id(value) in allowed_strings, "Unexpected retained string data in PDF object graph")
        if isinstance(value, (DictionaryObject, ArrayObject)):
            if id(value) in visited:
                continue
            visited.add(id(value))
            graph.append(value)
            require(len(graph) <= MAX_OBJECTS * 4, "Oversized PDF object graph")
            pending.extend(value.values() if isinstance(value, DictionaryObject) else value)
    # Resolve even orphan entries in strict mode before rejecting them.
    for number, generation in indexed:
        reader.get_object(IndirectObject(number, generation, reader))
    require(indexed == reachable, "Unreferenced or missing indexed PDF objects")

    known_dictionaries = {id(reader.trailer), id(root)}
    if info is not None:
        known_dictionaries.add(id(info))
    pending_pages = [root["/Pages"]]
    seen_pages = set()
    while pending_pages:
        node = resolved(pending_pages.pop())
        require(id(node) not in seen_pages, "Cyclic/reused page tree")
        seen_pages.add(id(node))
        if node.get("/Type") == "/Pages":
            keys_only(node, {"/Type", "/Kids", "/Count", "/Parent", "/MediaBox", "/Resources"}, "page tree")
            require(isinstance(node.get("/Count"), int) and 0 < node["/Count"] <= 30, "Invalid page-tree count")
            known_dictionaries.add(id(node))
            pending_pages.extend(node["/Kids"])
        else:
            require(node.get("/Type") == "/Page", "Invalid page-tree child")

    streams = set()
    total_pixels = 0
    for page in reader.pages:
        keys_only(page, {"/Type", "/Parent", "/Resources", "/Contents", "/MediaBox", "/CropBox", "/Rotate"}, "page")
        known_dictionaries.add(id(page))
        # pypdf PageObject can wrap the original xref dictionary.
        if page.indirect_reference:
            known_dictionaries.add(id(page.indirect_reference.get_object()))
        box = tuple(float(v) for v in page.mediabox)
        require(len(box) == 4 and all(math.isfinite(v) for v in box) and
                box[0] == box[1] == 0 and 0 < box[2] <= 2400 and 0 < box[3] <= 2400, "Invalid output page box")
        require(page.get("/Rotate", 0) == 0 and tuple(map(float, page.cropbox)) == box,
                "Output page must have no hidden crop or rotation")
        resources = page["/Resources"]
        keys_only(resources, {"/ProcSet", "/XObject"}, "page resources")
        if "/ProcSet" in resources:
            require(isinstance(resources["/ProcSet"], ArrayObject) and
                    all(isinstance(v, NameObject) and v in ("/PDF", "/ImageB", "/ImageC", "/ImageI")
                        for v in resources["/ProcSet"]), "Unsupported resource procedure set")
        known_dictionaries.add(id(resources))
        images = resolved(resources.get("/XObject"))
        require(isinstance(images, DictionaryObject) and len(images) == 1, "Page must expose exactly one raster")
        known_dictionaries.add(id(images))
        image_name, image = next(iter(images.items()))
        image = resolved(image)
        require(isinstance(image, StreamObject), "Raster is not an image stream")
        keys_only(image, {"/Type", "/Subtype", "/Width", "/Height", "/BitsPerComponent", "/ColorSpace",
                          "/Filter", "/Interpolate", "/Length"}, "raster image")
        require(image.get("/Type") == "/XObject" and image.get("/Subtype") == "/Image", "Non-image XObject")
        size = dimensions(image.get("/Width"), image.get("/Height"))
        total_pixels += size[0] * size[1]
        require(total_pixels <= MAX_TOTAL_PIXELS, "PDF raster pixels exceed the output profile")
        require(image.get("/BitsPerComponent") == 8, "Unsupported raster bit depth")
        color = resolved(image.get("/ColorSpace"))
        channels = 3
        if isinstance(color, ArrayObject):
            require(len(color) == 2 and color[0] == "/ICCBased", "Unsupported PDF color space")
            profile = resolved(color[1])
            keys_only(profile, {"/N", "/Alternate", "/Filter", "/Length"}, "ICC profile")
            require(isinstance(profile, StreamObject) and profile.get("/N") == 3 and
                    profile.get("/Alternate") == "/DeviceRGB", "Unsupported ICC components")
            require(profile.get("/Filter") in (None, "/FlateDecode"), "Unsupported ICC compression")
            known_icc(profile.get_data())
            streams.add(id(profile))
        else:
            require(color in ("/DeviceRGB", "/DeviceGray"), "Unsupported raster color space")
            channels = 1 if color == "/DeviceGray" else 3
        require(image.get("/Filter") in (None, "/FlateDecode"), "Unsupported raster compression")
        require(len(image.get_data()) == size[0] * size[1] * channels, "Incomplete raster sample data")
        streams.add(id(image))

        contents = resolved(page.get("/Contents"))
        parts = list(contents) if isinstance(contents, ArrayObject) else [contents]
        for part in parts:
            part = resolved(part)
            require(isinstance(part, StreamObject), "Missing page content stream")
            keys_only(part, {"/Filter", "/Length"}, "page content")
            require(part.get("/Filter") in (None, "/FlateDecode"), "Unsupported content compression")
            raw = part.get_data()
            require(len(raw) <= 1_000_000 and b"%" not in raw, "Unexpected content comments or excessive stream size")
            streams.add(id(part))
        content = ContentStream(page.raw_get("/Contents"), reader)
        ctm, stack, painted = (1, 0, 0, 1, 0, 0), [], 0
        for operands, operator in content.operations:
            require(operator in (b"q", b"Q", b"cm", b"Do", b"ri"), f"Non-raster page operator {operator!r}")
            if operator == b"q":
                require(not operands and len(stack) < 100, "Invalid graphics-state push")
                stack.append(ctm)
            elif operator == b"Q":
                require(not operands and bool(stack), "Invalid graphics-state pop")
                ctm = stack.pop()
            elif operator == b"cm":
                require(len(operands) == 6, "Invalid raster transform")
                matrix = tuple(float(v) for v in operands)
                require(all(math.isfinite(v) for v in matrix), "Non-finite raster transform")
                ctm = matrix_product(ctm, matrix)
            elif operator == b"ri":
                require(len(operands) == 1 and operands[0] in ("/Perceptual", "/RelativeColorimetric", "/Saturation", "/AbsoluteColorimetric"),
                        "Unknown rendering intent")
            else:
                require(operands == [image_name], "Unknown painted image")
                expected = (box[2], 0, 0, box[3], 0, 0)
                require(all(math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-7) for a, b in zip(ctm, expected)),
                        "Raster does not cover the full page")
                painted += 1
        require(painted == 1 and not stack, "Each page must actually paint one full raster")
        require(not page.extract_text().strip(), "Extractable text remains")

    for item in graph:
        if isinstance(item, StreamObject):
            require(id(item) in streams, "Unexpected PDF stream")
        elif isinstance(item, DictionaryObject):
            require(id(item) in known_dictionaries, "Unexpected PDF dictionary")
    return {"format": "pdf", "pages": len(reader.pages), "indexed_objects_checked": len(indexed),
            "raster_pixels": total_pixels, "opaque": True}


def verify_export(path: Path | str) -> dict:
    path = Path(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_FILE, "Input is absent, empty or too large")
    data = path.read_bytes()
    require(len(data) <= MAX_FILE, "Input grew beyond the size limit")
    result = verify_pdf(data) if data.startswith(b"%PDF-") else verify_image(data)
    return {"ok": True, "file": path.name, "sha256": hashlib.sha256(data).hexdigest(), **result}


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Usage: verify_export.py FILE [FILE ...]", "limits": LIMITS}))
        return 1
    results = []
    for argument in sys.argv[1:]:
        try:
            results.append(verify_export(argument))
        except Exception as error:
            results.append({"ok": False, "file": Path(argument).name,
                            "error": f"{type(error).__name__}: {error}"})
    ok = all(result["ok"] for result in results)
    payload = results[0] if len(results) == 1 else {"ok": ok, "files": results}
    print(json.dumps({**payload, "limits": LIMITS}, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
