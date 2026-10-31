#!/usr/bin/env python3
"""Write a small, clearly synthetic two-page PDF for real Files-picker QA."""

from pathlib import Path
import sys


def make_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for page, content_object in [(1, 5), (2, 7)]:
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_object} 0 R >>".encode()
        )
        content = (
            "BT /F1 18 Tf 24 350 Td (SYNTHETIC QA DOCUMENT) Tj "
            f"0 -36 Td (Page {page} of 2) Tj /F1 12 Tf "
            "0 -36 Td (No real personal information.) Tj "
            f"0 -24 Td (Review marker: SAMPLE-{page:02d}) Tj ET\n"
        ).encode()
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream")
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: make-accessibility-fixture.py OUTPUT.pdf")
    target = Path(sys.argv[1])
    # The caller supplies an existing directory belonging to its private test
    # simulator. Never overwrite a pre-existing document.
    with target.open("xb") as output:
        output.write(make_pdf())
    print(f"Created synthetic two-page Files fixture: {target}")
