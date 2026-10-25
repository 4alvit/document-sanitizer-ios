# Privacy policy — prerelease

RedactLeaf processes selected images and PDF documents on the user's device.
It does not require an account and does not operate a document upload server.
This prerelease includes no advertising, analytics or crash-reporting SDK.

The app uses temporary copies of selected files while preparing an export.
Documents shared to its extension are queued in its app-group container until
the main app imports them or the user discards them. The queue is excluded from
backups and uses complete file protection. Copies older than 24 hours are removed
when the main app next checks the queue, not by a guaranteed background erasure
service. Files in an active import are retained until that operation finishes.
Exported files are handed to the system share sheet;
the destination the user selects controls its own copies and privacy practices.
Clearing the workspace cannot delete already shared files from other apps.

Saved mask presets persist across app launches in protected local application
storage excluded from backups. A preset contains a name entered by the user and
rectangle coordinates. It contains no document image, thumbnail, recognized text,
source filename or file URL. Presets do not sync to a server. Clearing temporary
documents does not clear presets; delete them in the preset library. Resetting
the library removes all saved presets, including when recovering a damaged
library. Previously applied areas on an open document are unchanged by deletion.

OCR runs using Apple's Vision framework on the device. Purchasing Pro uses
Apple's StoreKit and App Store. Apple processes the purchase under its own terms;
RedactLeaf reads the resulting entitlement without collecting payment details.

For support, use a synthetic document and do not submit personal files through
public GitHub issues. Support information a user chooses to post is public.
This policy must be reviewed against the final shipping binary, extension and
App Store privacy questionnaire before a public App Store submission.

