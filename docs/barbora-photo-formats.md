# Barbora photo compatibility

abcde.lv reads this database directly and cannot display AVIF. Automatic image
selection therefore prefers an **actually advertised PNG**, then compatible
JPEG/WebP/GIF. It never guesses a PNG by changing an AVIF extension.

The shared selector handles original/image arrays, product-gallery pictures,
source/srcset and img fallbacks. It groups known format and size variants of the
same Barbora asset, keeps the best advertised rendition, and preserves distinct
gallery views and primary order. Listing-card alternatives must match the
structured product's asset identity.

Saving paths reject unsupported URLs even if a caller bypasses the parser.
Automatic fills never replace existing galleries. Scheduled retailer-primary
replacement retains manual/unknown ownership and externally edited photos;
an existing secondary-gallery variant requires review instead of duplication.
Reviewed full-product refreshes keep their existing preview, ownership and
concurrency protections.

Verification requests supported formats and checks both MIME type and bytes.
AVIF is `unsupported_format`, not working or missing. HTTP 403/429 remains
access-blocked, not proof of a missing image.

## Bounded production preview

```sh
python photo_format_preview.py --production --confirm-production \
  --limit 20 --seconds 120 \
  --output generated-artifacts/photo-format-preview
```

The database connection is read-only: no lease, schema, photo, ownership or
verification-cache changes. Affected primary, gallery, candidate and managed
URLs are inventoried. Only available, non-manual products are fetched, and
the page must confirm the exact SKU. Suggestions are restricted to supported
alternatives for the **same image asset**, never a different product or view.
Host denial stops further checks on that host.

`preview.json` includes the target fingerprint, timestamps, complete selected
gallery/ownership baselines and checksum. `links.csv` is the review report.
Unknown ownership, unavailable products, manual photos, unverified alternatives,
external edits and secondary-gallery ownership remain protected.

There is deliberately **no Apply command** in this preview tool. Repairing
existing production URLs requires explicit approval and fresh source/baseline
checks. Publishing the parser fix alone does not backfill existing photos.
