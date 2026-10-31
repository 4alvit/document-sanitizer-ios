# Changelog

## 0.1.0 — unreleased

- Preserve the original attachment order when importing older shared batches
  with ten or more files, including through PDF export.
- Clear only displayed, completed shared batches. Preserve active extension
  copies, newly arrived batches and cancelled imports while their workers finish.
  Only the main app prunes expired batches, respecting its active imports.
- Reject preset rectangles whose positive width or height disappears during
  floating-point addition. Keep representable subpixel areas supported.
- Read fresh preset-library file attributes. Reject symbolic links, including
  dangling links, without treating them as a missing library or following targets.
- Recognize supported image containers before using PDF header or filename hints,
  so a PDF marker inside image metadata does not break image import.
- Show specific recovery instructions for known import failures while keeping
  arbitrary provider error descriptions out of the interface.
- Record the first-pending-purchase StoreKit reproduction without a prior refund.
  Payment acceptance remains open; this is still a local development preview.
