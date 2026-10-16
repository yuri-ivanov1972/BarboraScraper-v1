# Regular photo maintenance

The daily scheduler now collects `big_image` / `image` candidates from category
listings already fetched for prices. Photo candidates are metadata only, not
proof that a CDN image is reachable. Photo failures do not roll back prices.

## Enable safely

Open **Nutri-Score Tools → Fix Broken Photos** in the app connected to the
intended database:

1. Initialize the additive tracking tables if prompted.
2. Run a bounded check with **Save verification results…** unchecked.
3. Review the preview, especially blocked hosts and unknown photo ownership.
4. Explicitly protect manual photos or approve retailer ownership, individually
   or for the filtered report. Existing ownership defaults to unknown.
5. Confirm that the preview was reviewed and enable daily maintenance.

Automatic writes are **off by default**, separately for each database. The
scheduler still collects candidates while writes are off. Once enabled, the
post-price pass attempts at most 1,500 due photo/report rows with a 20-minute
budget. Individual HTTP and database operations have timeouts; an in-flight
operation can finish after the budget. Due work remains queued.

New/changed URLs without prior verification are due first. Unchanged working
URLs are due after seven days. Failed checks are due after one day. On a host
403/401/429, stop the pass and persist a one-day host cooldown. A weekly sweep
is a target, not a promise while a host is restricted.

## Safety

- A small streamed HTTPS GET verifies content type and image magic. Redirects
  are deferred rather than followed to untrusted hosts.
- 403/429, invalid content, redirects, timeouts and 5xx are not missing-photo
  verdicts. Missing requires 404/410 evidence on two attempts at least a day
  apart; no photos are deleted by the maintenance pass.
- Only validated listing candidates may replace explicitly retailer-managed
  primaries. Unknown/manual photos and secondary images are preserved.
- Secondary CDN URLs are checked and reported, not silently removed.
- Only latest-price-history available products are eligible. Availability,
  ownership, candidate and photo identity are rechecked before replacement.
- URL checks are deduplicated within a pass. A database lease prevents
  overlapping checks, and database connections are closed during network work.
- A preview changes neither photo URLs nor verification results; a temporary
  run lease is its only tracking write.
- Legacy scraper gallery writes now only fill empty, unprotected galleries.
  Product-card refreshes preserve manual/unknown galleries once tracking exists.

The website reads the existing `productphotos` table directly. Photo IDs and
unrelated gallery rows are preserved on primary replacements. Website caches,
image proxies and browser rendering must be verified in that project's runtime;
reachability from this scraper does not prove reachability from every host.

## CLI

These commands use the current application's `DATABASE_URL`; they never select
production automatically:

```sh
python photo_maintenance.py --initialize
python photo_maintenance.py --limit 25             # bounded preview
python photo_maintenance.py --apply --limit 25     # explicit bounded writes
```

Initialization does not enable scheduled writes. Do not run the old full-scan
photo-fix command as a daily job; it lacks the new queue/cooldown scheduling.
