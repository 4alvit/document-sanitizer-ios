# Threat model and export contract

The user wants to send a selected copy while retaining their original unchanged.
Inputs can contain hidden text, annotations, actions, attachments, metadata,
rotated/cropped pages, transparency and oversized resources. Both input parsing
and OCR use Apple platform parsers; RedactLeaf is not a sandbox against operating
system parser vulnerabilities.

The page representation is an upright, bounded, opaque raster. All mask geometry
is normalized from its top-left. Preview and export use the same burn-in path.
Output is newly encoded: no source PDF object tree or source image metadata is
copied. A PDF output contains new raster pages, not original PDF pages with
overlay rectangles. Invalid masks are errors, never ignored silently.

Image-only output loses selectable text, form fields, hyperlinks, signatures,
source accessibility semantics and potentially print resolution. Input files
are never overwritten. The user must inspect every page before sharing. OCR
can miss text and cannot establish that an image contains no personal data.

Non-goals: long-term secret storage, secure erasure of flash storage, removal of
copies already sent, reliable automatic detection of all personal information,
legal/compliance certification, cryptographic signing and preservation of vector
fidelity. Users and recipient applications may create additional copies.

Resource limits, cancellation, fresh output paths and cleanup prevent common
accidental failures. The app and share extension use temporary app-owned copies;
they cannot delete copies created by Files, Photos or the recipient. A cancelled
operation must not publish a partially completed export. Free/Pro entitlement
changes must not obstruct reading or basic export of an already loaded packet.

Reusable presets retain only named geometry. Coordinates refer to the upright
raster, not the source PDF coordinate system or the current screen layout.
Applying a preset does not identify the document or align its fields. The user
previews placement on the selected page and still reviews every page before
export. Applying new areas preserves existing masks and invalidates an earlier
review. Invalid stored rectangles fail closed; they are not silently skipped.

Independent verification must examine emitted files with a second parser and
renderer. It checks metadata/object structure, extracted text, raster geometry,
black mask placement, preservation of unmasked content, rotation/crop behavior
and alpha compositing. A parser's clean report is a bounded technical check,
not a certification of the contents.

