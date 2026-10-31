#!/usr/bin/env python3
"""Independent synthetic acceptance probe for the narrow raster export profile.

Usage: python3 scripts/probe_export_verifier.py scripts/verify_export.py
These fixtures were authored separately from the verifier implementation.
All files are generated temporarily; no personal documents are read.
Generated ImageIO EXIF is allowed only for matching dimensions and sRGB.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable

from PIL import Image, PngImagePlugin
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, NameObject,
    NumberObject, TextStringObject,
)


def name(value: str) -> NameObject:
    return NameObject(value)


def synthetic_image() -> Image.Image:
    image = Image.new("RGB", (24, 18), "white")
    for y in range(4, 14):
        for x in range(3, 21):
            image.putpixel((x, y), (x * 11 % 256, y * 13 % 256, 80))
    return image


def raster_pdf(pages: int = 1) -> PdfWriter:
    """Build fresh image-only PDF; in particular, do not inherit Pillow metadata."""
    writer = PdfWriter()
    writer.metadata = None
    image = synthetic_image()
    for _ in range(pages):
        page = writer.add_blank_page(width=24, height=18)
        raster = DecodedStreamObject()
        raster.set_data(image.tobytes())
        raster.update({
            name("/Type"): name("/XObject"), name("/Subtype"): name("/Image"),
            name("/Width"): NumberObject(24), name("/Height"): NumberObject(18),
            name("/ColorSpace"): name("/DeviceRGB"),
            name("/BitsPerComponent"): NumberObject(8),
        })
        page[name("/Resources")] = DictionaryObject({
            name("/XObject"): DictionaryObject({name("/Im0"): writer._add_object(raster)})
        })
        content = DecodedStreamObject()
        content.set_data(b"q 24 0 0 18 0 0 cm /Im0 Do Q\n")
        page[name("/Contents")] = writer._add_object(content)
    return writer


def set_content(writer: PdfWriter, data: bytes, page_index: int = 0) -> None:
    stream = DecodedStreamObject()
    stream.set_data(data)
    writer.pages[page_index][name("/Contents")] = writer._add_object(stream)


def add_text(writer: PdfWriter) -> None:
    font = DictionaryObject({name("/Type"): name("/Font"),
                             name("/Subtype"): name("/Type1"),
                             name("/BaseFont"): name("/Helvetica")})
    writer.pages[0]["/Resources"][name("/Font")] = DictionaryObject({
        name("/F1"): writer._add_object(font)
    })
    set_content(writer, b"q 24 0 0 18 0 0 cm /Im0 Do Q\n"
                        b"BT /F1 8 Tf 1 5 Td (SYNTHETIC ORIGINAL TEXT) Tj ET\n")


def add_annotation(writer: PdfWriter) -> None:
    annotation = DictionaryObject({name("/Type"): name("/Annot"),
        name("/Subtype"): name("/Text"),
        name("/Rect"): ArrayObject([NumberObject(v) for v in (0, 0, 10, 10)]),
        name("/Contents"): TextStringObject("SYNTHETIC annotation")})
    writer.pages[0][name("/Annots")] = ArrayObject([writer._add_object(annotation)])


def add_xmp(writer: PdfWriter) -> None:
    metadata = DecodedStreamObject()
    metadata.set_data(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><synthetic>source</synthetic></x:xmpmeta>')
    metadata.update({name("/Type"): name("/Metadata"), name("/Subtype"): name("/XML")})
    writer._root_object[name("/Metadata")] = writer._add_object(metadata)


def add_form(writer: PdfWriter) -> None:
    field = DictionaryObject({name("/FT"): name("/Tx"),
        name("/T"): TextStringObject("synthetic-field"),
        name("/V"): TextStringObject("SYNTHETIC original value")})
    writer._root_object[name("/AcroForm")] = writer._add_object(DictionaryObject({
        name("/Fields"): ArrayObject([writer._add_object(field)])
    }))


def add_page_action(writer: PdfWriter) -> None:
    action = DictionaryObject({name("/S"): name("/URI"),
                               name("/URI"): TextStringObject("https://example.invalid/synthetic")})
    writer.pages[0][name("/AA")] = DictionaryObject({name("/O"): writer._add_object(action)})


def add_orphan_filespec(writer: PdfWriter) -> None:
    # Kept in the xref/object table, but deliberately unreachable from the catalog.
    stream = DecodedStreamObject()
    stream.set_data(b"SYNTHETIC retained attachment")
    stream[name("/Type")] = name("/EmbeddedFile")
    writer._add_object(DictionaryObject({name("/Type"): name("/Filespec"),
        name("/F"): TextStringObject("synthetic.txt"),
        name("/EF"): DictionaryObject({name("/F"): writer._add_object(stream)})}))


def build_fixtures(root: Path) -> list[dict]:
    cases: list[dict] = []

    def record(label: str, path: Path, accept: bool, reason: str, advisory: bool = False) -> None:
        cases.append({"case": label, "path": str(path), "expect_accept": accept,
                      "reason": reason, "advisory": advisory})

    def pdf(label: str, accept: bool, reason: str,
            mutate: Callable[[PdfWriter], None] | None = None,
            pages: int = 1, advisory: bool = False) -> None:
        writer = raster_pdf(pages)
        if mutate:
            mutate(writer)
        path = root / f"{label}.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        record(label, path, accept, reason, advisory)

    pdf("valid_raster_pdf", True, "Fresh painted RGB image, no metadata or text")
    pdf("valid_multipage_pdf", True, "Every page paints an image", pages=2)
    pdf("valid_white_raster_pdf", True, "A genuinely painted flat white image remains valid",
        lambda w: w.pages[0]["/Resources"]["/XObject"]["/Im0"].set_data(
            Image.new("RGB", (24, 18), "white").tobytes()))
    pdf("pdf_extractable_text", False, "Painted image plus extractable original text", add_text)
    pdf("pdf_annotation", False, "Text annotation retains original content", add_annotation)
    pdf("pdf_embedded_file", False, "Catalog-linked embedded attachment",
        lambda w: w.add_attachment("synthetic.txt", b"SYNTHETIC original attachment"))
    pdf("pdf_javascript", False, "Document-level JavaScript name tree",
        lambda w: w.add_js("/* SYNTHETIC inert test */"))
    pdf("pdf_page_action", False, "Page additional action", add_page_action)
    pdf("pdf_acroform", False, "Form field retains an original value", add_form)
    pdf("pdf_source_metadata", False, "Original title/author/custom metadata",
        lambda w: w.add_metadata({"/Title": "SYNTHETIC original filename",
                                  "/Author": "SYNTHETIC source", "/Private": "secret fixture"}))
    pdf("pdf_xmp_metadata", False, "Document XMP metadata", add_xmp)
    pdf("pdf_unused_image_resource", False, "Image resource exists but is never painted",
        lambda w: set_content(w, b"q Q\n"))
    pdf("pdf_image_only_in_comment", False, "Comment mentions Do but does not paint an image",
        lambda w: set_content(w, b"% /Im0 Do\nq Q\n"))
    pdf("pdf_blank_second_page", False, "An image on page one does not validate a blank page two",
        lambda w: set_content(w, b"q Q\n", 1), pages=2)
    pdf("pdf_empty_document", False, "No pages", pages=0)
    pdf("pdf_orphan_filespec", False,
        "Unreachable Filespec/EmbeddedFile bytes retained in xref; stricter whole-file policy",
        add_orphan_filespec, advisory=True)

    for label, data in (("pdf_corrupt", b"%PDF-1.7\nnot a PDF\n"),
                        ("pdf_truncated", (root / "valid_raster_pdf.pdf").read_bytes()[:200])):
        path = root / f"{label}.pdf"
        path.write_bytes(data)
        record(label, path, False, "Malformed or truncated PDF")

    image = synthetic_image()
    for fmt, ext in (("PNG", "png"), ("JPEG", "jpg")):
        path = root / f"valid_raster_{ext}.{ext}"
        image.save(path, format=fmt)
        record(f"valid_raster_{ext}", path, True,
               "Fresh image; JPEG JFIF container information is not original metadata")
    path = root / "valid_white_png.png"
    Image.new("RGB", (24, 18), "white").save(path)
    record("valid_white_png", path, True, "Flat white pixels alone do not invalidate an image")

    # Fresh ImageIO PNG may carry this exact technical IFD
    # with dimensions matching the output pixels, plus the standard sRGB chunk.
    technical_fields = {40961: 1, 40962: image.width, 40963: image.height}
    for label, fields, accept, reason in (
        ("valid_png_imageio_technical_exif", technical_fields, True,
         "Exact generated ExifIFD ColorSpace/width/height matches output pixels; sRGB allowed"),
        ("png_technical_exif_extra_tag", {**technical_fields, 37510: b"ASCII\x00\x00\x00SYNTHETIC comment"}, False,
         "Extra UserComment in otherwise permitted technical ExifIFD is forbidden"),
        ("png_technical_exif_wrong_dimensions", {**technical_fields, 40962: image.width + 1}, False,
         "Technical ExifIFD width differs from output pixel width"),
    ):
        technical_exif = Image.Exif()
        technical_exif[34665] = fields
        srgb = PngImagePlugin.PngInfo()
        srgb.add(b"sRGB", b"\x00")
        path = root / f"{label}.png"
        image.save(path, exif=technical_exif, pnginfo=srgb)
        record(label, path, accept, reason)
        cases[-1]["basis"] = "owner_addendum_imageio_technical_exif"

    text = PngImagePlugin.PngInfo()
    text.add_text("Source", "SYNTHETIC original document")
    path = root / "png_text_metadata.png"
    image.save(path, pnginfo=text)
    record("png_text_metadata", path, False, "PNG textual source metadata")
    xmp = PngImagePlugin.PngInfo()
    xmp.add_itxt("XML:com.adobe.xmp", "<synthetic>source metadata</synthetic>")
    path = root / "png_xmp_metadata.png"
    image.save(path, pnginfo=xmp)
    record("png_xmp_metadata", path, False, "PNG iTXt/XMP metadata")

    exif = Image.Exif()
    exif[270] = "SYNTHETIC original image description"
    exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0), 3: "E", 4: (4.0, 5.0, 6.0)}
    for fmt, ext in (("PNG", "png"), ("JPEG", "jpg")):
        path = root / f"{ext}_exif_gps.{ext}"
        image.save(path, format=fmt, exif=exif)
        record(f"{ext}_exif_gps", path, False, "EXIF including synthetic GPS coordinates")

    path = root / "jpeg_xmp_metadata.jpg"
    image.save(path, format="JPEG", xmp=b"<synthetic>original metadata</synthetic>")
    record("jpeg_xmp_metadata", path, False, "JPEG XMP APP1 metadata")
    path = root / "jpeg_comment.jpg"
    image.save(path, format="JPEG", comment=b"SYNTHETIC original metadata")
    record("jpeg_comment", path, False, "JPEG COM arbitrary metadata")
    for ext in ("png", "jpg"):
        path = root / f"{ext}_truncated.{ext}"
        path.write_bytes((root / f"valid_raster_{ext}.{ext}").read_bytes()[:40])
        record(f"{ext}_truncated", path, False, "Truncated image cannot be fully decoded")

    # Independent fixture sanity checks avoid accepting a broken negative corpus.
    clean_pdf = PdfReader(root / "valid_raster_pdf.pdf", strict=True)
    assert clean_pdf.metadata is None and len(clean_pdf.pages) == 1
    assert clean_pdf.pages[0].extract_text() == ""
    assert "SYNTHETIC ORIGINAL TEXT" in PdfReader(root / "pdf_extractable_text.pdf").pages[0].extract_text()
    assert b"/Filespec" in (root / "pdf_orphan_filespec.pdf").read_bytes()
    assert b"/EmbeddedFile" in (root / "pdf_orphan_filespec.pdf").read_bytes()
    assert Image.open(root / "jpg_exif_gps.jpg").getexif().get_ifd(34853)
    assert Image.open(root / "jpeg_xmp_metadata.jpg").info.get("xmp")
    assert Image.open(root / "jpeg_comment.jpg").info.get("comment")
    with Image.open(root / "valid_png_imageio_technical_exif.png") as technical:
        assert set(technical.info) == {"exif", "srgb"} and technical.info["srgb"] == 0
        assert set(technical.getexif()) == {34665}
        assert technical.getexif().get_ifd(34665) == {
            40961: 1, 40962: technical.width, 40963: technical.height
        }
    with Image.open(root / "png_technical_exif_extra_tag.png") as extra:
        assert set(extra.getexif().get_ifd(34665)) == {40961, 40962, 40963, 37510}
    with Image.open(root / "png_technical_exif_wrong_dimensions.png") as mismatch:
        assert mismatch.getexif().get_ifd(34665)[40962] != mismatch.width
    return cases


def probe(verifier: Path, cases: list[dict], timeout: float) -> dict:
    results = []
    for case in cases:
        result = dict(case)
        try:
            run = subprocess.run([sys.executable, str(verifier), case["path"]],
                                 capture_output=True, text=True, timeout=timeout, check=False)
            result["exit_code"] = run.returncode
            result["stderr"] = run.stderr[-1200:]
            try:
                payload = json.loads(run.stdout)
                protocol_ok = isinstance(payload, dict)
                result["output"] = payload
            except (ValueError, TypeError):
                protocol_ok = False
                result["stdout"] = run.stdout[-1200:]
            result["protocol_ok"] = protocol_ok
            result["satisfied"] = bool(protocol_ok and run.returncode >= 0 and
                                        (run.returncode == 0) == case["expect_accept"])
        except subprocess.TimeoutExpired:
            result.update(satisfied=False, error="verifier_timeout")
        results.append(result)
    required = [r for r in results if not r["advisory"]]
    return {"probe_version": 2, "verifier": str(verifier), "python": sys.executable,
            "input_provenance": {
                "profile": "RedactLeaf raster export profile",
                "technical_metadata": "Allows fresh ImageIO PNG EXIF root 34665 only, with "
                                  "ExifIFD 40961=1, 40962=output.width, 40963=output.height, plus sRGB. "
                                  "Source metadata remains forbidden."
            },
            "required_cases": len(required), "passed": sum(r["satisfied"] for r in required),
            "ok": all(r["satisfied"] for r in required), "results": results,
            "limits": [
                "Synthetic parser/container checks only; not proof that all private data was discovered.",
                "No pixel comparison: mask positions, rotation/crop alignment and coverage are not verified.",
                "No iOS lifecycle, cancellation, entitlement, filesystem cleanup or concurrency tests.",
                "Orphan Filespec is advisory: retained bytes violate strict sanitization, but catalog-only scope is ambiguous.",
                "No arbitrary PDF parser equivalence, resource exhaustion or exhaustive malformed-format proof.",
                "Images may validly be flat white; the PDF must actually paint an image, not merely list a resource.",
                "ICC/color rendering policy is not prescribed or tested; normal JPEG JFIF structural fields are allowed.",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verifier", type=Path, help="Python verifier accepting one exported-file path")
    parser.add_argument("--timeout", type=float, default=15, help="Seconds per synthetic input")
    parser.add_argument("--keep-fixtures", type=Path, help="New directory to retain only generated synthetic fixtures")
    args = parser.parse_args()
    verifier = args.verifier.resolve(strict=True)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.keep_fixtures:
        root = args.keep_fixtures.resolve()
        root.mkdir(parents=True, exist_ok=False)
        report = probe(verifier, build_fixtures(root), args.timeout)
    else:
        with tempfile.TemporaryDirectory(prefix="sanitizer-verifier-probe-") as temporary:
            report = probe(verifier, build_fixtures(Path(temporary)), args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
