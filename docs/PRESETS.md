# Local mask presets

A preset saves the selected page's masked areas as a reusable layout. It stores
a user-chosen name and normalized rectangles. It does not save a document,
thumbnail, recognized text or source filename.

## Create and use

1. Import a document and mark areas on the selected page.
2. Save those areas under a name while Pro is available. The save operation
   checks access again; opening the naming screen does not reserve Pro access.
3. On another selected page, choose a saved preset and inspect its actual
   rendered placement. Cancel leaves the document unchanged.
4. Apply to add the proposed areas. Existing areas remain; identical rectangles
   are not duplicated. The action targets only the selected page.
5. Open the final review and check every page before export. Preset placement
   preview is not final export approval.

Using and deleting saved presets remains available when Pro is refunded or
unavailable. Deleting a preset leaves its already applied document areas intact.
New paid-capacity imports are governed separately by the batch limit.

## Placement and review

Coordinates are fractions of the visually upright page, measured from its
top-left corner. Screen orientation and zoom do not change them. A different
page size or aspect ratio can place the same fractions over different content.
Presets do not recognize forms, align fields, rotate themselves to match a
document or find personal information.

Preview uses the same raster sanitizer as final review and export. Applying a
new area invalidates an existing review; a repeated application that adds
nothing preserves it. A stale or cancelled preview cannot change a newer
workspace. Invalid geometry is rejected rather than omitted.

## Storage and recovery

The library is versioned local application data, outside the temporary document
workspace. It uses file protection, excludes its storage from backups and does
not sync. App restart clears temporary documents but retains the library.

Limits are 50 presets, 80 characters per name, 200 rectangles per preset and
1 MiB for the stored library. Names are display labels, never file paths.
Saving and deletion replace the library atomically; a failed write preserves
the previous library. Unsupported or damaged storage produces an error and
blocks ordinary changes. Retry loading after a temporary storage problem, or
explicitly confirm a library reset to discard the saved presets.

These are convenience layouts. Their presence does not certify that all
private details have been hidden.

## Development checks

Hosted `MaskPresetStoreTests` and `PresetApplicationTests` cover persistence,
authorization, geometry, cancellation, stale previews and review invalidation.
Run the dedicated interface gate on a newly created private simulator:

```sh
bash scripts/check-ios-presets.sh iPhone
bash scripts/check-ios-presets.sh iPad
```

The gate seeds one synthetic geometry preset into that simulator's application
data and runs at the largest system text size. It never changes entitlements.
Both UI cases must pass without skips. Running the seeded UI case without its
fixture produces an explicit skip and does not satisfy this gate. Creating a
preset through an actual Pro purchase remains part of native payment integration.

The complete-file-protection metadata test explicitly skips Simulator: its
`FileManager` does not expose this protection class reliably, as discussed by
[Apple Developer Technical Support](https://developer.apple.com/forums/thread/780632).
Backup exclusion is still tested on Simulator. The physical-device protection
test must run before release, followed by a passcode lock/unlock check; a
Simulator pass does not establish protection of data on a locked device.
