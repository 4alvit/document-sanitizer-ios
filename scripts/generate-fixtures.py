#!/usr/bin/env python3
"""Create only synthetic public-safe hostile document containers for QA."""
import argparse
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject
from PIL import Image, ImageDraw, PngImagePlugin


def pdf(path: Path, rotation: int, cropped: bool, pages: int = 1) -> None:
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    for _ in range(pages):
        page = writer.add_blank_page(width=200, height=160)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)}),
            NameObject('/ExtGState'): DictionaryObject({
                NameObject('/Half'): DictionaryObject({
                    NameObject('/Type'): NameObject('/ExtGState'),
                    NameObject('/ca'): FloatObject(.5),
                }),
            }),
        })
        content = DecodedStreamObject()
        # Asymmetric corner markers expose flips, rotations and crop errors.
        content.set_data(b'1 1 1 rg 0 0 200 160 re f\n1 0 0 rg 24 112 28 24 re f\n0 0 1 rg 148 24 28 24 re f\n0 0.7 0 rg 64 44 20 32 re f\n0 0 0 rg BT /F1 12 Tf 24 92 Td (SYNTHETIC SECRET123) Tj ET\nq /Half gs 1 0 1 rg 78 104 36 18 re f Q\n')
        page[NameObject('/Contents')] = writer._add_object(content)
        page[NameObject('/Rotate')] = NumberObject(rotation)
        if cropped:
            page[NameObject('/CropBox')] = ArrayObject([NumberObject(n) for n in [20, 20, 180, 140]])
        annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Text'), NameObject('/Rect'): ArrayObject([NumberObject(n) for n in [2, 2, 12, 12]]), NameObject('/Contents'): TextStringObject('SYNTHETIC_HIDDEN_NOTE')})
        # A pre-existing visible opaque annotation must remain visible in the
        # raster. Dropping annotation objects before rendering can expose text.
        appearance = DecodedStreamObject()
        appearance.set_data(b'0 0 0 rg 0 0 156 21 re f\n')
        appearance.update({
            NameObject('/Type'): NameObject('/XObject'),
            NameObject('/Subtype'): NameObject('/Form'),
            NameObject('/BBox'): ArrayObject([NumberObject(n) for n in [0, 0, 156, 21]]),
            NameObject('/Resources'): DictionaryObject(),
        })
        overlay = DictionaryObject({
            NameObject('/Type'): NameObject('/Annot'),
            NameObject('/Subtype'): NameObject('/Square'),
            NameObject('/Rect'): ArrayObject([NumberObject(n) for n in [22, 86, 178, 107]]),
            NameObject('/F'): NumberObject(4),
            NameObject('/C'): ArrayObject([NumberObject(0)] * 3),
            NameObject('/IC'): ArrayObject([NumberObject(0)] * 3),
            NameObject('/AP'): DictionaryObject({NameObject('/N'): writer._add_object(appearance)}),
        })
        page[NameObject('/Annots')] = ArrayObject([writer._add_object(annotation), writer._add_object(overlay)])
    writer.add_metadata({'/Author': 'SYNTHETIC_PERSON_42', '/Title': 'PRIVATE_SYNTHETIC_TITLE'})
    writer.add_attachment('synthetic-notes.txt', b'SYNTHETIC_ATTACHMENT_MUST_NOT_SURVIVE')
    writer.add_js("/* SYNTHETIC_ONLY_MUST_NOT_SURVIVE */")
    with path.open('wb') as handle:
        writer.write(handle)


def generate(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for rotation in [0, 90, 180, 270]:
        for cropped in [False, True]:
            pdf(directory / f'rotation-{rotation}-crop-{int(cropped)}.pdf', rotation, cropped)
    pdf(directory / 'multipage.pdf', 90, True, 3)
    image = Image.new('RGBA', (400, 300), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 30, 95, 85), fill=(255, 0, 0, 255))
    draw.rectangle((295, 210, 365, 265), fill=(0, 0, 255, 128))
    draw.text((35, 130), 'SYNTHETIC SECRET123', fill=(0, 0, 0, 255))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Author', 'SYNTHETIC_PERSON_42')
    metadata.add_text('Comment', 'SYNTHETIC_METADATA_MUST_NOT_SURVIVE')
    image.save(directory / 'transparent-metadata.png', pnginfo=metadata)
    rgb = Image.new('RGB', image.size, 'white')
    rgb.paste(image, mask=image.getchannel('A'))
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = 'SYNTHETIC_PERSON_42'
    exif[270] = 'SYNTHETIC_METADATA_MUST_NOT_SURVIVE'
    rgb.save(directory / 'orientation-6.jpg', exif=exif, quality=95)
    (directory / 'not-a-pdf.pdf').write_bytes(b'not a PDF; entirely synthetic')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    generate(parser.parse_args().directory)

