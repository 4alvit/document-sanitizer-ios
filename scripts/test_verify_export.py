"""Focused verifier regression tests; all bytes are synthetic and temporary."""
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from verify_export import EMPTY_IPTC, VerificationError, verify_export


class VerifyExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="cleansend-verifier-tests-")
        self.path = Path(self.directory.name) / "synthetic"

    def tearDown(self):
        self.directory.cleanup()

    def check_bytes(self, data, accepted):
        self.path.write_bytes(data)
        if accepted:
            self.assertTrue(verify_export(self.path)["ok"])
        else:
            with self.assertRaises((VerificationError, OSError, ValueError)):
                verify_export(self.path)

    @staticmethod
    def image_bytes(format="PNG", mode="RGB"):
        data = io.BytesIO()
        Image.new(mode, (12, 8), "white").save(data, format=format)
        return data.getvalue()

    @staticmethod
    def pdf_writer():
        writer = PdfWriter()
        writer.metadata = None
        page = writer.add_blank_page(12, 8)
        image = DecodedStreamObject()
        image.set_data(bytes([255]) * 12 * 8 * 3)
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(12), NameObject("/Height"): NumberObject(8),
                      NameObject("/BitsPerComponent"): NumberObject(8), NameObject("/ColorSpace"): NameObject("/DeviceRGB")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({
            NameObject("/Im0"): writer._add_object(image)})})
        content = DecodedStreamObject()
        content.set_data(b"q 12 0 0 8 0 0 cm /Im0 Do Q\n")
        page[NameObject("/Contents")] = writer._add_object(content)
        return writer

    def check_pdf(self, writer, accepted):
        data = io.BytesIO()
        writer.write(data)
        self.check_bytes(data.getvalue(), accepted)

    def test_white_images_are_valid_but_alpha_is_not(self):
        self.check_bytes(self.image_bytes(), True)
        self.check_bytes(self.image_bytes("JPEG"), True)
        self.check_bytes(self.image_bytes(mode="RGBA"), False)

    def test_png_unknown_chunk_and_trailing_bytes_are_rejected(self):
        data = self.image_bytes()
        kind, payload = b"vpAg", b"SYNTHETIC original payload"
        chunk = struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
        self.check_bytes(data[:-12] + chunk + data[-12:], False)
        self.check_bytes(data + b"SYNTHETIC trailing payload", False)

    def test_jpeg_empty_iptc_is_exactly_allowlisted(self):
        data = self.image_bytes("JPEG")
        segment = lambda value: b"\xff\xed" + struct.pack(">H", len(value) + 2) + value
        self.check_bytes(data[:2] + segment(EMPTY_IPTC) + data[2:], True)
        self.check_bytes(data[:2] + segment(EMPTY_IPTC + b"SOURCE") + data[2:], False)

    def test_jpeg_comment_after_scan_and_trailing_data_are_rejected(self):
        data = self.image_bytes("JPEG")
        comment = b"\xff\xfe\x00\x08SOURCE"
        self.check_bytes(data[:-2] + comment + data[-2:], False)
        self.check_bytes(data + b"SOURCE", False)

    def test_pdf_generated_metadata_and_invalid_dates(self):
        writer = self.pdf_writer()
        writer.add_metadata({"/Creator": "RedactLeaf", "/Producer": "Quartz PDFContext",
                             "/CreationDate": "D:20261020120000Z00'00'"})
        self.check_pdf(writer, True)
        writer.add_metadata({"/Creator": "Arbitrary source application"})
        self.check_pdf(writer, False)
        writer.add_metadata({"/Creator": "RedactLeaf"})
        writer.add_metadata({"/CreationDate": "D:20260231120000Z"})
        self.check_pdf(writer, False)

    def test_pdf_hidden_strings_in_procset_rejected(self):
        writer = self.pdf_writer()
        writer.pages[0]["/Resources"][NameObject("/ProcSet")] = ArrayObject([TextStringObject("SYNTHETIC private data")])
        self.check_pdf(writer, False)

    def test_pdf_zero_area_paint_rejected(self):
        writer = self.pdf_writer()
        writer.pages[0]["/Contents"].set_data(b"q 0 0 0 0 0 0 cm /Im0 Do Q\n")
        self.check_pdf(writer, False)

    def test_pdf_unused_orphan_and_content_comment_rejected(self):
        writer = self.pdf_writer()
        writer._add_object(TextStringObject("SYNTHETIC orphan data"))
        self.check_pdf(writer, False)
        writer = self.pdf_writer()
        writer.pages[0]["/Contents"].set_data(b"% SYNTHETIC retained comment\nq 12 0 0 8 0 0 cm /Im0 Do Q\n")
        self.check_pdf(writer, False)


if __name__ == "__main__":
    unittest.main()
