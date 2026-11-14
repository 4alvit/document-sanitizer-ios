"""Keep hostile corpus payloads present when the PDF/image dependencies change."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pypdf import PdfReader

SPEC = importlib.util.spec_from_file_location("corpus_fixtures", Path(__file__).with_name("generate-fixtures.py"))
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class HostileCorpusTests(unittest.TestCase):
    def test_every_pdf_profile_retains_original_actions_attachments_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            GENERATOR.generate(root)
            paths = [p for p in root.glob("*.pdf") if p.name != "not-a-pdf.pdf"]
            self.assertEqual(len(paths), 9)
            for path in paths:
                with self.subTest(profile=path.name):
                    reader = PdfReader(path)
                    catalog = reader.trailer["/Root"]
                    actions = catalog["/Names"]["/JavaScript"]["/Names"][1::2]
                    self.assertTrue(actions)
                    self.assertTrue(any(action.get_object()["/S"] == "/JavaScript"
                                        and "SYNTHETIC_ONLY_MUST_NOT_SURVIVE" in action.get_object()["/JS"]
                                        for action in actions))
                    self.assertTrue(catalog["/Names"]["/EmbeddedFiles"]["/Names"])
                    self.assertEqual(reader.metadata.author, "SYNTHETIC_PERSON_42")
                    self.assertTrue(all("SYNTHETIC SECRET123" in page.extract_text()
                                        and page["/Annots"] for page in reader.pages))
            with Image.open(root / "transparent-metadata.png") as image:
                self.assertEqual(image.info["Author"], "SYNTHETIC_PERSON_42")
                self.assertIn("A", image.getbands())
            with Image.open(root / "orientation-6.jpg") as image:
                self.assertEqual(image.getexif()[274], 6)
                self.assertEqual(image.getexif()[315], "SYNTHETIC_PERSON_42")
